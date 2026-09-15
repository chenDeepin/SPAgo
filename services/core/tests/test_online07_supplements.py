"""ONLINE-07: manually added literature rows.

The scientific point: a target whose retrieved set is thin or all-weak can be
supplemented by hand, and the supplement must stay *separately attributable* — its
own provenance state, its own store, its own count — so a reader never mistakes a
person's claim for a source's measurement. Driven end to end (HTTP → validation →
RDKit → RDKit-cartridge descriptors → stored rows → verdict → export), the path pins:

- that a row without a note is refused, because the note is the row's provenance;
- that a value without a stated endpoint is refused instead of being assumed to be
  an IC50;
- that one bad row does not refuse the rest of the batch, and nothing is dropped
  silently;
- that a user-added structure is *one* compound: the same InChIKey as the corpus
  one, with the same cartridge-derived descriptors as a patent-derived compound;
- that a structure-less row is kept as a remark, counted in the verdict, and never
  counted as a compound or a measurement;
- that re-posting a row updates it rather than duplicating one literature claim;
- that an export states `user_curated` for these rows instead of claiming a curated
  database fact.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.bioactivity_base import ActivityRecord
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.chemistry.activities import DEFAULT_THRESHOLD_NM
from spago_core.db import run_migrations
from spago_core.domain import MAX_SUPPLEMENT_ROWS, EvidenceClass
from spago_core.main import create_app
from spago_core.services import ai
from spago_core.services.discovery import TargetDiscoveryService
from spago_core.services.reference import policy_from_settings, reference_verdict
from spago_core.services.supplements import import_supplements
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import (
    StubActivityAdapter,
    StubSourceClient,
    load_fixture,
)

SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
OTHER_SMALL_MOLECULE = "CC(=O)Oc1ccccc1C(=O)O"
#: Two different SMILES strings for one structure (the free acid and its sodium
#: salt): identity is the InChIKey, not the submitted string.
SAME_STRUCTURE_OTHER_FORM = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)[O-])cc2)cc1.[Na+]"


class _Settings:
    def __init__(self, threshold_nm: float = DEFAULT_THRESHOLD_NM, min_compounds: int = 10):
        self.activity_threshold_nm = threshold_nm
        self.activity_min_compounds = min_compounds


def policy(threshold_nm: float = DEFAULT_THRESHOLD_NM, min_compounds: int = 10, **kwargs):
    return policy_from_settings(
        _Settings(threshold_nm, min_compounds), **kwargs  # type: ignore[arg-type]
    )


def row(name: str, note: str = "checked in the paper's Table 2", **overrides) -> dict:
    payload = {"name": name, "note": note}
    payload.update(overrides)
    return payload


def active_row(name: str, smiles: str, value: float = 4.0, **overrides) -> dict:
    payload = row(
        name,
        smiles=smiles,
        activity_type="IC50",
        value=value,
        unit="nM",
        **overrides,
    )
    return payload


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_online_tables(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


@pytest.fixture()
def resolved_target(online_engine):
    resolver = UniProtTargetResolver(
        client=StubSourceClient({"uniprotkb/search": load_fixture("uniprot_TSLP_human.json")})
    )
    outcome = TargetResolutionService(uniprot=resolver).resolve(online_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


def _uniprot_payload(accession: str, gene: str, protein: str) -> dict:
    """The TSLP fixture re-labelled as another human target, so a second target row
    is real (resolved through the same service) instead of hand-inserted."""
    payload = json.loads(json.dumps(load_fixture("uniprot_TSLP_human.json")))
    hit = payload["results"][0]
    hit["primaryAccession"] = accession
    hit["uniProtkbId"] = f"{gene}_HUMAN"
    hit["proteinDescription"]["recommendedName"]["fullName"]["value"] = protein
    for entry in hit.get("genes", []):
        entry["geneName"]["value"] = gene
    return payload


def _second_human_target_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "CD40LG" in query or "P29965" in query:
        return _uniprot_payload("P29965", "CD40LG", "CD40 ligand")
    return _uniprot_route(call)


def _app(online_engine, discovery: TargetDiscoveryService | None = None):
    app = create_app()
    app.state.engine = online_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    if discovery is not None:
        app.state.discovery_service = discovery
    return app


@pytest.fixture()
def client(online_engine):
    return TestClient(_app(online_engine))


def investigate(engine, target, records):
    service = TargetDiscoveryService(
        chembl=StubActivityAdapter(records),
        bindingdb=StubActivityAdapter([]),
        pubchem=PubChemAdapter(client=StubSourceClient({})),
    )
    service.investigate(engine, target, sources=["chembl"])
    return service


def corpus_record(record_id: str, smiles: str, **overrides) -> ActivityRecord:
    """One retrieved record, as an adapter would stamp it."""
    payload = dict(
        source_record_id=record_id,
        compound_source_id=smiles,
        target_key="CHEMBL_STUB",
        assay_key=f"STUB:ASSAY:{record_id}",
        assay_type="B",
        standard_type="IC50",
        value=43_000.0,
        unit="nM",
        relation="=",
        evidence_class=EvidenceClass.MEASURED_DIRECT_BINDING,
        raw_value="43000",
        raw_smiles=smiles,
        source_molecule_id=record_id,
        source_name="chembl",
        source_dataset_version="chembl:2026-09-15",
    )
    payload.update(overrides)
    return ActivityRecord(**payload)


class TestRefusals:
    """A row that cannot be classified is refused with a reason, never guessed at."""

    def test_a_row_without_a_note_is_refused(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [{"name": "compound 7", "smiles": SMALL_MOLECULE, "activity_type": "IC50",
              "value": 4.0, "unit": "nM"}],
        )
        assert result.measurements == 0
        assert result.rows[0].status == "rejected"
        assert any("note" in reason for reason in result.rows[0].reasons)
        assert _count(online_engine, "measurements") == 0
        assert _count(online_engine, "compounds") == 0

    def test_a_value_without_an_endpoint_is_refused(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [row("compound 7", smiles=SMALL_MOLECULE, value=4.0)],
        )
        assert result.rows[0].status == "rejected"
        assert any("activity_type" in reason for reason in result.rows[0].reasons)
        assert _count(online_engine, "compounds") == 0

    def test_an_endpoint_without_a_value_is_refused(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [row("compound 7", smiles=SMALL_MOLECULE, activity_type="IC50", unit="nM")],
        )
        assert result.rows[0].status == "rejected"
        assert any("without a value" in reason for reason in result.rows[0].reasons)

    def test_an_unknown_row_field_is_refused(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [active_row("compound 7", SMALL_MOLECULE, potency="potent")],
        )
        assert result.rows[0].status == "rejected"
        assert any("potency" in reason for reason in result.rows[0].reasons)

    def test_an_unparseable_structure_refuses_only_that_row(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [
                active_row("compound 7", "N=C(N)this-is-not-valid-smiles"),
                active_row("compound 8", SMALL_MOLECULE),
            ],
        )
        assert [outcome.status for outcome in result.rows] == ["rejected", "measurement"]
        assert any("unparseable_structure" in reason for reason in result.rows[0].reasons)
        assert result.rows[0].index == 0 and result.rows[1].index == 1
        assert result.measurements == 1
        assert _count(online_engine, "compounds") == 1

    def test_a_row_without_a_structure_is_a_remark_not_a_compound(
        self, online_engine, resolved_target
    ):
        result = import_supplements(
            online_engine,
            resolved_target.id,
            [
                row(
                    "Markush example 12",
                    note="IC50 3 nM read from the patent table; no public SMILES",
                    activity_type="IC50",
                    value=3.0,
                    unit="nM",
                    patent_number="WO 2019/047734",
                )
            ],
        )
        assert result.remarks == 1
        assert result.measurements == 0
        assert result.rows[0].status == "remark"
        assert any("without a structure" in reason for reason in result.rows[0].reasons)
        assert _count(online_engine, "compounds") == 0
        assert _count(online_engine, "measurements") == 0
        with online_engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT note, provenance_state, patent_number FROM target_supplement_remarks"
                )
            ).mappings().one()
        assert stored["provenance_state"] == "user_curated"
        # The note is preserved verbatim, and the patent number is normalized.
        assert "no public SMILES" in stored["note"]
        assert stored["patent_number"] == "WO2019047734"


def _count(engine, table: str, where: str = "") -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(text(f"SELECT count(*) FROM {table} {where}")).scalar_one()
        )


class TestIdentityAndChemistry:
    """A user-added structure is the same kind of object as a retrieved one."""

    def test_a_structure_already_in_the_corpus_is_reused(self, online_engine, resolved_target):
        investigate(
            online_engine, resolved_target, [corpus_record("r1", SMALL_MOLECULE)]
        )
        before = _count(online_engine, "compounds")

        result = import_supplements(
            online_engine,
            resolved_target.id,
            [active_row("compound 7", SMALL_MOLECULE)],
        )

        assert result.compounds_created == 0
        assert result.compounds_reused == 1
        assert result.rows[0].reused_compound is True
        assert _count(online_engine, "compounds") == before

    def test_a_salt_form_is_not_merged_into_its_parent(self, online_engine, resolved_target):
        """AGENTS.md §28: different salts are different compounds, stated explicitly."""
        first = import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE)]
        )
        second = import_supplements(
            online_engine,
            resolved_target.id,
            [active_row("compound 7", SAME_STRUCTURE_OTHER_FORM)],
        )
        assert first.compounds_created == 1
        assert second.compounds_created == 1
        assert second.rows[0].reused_compound is False
        assert second.rows[0].inchikey != first.rows[0].inchikey
        with online_engine.connect() as conn:
            multi = conn.execute(
                text("SELECT is_multi_component FROM compounds WHERE inchikey = :k"),
                {"k": second.rows[0].inchikey},
            ).scalar_one()
        # The salt is stored as the multi-component structure it is; nothing silently
        # strips the counter-ion to make it look like the same molecule.
        assert multi is True
        assert _count(online_engine, "compounds") == 2

    def test_descriptors_are_filled_by_the_cartridge(self, online_engine, resolved_target):
        """The external path must carry the same chemistry columns as ingestion."""
        import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE)]
        )
        with online_engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT c.inchi, c.molecular_formula, c.molecular_weight, c.hbd, c.hba, "
                       "c.tpsa, c.logp, c.has_stereo, c.modality, c.modality_rule, "
                       "c.modality_source, c.scaffold "
                    "FROM compounds c"
                )
            ).mappings().one()
        assert stored["inchi"].startswith("InChI=1S/")
        assert stored["molecular_formula"]
        assert stored["molecular_weight"] > 200
        assert stored["hbd"] >= 1 and stored["hba"] >= 1
        assert stored["tpsa"] > 0
        assert stored["logp"] is not None
        assert stored["has_stereo"] is False
        assert stored["modality"] == "small_molecule"
        assert stored["modality_source"] == "rdkit"
        assert stored["modality_rule"]
        assert stored["scaffold"]

    def test_the_stored_row_states_it_was_added_by_a_person(self, online_engine, resolved_target):
        import_supplements(
            online_engine,
            resolved_target.id,
            [
                active_row(
                    "compound 7",
                    SMALL_MOLECULE,
                    note="Table 2, IC50 against human TSLP",
                    doi="10.1000/example",
                )
            ],
        )
        with online_engine.connect() as conn:
            measurement = conn.execute(
                text(
                    "SELECT source_name, provenance_state, extraction_method, assay_description, "
                       "document_doi, evidence_class, dataset_version FROM measurements"
                )
            ).mappings().one()
            candidate = conn.execute(
                text("SELECT source_name, evidence_class, modality FROM target_candidates")
            ).mappings().one()
            assay = conn.execute(
                text("SELECT source_name, assay_type, target_id FROM assays")
            ).mappings().one()
        assert measurement["source_name"] == "user_supplement"
        assert measurement["provenance_state"] == "user_curated"
        assert measurement["extraction_method"] == "user_supplement"
        assert measurement["document_doi"] == "10.1000/example"
        assert measurement["dataset_version"] == "user-supplement:v1"
        # A person's row is not dressed up as a direct binding measurement.
        assert measurement["evidence_class"] != EvidenceClass.MEASURED_DIRECT_BINDING.value
        # The note travels with the row as its provenance, not as a source's assay text.
        assert measurement["assay_description"] == "Table 2, IC50 against human TSLP"
        assert candidate["source_name"] == "user_supplement"
        assert candidate["modality"] == "small_molecule"
        assert assay["source_name"] == "user_supplement"
        # The synthetic assay is attached to the target it was added for.
        assert str(assay["target_id"]) == str(resolved_target.id)


class TestVerdict:
    """Supplements are visible in the verdict, and they never inflate it silently."""

    def test_an_active_supplement_makes_the_set_a_reference(self, online_engine, resolved_target):
        investigate(
            online_engine, resolved_target, [corpus_record("r1", OTHER_SMALL_MOLECULE)]
        )
        assert reference_verdict(online_engine, resolved_target, policy()).qualifies is False

        import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE, 4.0)]
        )

        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.qualifies is True
        assert verdict.compounds_active == 1
        assert verdict.best_active is not None
        assert verdict.best_active.source_name == "user_supplement"
        assert verdict.best_active.potency_label == "IC50 4 nM"

    def test_a_remark_is_counted_and_stated_in_the_reason(self, online_engine, resolved_target):
        investigate(
            online_engine, resolved_target, [corpus_record("r1", OTHER_SMALL_MOLECULE)]
        )
        import_supplements(
            online_engine,
            resolved_target.id,
            [
                row(
                    "example 12",
                    note="IC50 3 nM in the patent table; structure not published",
                    activity_type="IC50",
                    value=3.0,
                    unit="nM",
                )
            ],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.supplement_remarks == 1
        assert "literature remark" in verdict.reason
        # A remark is not a compound and not a measurement: the retrieved set is
        # unchanged, and the reader is told a claim exists that SPAgo cannot draw.
        assert verdict.compounds == 1
        assert verdict.measurements == 1

    def test_a_supplement_does_not_change_another_target(self, online_engine, resolved_target):
        other = TargetResolutionService(
            uniprot=UniProtTargetResolver(
                client=StubSourceClient(
                    {"uniprotkb/search": _second_human_target_route}
                )
            )
        ).resolve(online_engine, "CD40LG", "human")
        assert other.target is not None
        import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE)]
        )
        verdict = reference_verdict(online_engine, other.target, policy())
        assert verdict.compounds == 0
        assert verdict.qualifies is False
        assert verdict.supplement_remarks == 0


class TestIdempotence:
    def test_re_posting_a_row_updates_it(self, online_engine, resolved_target):
        payload = [active_row("compound 7", SMALL_MOLECULE, 4.0, doi="10.1000/example")]
        first = import_supplements(online_engine, resolved_target.id, payload)
        second = import_supplements(online_engine, resolved_target.id, payload)

        assert first.measurements == 1 and first.updated == 0
        assert second.measurements == 1 and second.updated == 1
        assert second.compounds_created == 0 and second.compounds_reused == 1
        assert _count(online_engine, "measurements") == 1
        assert _count(online_engine, "target_candidates") == 1
        assert _count(online_engine, "compounds") == 1

    def test_a_corrected_value_replaces_the_earlier_one(self, online_engine, resolved_target):
        import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE, 4.0)]
        )
        import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE, 40.0)]
        )
        with online_engine.connect() as conn:
            values = conn.execute(text("SELECT value FROM measurements")).scalars().all()
        # A corrected potency is a new claim under the same row and the same document,
        # so both stored reports stay visible rather than one silently replacing the
        # other (AGENTS.md §9: contradictions are preserved).
        assert sorted(values) == [4.0, 40.0]

    def test_supplying_a_structure_supersedes_an_earlier_remark(
        self, online_engine, resolved_target
    ):
        remark = row(
            "example 12", note="IC50 3 nM; structure not published",
            activity_type="IC50", value=3.0, unit="nM",
        )
        import_supplements(online_engine, resolved_target.id, [remark])
        assert _count(online_engine, "target_supplement_remarks") == 1

        result = import_supplements(
            online_engine,
            resolved_target.id,
            [dict(remark, smiles=SMALL_MOLECULE)],
        )
        assert result.rows[0].status == "measurement"
        assert _count(online_engine, "target_supplement_remarks") == 0
        assert any("replaced" in reason for reason in result.rows[0].reasons)
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.supplement_remarks == 0


class TestExport:
    def test_the_export_states_user_curated_provenance(self, online_engine, resolved_target):
        result = import_supplements(
            online_engine, resolved_target.id, [active_row("compound 7", SMALL_MOLECULE, 4.0)]
        )
        app = _app(online_engine)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/export",
                json={
                    "target_id": str(resolved_target.id),
                    "compound_ids": [str(result.rows[0].compound_id)],
                    "format": "csv",
                },
            )
        assert response.status_code == 200, response.text
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert len(rows) == 1
        # A file must not present a person's row as a curated database fact.
        assert rows[0]["provenance_states"] == "user_curated"
        assert rows[0]["activity_class"] == "active"
        assert rows[0]["reference_policy_version"] == "potency-gate-v1"


class TestHttpContract:
    """The API answers per row, and refuses what it cannot accept."""

    @pytest.fixture()
    def target_id(self, online_engine) -> uuid.UUID:
        with TestClient(_app(online_engine)) as client:
            resolved = client.post(
                "/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"}
            )
            assert resolved.status_code == 200, resolved.text
            return uuid.UUID(resolved.json()["target_id"])

    def test_rows_are_answered_per_row(self, client, target_id):
        response = client.post(
            f"/api/v1/targets/{target_id}/supplements",
            json={
                "rows": [
                    active_row("compound 7", SMALL_MOLECULE, 4.0),
                    row("example 12", note="IC50 3 nM; structure not published",
                        activity_type="IC50", value=3.0, unit="nM"),
                    {"name": "no note"},
                ]
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["received"] == 3
        assert body["measurements"] == 1
        assert body["remarks"] == 1
        assert [r["status"] for r in body["rows"]] == ["measurement", "remark", "rejected"]
        assert body["rows"][0]["activity_class"] == "active"
        assert any("note" in reason for reason in body["rows"][2]["reasons"])

    def test_the_verdict_reports_the_remark(self, client, target_id):
        client.post(
            f"/api/v1/targets/{target_id}/supplements",
            json={
                "rows": [
                    row("example 12", note="IC50 3 nM; structure not published",
                        activity_type="IC50", value=3.0, unit="nM")
                ]
            },
        )
        verdict = client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert verdict["supplement_remarks"] == 1
        assert "literature remark" in verdict["reason"]

        remarks = client.get(f"/api/v1/targets/{target_id}/supplements/remarks").json()
        assert len(remarks) == 1
        assert remarks[0]["provenance_state"] == "user_curated"
        assert remarks[0]["value"] == 3.0
        assert remarks[0]["patent_number"] is None

    def test_a_batch_over_the_cap_is_refused(self, client, online_engine, target_id):
        rows = [
            active_row(f"compound {index}", SMALL_MOLECULE)
            for index in range(MAX_SUPPLEMENT_ROWS + 1)
        ]
        response = client.post(f"/api/v1/targets/{target_id}/supplements", json={"rows": rows})
        assert response.status_code == 422
        # The bound is a contract: the batch is refused, never silently truncated.
        assert _count(online_engine, "compounds") == 0

    def test_a_stored_row_is_readable_through_the_evidence_endpoint(self, client, target_id):
        response = client.post(
            f"/api/v1/targets/{target_id}/supplements",
            json={"rows": [active_row("compound 7", SMALL_MOLECULE, 4.0)]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["compounds_created"] == 1
        # A supplement is not a private side channel: it is readable through the
        # existing evidence endpoints, with its own source and note.
        measurements = client.get(f"/api/v1/targets/{target_id}/measurements").json()
        assert len(measurements) == 1
        assert measurements[0]["source_name"] == "user_supplement"
        assert measurements[0]["activity_class"] == "active"
        # The note is the row's provenance and is exposed as such, not as a source's
        # assay text.
        assert measurements[0]["note"] == "checked in the paper's Table 2"
        assert "added by hand" in measurements[0]["assay_description"]

    def test_an_unknown_target_is_a_404(self, client):
        response = client.post(
            f"/api/v1/targets/{uuid.uuid4()}/supplements",
            json={"rows": [active_row("compound 7", SMALL_MOLECULE)]},
        )
        assert response.status_code == 404


class TestTargetSummary:
    """The summary fact (prompt v8) carries hand-added rows as their own number.

    A thin retrieved set is exactly the case where someone adds a row by hand, so
    the summary that describes that set must not read as if nothing were recorded.
    """

    def test_the_snapshot_carries_the_remark_count(self, client, online_engine, resolved_target):
        client.post(
            f"/api/v1/targets/{resolved_target.id}/supplements",
            json={
                "rows": [
                    row("example 12", note="IC50 3 nM; structure not published",
                        activity_type="IC50", value=3.0, unit="nM")
                ]
            },
        )
        result = ai.summarize_target(online_engine, resolved_target.id)
        assert ai.TARGET_PROMPT_VERSION == "target-investigation-v8"
        assert result["input_snapshot"]["reference"]["supplement_remarks"] == 1
        # The offline provider states it in the same paragraph as the other counts,
        # and distinguishes a person's reading from a source's record.
        assert "added by hand" in result["text"]
        assert "not as compounds or measurements" in result["text"]
