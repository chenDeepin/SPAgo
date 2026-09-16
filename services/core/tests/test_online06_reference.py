"""ONLINE-06: the potency reference verdict and source-declared patents.

The scientific point: "2 compounds, none better than 10 µM" and "3 compounds,
best 4 nM" are different facts about a target, and the difference must come from
a stated rule rather than from a reader's eye. These tests drive the whole path
(record → persistence → stored rows → verdict) and pin:

- the censor and unit semantics end to end, through the database;
- that a sparse-and-weak set is reported as *not* usable, with the count that
  makes it so;
- that a class is never invented for a non-potency readout;
- that peptide actives are reported separately instead of being counted as a
  small-molecule reference;
- that a threshold change is an explicit policy, not a silent re-reading of
  stored values;
- that a patent number declared by a source is stored, matched and displayed
  separately from an occurrence in the loaded corpus.
"""
from __future__ import annotations

import csv
import io
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
from spago_core.chemistry.activities import ActivityClass
from spago_core.db import run_migrations
from spago_core.domain import EvidenceClass
from spago_core.main import create_app
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_candidates,
    list_target_measurements,
)
from spago_core.services.reference import (
    policy_from_settings,
    reference_verdict,
    reference_verdicts,
)
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import (
    StubActivityAdapter,
    StubSourceClient,
    load_fixture,
)

TSLP_ACCESSION = "Q969D9"
SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
OTHER_SMALL_MOLECULE = "CC(=O)Oc1ccccc1C(=O)O"
#: Real ChEMBL record for human TSLP: 9 residues, reported by the source as a
#: small molecule (see tests/test_online00_modality.py).
TSLP_PEPTIDE = (
    "CC(=O)N[C@@H](CCCNC(=N)N)C(=O)N[C@@H](C)C(=O)N[C@@H](C)C(=O)N"
    "[C@@H](Cc1cnc[nH]1)C(=O)N[C@@H](Cc1ccc(O)cc1)C(=O)NCC(=O)N"
    "[C@@H](CC(C)C)C(=O)N[C@@H](CCC(=O)O)C(=O)N[C@@H](C)C(=O)O"
)


class _Settings:
    """The two policy knobs, as `Settings` exposes them."""

    def __init__(self, threshold_nm: float = 10_000.0, min_compounds: int = 10) -> None:
        self.activity_threshold_nm = threshold_nm
        self.activity_min_compounds = min_compounds


def policy(threshold_nm: float = 10_000.0, min_compounds: int = 10, **kwargs):
    return policy_from_settings(
        _Settings(threshold_nm, min_compounds), **kwargs  # type: ignore[arg-type]
    )


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


def record(
    record_id: str,
    smiles: str,
    *,
    standard_type: str = "IC50",
    value: float = 4.0,
    unit: str = "nM",
    relation: str = "=",
    source_name: str = "chembl",
    document_ref: str | None = None,
    document_patent_number: str | None = None,
    document_doi: str | None = None,
    evidence_class: EvidenceClass = EvidenceClass.MEASURED_DIRECT_BINDING,
) -> ActivityRecord:
    return ActivityRecord(
        source_record_id=record_id,
        compound_source_id=smiles,
        target_key="CHEMBL_STUB",
        assay_key=f"STUB:ASSAY:{record_id}",
        assay_type="B",
        standard_type=standard_type,
        value=value,
        unit=unit,
        relation=relation,
        evidence_class=evidence_class,
        raw_value=str(value),
        document_ref=document_ref,
        document_patent_number=document_patent_number,
        document_doi=document_doi,
        raw_smiles=smiles,
        source_molecule_id=record_id,
        # A real record arrives already stamped by its adapter (ONLINE-06); the stub
        # stands in for the adapter, so the test states the source itself.
        source_name=source_name,
        source_dataset_version=f"{source_name}:2026-09-15",
    )


def investigate(engine, target, records, *, chembl=None):
    adapter = chembl or StubActivityAdapter(records)
    service = TargetDiscoveryService(
        chembl=adapter,
        bindingdb=StubActivityAdapter([]),
        pubchem=PubChemAdapter(client=StubSourceClient({})),
    )
    service.investigate(engine, target, sources=["chembl"])
    return adapter


class TestVerdictCounts:
    def test_sparse_and_weak_set_is_not_a_reference(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", SMALL_MOLECULE, value=43_000.0),
                record("r2", OTHER_SMALL_MOLECULE, value=51_000.0),
            ],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.qualifies is False
        assert verdict.compounds == 2
        assert verdict.compounds_weak == 2
        assert verdict.compounds_active == 0
        assert "sparse and weak" in verdict.reason
        assert "10 µM" in verdict.reason
        assert verdict.policy.threshold_label == "10 µM"
        assert verdict.policy.version == "potency-gate-v1"

    def test_one_compound_at_the_threshold_qualifies(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", SMALL_MOLECULE, value=43_000.0),
                record("r2", OTHER_SMALL_MOLECULE, value=4.0),
            ],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.qualifies is True
        assert verdict.compounds_active == 1
        assert verdict.compounds_weak == 1
        assert verdict.best_active is not None
        # The label is as reported, in the unit the source used.
        assert verdict.best_active.potency_label == "IC50 4 nM"
        assert "at or below 10 µM" in verdict.reason

    def test_censored_values_are_classified_by_direction(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", SMALL_MOLECULE, value=1000.0, relation="<"),
                record("r2", OTHER_SMALL_MOLECULE, value=10_000.0, relation=">"),
                record("r3", "CC(=O)Nc1ccc(O)cc1", value=1000.0, relation=">"),
            ],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds_active == 1          # "<1 µM" is below the threshold
        assert verdict.compounds_weak == 1            # ">10 µM" excludes it
        assert verdict.compounds_unknown == 1         # ">1 µM" cannot be decided
        assert verdict.qualifies is True

    def test_micromolar_units_are_converted_before_any_comparison(
        self, online_engine, resolved_target
    ):
        # 8 µM is a 10 µM-threshold active; a unit-blind comparison would not know.
        investigate(
            online_engine,
            resolved_target,
            [record("r1", SMALL_MOLECULE, value=8.0, unit="µM")],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.compounds_active == 1
        assert verdict.best_active is not None
        assert verdict.best_active.potency_label == "IC50 8 µM"

    def test_non_potency_readouts_are_not_classified(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", SMALL_MOLECULE, standard_type="kon", value=1e5, unit="1/s"),
                record("r2", OTHER_SMALL_MOLECULE, standard_type="Inhibition", value=90.0, unit="%"),
            ],
        )
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.qualifies is False
        assert verdict.compounds_not_applicable == 2
        assert verdict.compounds_active == 0
        assert "not potency measurements" in verdict.reason

    def test_no_measurement_is_reported_as_such(self, online_engine, resolved_target):
        investigate(online_engine, resolved_target, [])
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.qualifies is False
        assert verdict.compounds == 0
        assert verdict.reason == "No stored measurement for this target."


class TestPolicyIsExplicit:
    def test_the_threshold_is_the_policy_not_a_property_of_the_record(
        self, online_engine, resolved_target
    ):
        investigate(
            online_engine,
            resolved_target,
            [record("r1", SMALL_MOLECULE, value=50.0)],
        )
        strict = reference_verdict(online_engine, resolved_target, policy(threshold_nm=10.0))
        loose = reference_verdict(online_engine, resolved_target, policy(threshold_nm=100.0))
        assert strict.qualifies is False and strict.compounds_weak == 1
        assert loose.qualifies is True and loose.compounds_active == 1
        # The stored row did not change; only the stated rule did.
        stored = list_target_measurements(online_engine, resolved_target.id, limit=10)
        assert [m["value"] for m in stored] == [50.0]
        assert stored[0]["activity_class"] == "active"   # under the deployment default
        assert stored[0]["unit"] == "nM"

    def test_measurement_class_follows_the_requested_threshold(
        self, online_engine, resolved_target
    ):
        investigate(online_engine, resolved_target, [record("r1", SMALL_MOLECULE, value=50.0)])
        strict = list_target_measurements(
            online_engine, resolved_target.id, limit=10, threshold_nm=10.0
        )
        assert strict[0]["activity_class"] == "weak"
        assert strict[0]["activity_class_rule"] == "value_above_threshold"

    def test_min_compounds_shapes_the_reason_only(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [record("r1", SMALL_MOLECULE, value=4.0)],
        )
        verdict = reference_verdict(
            online_engine, resolved_target, policy(min_compounds=10_000)
        )
        # One potent compound still qualifies: the minimum is not a gate.
        assert verdict.qualifies is True
        assert "1 of 1 in-scope compound(s)" in verdict.reason


class TestModalityScope:
    def test_peptide_active_is_reported_but_outside_the_small_molecule_scope(
        self, online_engine, resolved_target
    ):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", TSLP_PEPTIDE, value=1.0),
                record("r2", SMALL_MOLECULE, value=43_000.0),
            ],
        )
        scoped = reference_verdict(online_engine, resolved_target, policy())
        assert scoped.qualifies is False
        assert scoped.compounds == 1                      # the small molecule
        assert scoped.active_compounds_outside_scope == 1  # the peptide, counted not hidden
        assert "outside the modality scope" in scoped.reason

        expanded = reference_verdict(
            online_engine, resolved_target, policy(include_all_modalities=True)
        )
        assert expanded.qualifies is True
        assert expanded.compounds == 2
        assert expanded.modality_counts.get("peptide") == 1

    def test_per_compound_class_is_reported_on_the_candidate_page(
        self, online_engine, resolved_target
    ):
        investigate(
            online_engine,
            resolved_target,
            [
                record("r1", SMALL_MOLECULE, value=4.0),
                record("r2", OTHER_SMALL_MOLECULE, value=43_000.0),
            ],
        )
        _total, items = list_candidates(
            online_engine, resolved_target.id, policy=policy()
        )
        by_smiles = {item.canonical_smiles: item for item in items}
        active = next(i for i in items if i.activity_class is ActivityClass.ACTIVE)
        weak = next(i for i in items if i.activity_class is ActivityClass.WEAK)
        assert active.potency_label == "IC50 4 nM"
        assert weak.potency_label == "IC50 43000 nM"
        assert active.sources == ["chembl"]
        assert len(by_smiles) == 2


class TestSourceDeclaredPatents:
    def test_patent_and_doi_are_stored_decomposed(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [
                record(
                    "r1",
                    SMALL_MOLECULE,
                    document_ref="CHEMBL3638439",
                    document_patent_number="US20130089624",
                    document_doi=None,
                ),
                record(
                    "r2",
                    OTHER_SMALL_MOLECULE,
                    document_ref="CHEMBL4043230",
                    document_doi="10.1016/j.bmcl.2017.09.010",
                ),
            ],
        )
        measurements = list_target_measurements(online_engine, resolved_target.id, limit=10)
        by_record = {m["source_record_id"]: m for m in measurements}
        assert by_record["r1"]["document_patent_number"] == "US20130089624"
        assert by_record["r1"]["document_doi"] is None
        assert by_record["r2"]["document_doi"] == "10.1016/j.bmcl.2017.09.010"
        assert by_record["r2"]["document_patent_number"] is None
        verdict = reference_verdict(online_engine, resolved_target, policy())
        assert verdict.source_declared_patents == ["US20130089624"]

    def test_source_declared_patent_is_not_a_corpus_occurrence(
        self, online_engine, resolved_target
    ):
        """The two are different facts and must stay distinguishable: a source
        can name a patent in its own formatting even when the loaded corpus has
        no compound occurrence for it."""
        investigate(
            online_engine,
            resolved_target,
            [
                record(
                    "r1",
                    SMALL_MOLECULE,
                    document_ref="CHEMBL3638439",
                    document_patent_number="US20130089624",
                )
            ],
        )
        _total, items = list_candidates(online_engine, resolved_target.id, policy=policy())
        item = items[0]
        assert item.source_declared_patents == ["US20130089624"]
        assert item.patent_occurrences == 0
        assert item.patent_labels == []

    def test_corpus_occurrence_is_reported_separately_from_the_source_claim(
        self, online_engine, resolved_target
    ):
        investigate(
            online_engine,
            resolved_target,
            [
                record(
                    "r1",
                    SMALL_MOLECULE,
                    document_ref="CHEMBL3638439",
                    document_patent_number="US20130089624",
                )
            ],
        )
        from spago_core.services.discovery import compound_id_for_inchikey
        from spago_core.chemistry import normalize

        inchikey = normalize(SMALL_MOLECULE).inchikey
        family_id = uuid.uuid4()
        document_id = uuid.uuid4()
        with online_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_families (id, family_key, title, source_name,
                                                 dataset_version, retrieved_at)
                    VALUES (:id, :key, 'stub family', 'stub', 'stub:2026-09-15', now())
                    """
                ),
                {"id": family_id, "key": f"STUB-{family_id.hex[:8]}"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, source_name,
                                                  dataset_version, retrieved_at)
                    VALUES (:id, :fid, 'US-20130089624-A1', 'stub', 'stub:2026-09-15', now())
                    """
                ),
                {"id": document_id, "fid": family_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO compound_mentions (id, compound_id, document_id, patent_label,
                                                   source_name, dataset_version, retrieved_at)
                    VALUES (:id, :cid, :did, 'Example 7', 'stub', 'stub:2026-09-15', now())
                    """
                ),
                {"id": uuid.uuid4(), "cid": compound_id_for_inchikey(inchikey), "did": document_id},
            )
        _total, items = list_candidates(online_engine, resolved_target.id, policy=policy())
        item = items[0]
        assert item.patent_occurrences == 1
        assert item.patent_labels == ["US-20130089624-A1 · Example 7"]
        assert item.source_declared_patents == ["US20130089624"]


class TestAdapterDocumentMetadata:
    def test_activities_carry_the_document_patent_and_identifiers(self):
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_Q969D9.json"),
                    "activity.json": load_fixture("chembl_activities_TSLP.json"),
                    "document.json": load_fixture("chembl_documents_TSLP.json"),
                }
            )
        )
        result = adapter.activities("CHEMBL3712931")
        by_document: dict[str, ActivityRecord] = {}
        for rec in result.records:
            by_document.setdefault(rec.document_ref or "", rec)
        # The recorded activities cite CHEMBL4043230 (a publication), not the
        # patent fixture document; the publication's DOI/PMID must be attached.
        publication = by_document["CHEMBL4043230"]
        assert publication.document_doi == "10.1016/j.bmcl.2017.09.010"
        assert publication.document_pmid == "28927768"
        assert publication.document_patent_number is None
        # The document was asked for once, batched, and only for the fields used.
        document_calls = [
            params for url, params in adapter.client.calls if "document.json" in url
        ]
        assert len(document_calls) == 1
        assert "document_chembl_id__in" in document_calls[0]
        assert "patent_id" in document_calls[0]["only"]

    def test_document_lookup_is_bounded_and_reported(self):
        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient({"document.json": load_fixture("chembl_documents_TSLP.json")}),
            max_document_lookups=1,
        )
        lookups = adapter.documents([f"CHEMBL_NOT_REAL_{n}" for n in range(120)])
        # Only the documents the source actually answered for are returned, the
        # request stayed inside the bound, and the gap is stated rather than
        # reported as "this activity has no patent".
        assert set(lookups.metadata) == {"CHEMBL3638439", "CHEMBL4043230"}
        assert any("configured bound" in w for w in lookups.warnings)
        assert len([1 for url, _ in adapter.client.calls if "document.json" in url]) == 1
        # B-02: every unresolved id carries its reason, so the retrieval can count
        # "the source answered and does not know it" (50 ids in the one batch that
        # was spent) separately from "the bound stopped us before asking" (the
        # remaining 70).
        assert len(lookups.unresolved) == 120
        reasons = list(lookups.unresolved.values())
        assert reasons.count("unknown_to_source") == 50
        assert reasons.count("bound") == 70

    def test_a_failed_document_lookup_is_not_reported_as_no_patent(self):
        from spago_core.adapters.http import SourceUnavailableError

        adapter = ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {"document.json": SourceUnavailableError("chembl", "HTTP 503")}
            )
        )
        lookups = adapter.documents(["CHEMBL4043230"])
        assert lookups.metadata == {}
        assert any("unavailable" in w for w in lookups.warnings)
        assert lookups.unresolved == {"CHEMBL4043230": "failure"}


class TestMatrixProjection:
    def test_verdicts_are_projected_per_target(self, online_engine, resolved_target):
        investigate(
            online_engine,
            resolved_target,
            [record("r1", SMALL_MOLECULE, value=4.0)],
        )
        verdicts = reference_verdicts(online_engine, [resolved_target], policy())
        verdict = verdicts[resolved_target.id]
        assert verdict.qualifies is True
        assert verdict.policy.version == "potency-gate-v1"


# --- HTTP contract -----------------------------------------------------------


def _uniprot_route(call):
    """Answer the UniProt search for the TSLP fixture only (ONLINE-00 pattern)."""
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


def _app(online_engine, discovery: TargetDiscoveryService):
    app = create_app()
    app.state.engine = online_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    app.state.discovery_service = discovery
    return app


@pytest.fixture()
def recorded_client(online_engine):
    """The app with the *recorded* ChEMBL/BindingDB payloads, so the HTTP
    contract is exercised against real source shapes (including the document
    lookup that supplies DOI/PMID)."""
    return TestClient(
        _app(
            online_engine,
            TargetDiscoveryService(
                chembl=ChEMBLDiscoveryAdapter(
                    client=StubSourceClient(
                        {
                            "target.json": load_fixture("chembl_targets_Q969D9.json"),
                            "activity.json": load_fixture("chembl_activities_TSLP.json"),
                            "document.json": load_fixture("chembl_documents_TSLP.json"),
                        }
                    )
                ),
                bindingdb=BindingDBRestAdapter(
                    client=StubSourceClient(
                        {"getLigandsByUniprot": load_fixture("bindingdb_P05231.json")}
                    )
                ),
                pubchem=PubChemAdapter(
                    client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
                ),
            ),
        )
    )


@pytest.fixture()
def recorded_investigation(recorded_client) -> dict:
    resolved = recorded_client.post(
        "/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"}
    )
    assert resolved.status_code == 200, resolved.text
    target_id = resolved.json()["target_id"]
    discovered = recorded_client.post("/api/v1/targets/discover", json={"target_id": target_id})
    assert discovered.status_code == 200, discovered.text
    return {"target_id": target_id, **discovered.json()}


class TestReferenceApi:
    """The HTTP contract, driven by the *recorded* ChEMBL/BindingDB payloads.

    The recorded TSLP retrieval holds three small-molecule compounds (two
    BindingDB IC50s at 1.1 nM and 83 nM, one ChEMBL percent-inhibition readout)
    and two peptides (a Kd at 230 nM and a percent readout), so it exercises the
    in-scope/out-of-scope split with real source shapes.
    """

    def test_discovery_returns_the_verdict_under_the_deployment_policy(
        self, recorded_investigation
    ):
        reference = recorded_investigation["reference"]
        assert reference is not None
        assert reference["policy"]["version"] == "potency-gate-v1"
        assert reference["policy"]["threshold_nm"] == 10_000.0
        assert reference["policy"]["threshold_label"] == "10 µM"
        assert reference["policy"]["all_modalities"] is False
        assert reference["compounds"] == 3
        assert reference["compounds_active"] == 2
        assert reference["compounds_not_applicable"] == 1
        assert reference["measurements"] == 3
        assert reference["class_counts"] == {"active": 2, "not_applicable": 1}
        assert reference["endpoint_counts"] == {"IC50": 2}
        assert reference["modality_counts"] == {"small_molecule": 3}
        # A potency outside the modality scope is reported, never counted as an
        # in-scope reference: the peptide's Kd at 230 nM is that fact.
        assert reference["active_compounds_outside_scope"] == 1
        assert reference["qualifies"] is True
        assert reference["reason"].startswith("2 of 3 in-scope compound(s) at or below 10 µM")
        assert reference["best_active"]["potency_label"] == "IC50 1.1 nM"
        assert reference["best_active"]["source_name"] == "bindingdb"

    def test_the_reference_route_recomputes_from_stored_rows(
        self, recorded_client, recorded_investigation
    ):
        target_id = recorded_investigation["target_id"]
        response = recorded_client.get(f"/api/v1/targets/{target_id}/reference")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["target_key"] == "TSLP"
        assert body["policy"]["version"] == "potency-gate-v1"
        # The route reads the stored rows, so it agrees with the discovery
        # response without a second rule being applied anywhere.
        assert body["compounds"] == recorded_investigation["reference"]["compounds"]
        assert body["compounds_active"] == 2

        # The labelled expansion counts every modality: the peptide Kd becomes an
        # in-scope active — same stored rows, a different stated scope.
        expanded = recorded_client.get(
            f"/api/v1/targets/{target_id}/reference",
            params={"include_all_modalities": True},
        ).json()
        assert expanded["policy"]["all_modalities"] is True
        assert expanded["compounds"] == 5
        assert expanded["compounds_active"] == 3
        assert expanded["modality_counts"] == {"peptide": 2, "small_molecule": 3}
        assert expanded["qualifies"] is True
        assert expanded["reason"].startswith("3 of 5 in-scope compound(s) at or below 10 µM")

    def test_an_unusable_threshold_is_refused(self, recorded_client, recorded_investigation):
        target_id = recorded_investigation["target_id"]
        for value in ("0", "-1", "1e10", "not-a-number"):
            response = recorded_client.get(
                f"/api/v1/targets/{target_id}/reference",
                params={"activity_threshold_nm": value},
            )
            assert response.status_code == 422, value

    def test_measurements_carry_the_class_and_the_decomposed_reference(
        self, recorded_client, recorded_investigation
    ):
        target_id = recorded_investigation["target_id"]
        rows = recorded_client.get(
            f"/api/v1/targets/{target_id}/measurements", params={"limit": 50}
        ).json()
        by_value = {(row["standard_type"], row["value"]): row for row in rows}
        # A potency endpoint is classed; a percent readout is explicitly not.
        assert by_value[("Kd", 230.0)]["activity_class"] == "active"
        assert (
            by_value[("Kd", 230.0)]["activity_class_rule"] == "value_at_or_below_threshold"
        )
        assert by_value[("Inhibition", 34.0)]["activity_class"] == "not_applicable"
        assert (
            by_value[("Inhibition", 34.0)]["activity_class_rule"] == "endpoint_not_a_potency"
        )
        # ChEMBL's activity payload carries no DOI/PMID; the bounded document
        # lookup supplies them for the document that has them.
        assert by_value[("Inhibition", 34.0)]["document_doi"] == "10.1016/j.bmcl.2017.09.010"
        assert by_value[("Inhibition", 34.0)]["document_pmid"] == "28927768"
        # The Kd record belongs to a patent-free document, so nothing is invented.
        assert by_value[("Kd", 230.0)]["document_doi"] is None
        assert by_value[("Kd", 230.0)]["document_patent_number"] is None
        # The source is the one that reported the value, not the resolver.
        assert by_value[("Kd", 230.0)]["source_name"] == "chembl"
        assert by_value[("IC50", 1.1)]["source_name"] == "bindingdb"

        # A request-level threshold is applied to the returned classes: 230 nM is
        # above a 100 nM threshold and becomes weak, while 83 nM stays active.
        strict = recorded_client.get(
            f"/api/v1/targets/{target_id}/measurements",
            params={"limit": 50, "activity_threshold_nm": 100},
        ).json()
        classes = {(row["standard_type"], row["value"]): row["activity_class"] for row in strict}
        assert classes[("Kd", 230.0)] == "weak"
        assert classes[("IC50", 83.0)] == "active"
        assert classes[("IC50", 1.1)] == "active"
        assert classes[("Inhibition", 77.5)] == "not_applicable"

    def test_candidate_page_states_the_policy_it_classified_under(
        self, recorded_client, recorded_investigation
    ):
        target_id = recorded_investigation["target_id"]
        page = recorded_client.get(
            f"/api/v1/targets/{target_id}/candidates",
            params={"include_all_modalities": True},
        ).json()
        assert page["policy"]["threshold_label"] == "10 µM"
        assert page["policy"]["version"] == "potency-gate-v1"
        # The recorded set holds two peptides: the one with a Kd is active, the
        # one with only a percent readout is explicitly not a potency. Same
        # modality, different class — the class follows the report.
        peptide_actives = [
            row for row in page["items"] if row["modality"] == "peptide" and row["activity_class"] == "active"
        ]
        assert len(peptide_actives) == 1
        peptide = peptide_actives[0]
        # The label is the source's own endpoint string, uppercased, in the
        # reported unit — never a converted or re-ranked value.
        assert peptide["potency_label"] == "KD 230 nM"
        assert peptide["sources"] == ["chembl"]
        peptide_readout = next(
            row
            for row in page["items"]
            if row["modality"] == "peptide" and row["activity_class"] == "not_applicable"
        )
        assert "INHIBITION" in peptide_readout["potency_label"]
        # The compound's own class is not filtered by the set's modality scope:
        # the peptide's class is what its own evidence supports.
        small = next(row for row in page["items"] if row["source_name"] == "bindingdb")
        assert small["activity_class"] == "active"
        assert small["sources"] == ["bindingdb"]
        assert small["source_declared_patents"] == []

    def test_coverage_matrix_repeats_the_verdict_next_to_each_retrieval(
        self, recorded_client, recorded_investigation
    ):
        rows = recorded_client.get("/api/v1/targets/coverage/matrix").json()
        target_rows = [
            row for row in rows if row["target_id"] == recorded_investigation["target_id"]
        ]
        assert target_rows
        for row in target_rows:
            # Each retrieval row carries the same target verdict, so a coverage
            # report can separate "retrieved nothing" from "no compound at or
            # below the threshold".
            assert row["reference_qualifies"] is True
            assert row["reference_n_active"] == 2
            assert row["reference_threshold_nm"] == 10_000.0
            assert row["reference_policy_version"] == "potency-gate-v1"
            assert row["reference_reason"]
        assert {row["source_name"] for row in target_rows} >= {"chembl", "bindingdb"}


class TestReferenceApiWithStatedPolicy:
    """Threshold change, export policy and source-declared patents, driven by
    explicit records so the values under test are stated, not inferred."""

    @pytest.fixture()
    def stated_client(self, online_engine):
        records = [
            record(
                "r1",
                SMALL_MOLECULE,
                value=50.0,
                document_ref="CHEMBL3638439",
                document_patent_number="US20130089624",
            ),
            record("r2", OTHER_SMALL_MOLECULE, value=43_000.0),
        ]
        return TestClient(
            _app(
                online_engine,
                TargetDiscoveryService(
                    chembl=StubActivityAdapter(records),
                    bindingdb=StubActivityAdapter([]),
                    pubchem=PubChemAdapter(client=StubSourceClient({})),
                ),
            )
        )

    @pytest.fixture()
    def stated_investigation(self, stated_client) -> dict:
        resolved = stated_client.post(
            "/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"}
        )
        assert resolved.status_code == 200, resolved.text
        target_id = resolved.json()["target_id"]
        discovered = stated_client.post("/api/v1/targets/discover", json={"target_id": target_id})
        assert discovered.status_code == 200, discovered.text
        return {"target_id": target_id, **discovered.json()}

    def test_a_stricter_threshold_flips_the_class_and_the_verdict(
        self, stated_client, stated_investigation
    ):
        target_id = stated_investigation["target_id"]
        default = stated_client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert default["qualifies"] is True
        assert default["compounds_active"] == 1

        strict = stated_client.get(
            f"/api/v1/targets/{target_id}/reference",
            params={"activity_threshold_nm": 10},
        ).json()
        assert strict["qualifies"] is False
        assert strict["compounds_active"] == 0
        assert strict["compounds_weak"] == 2
        assert strict["policy"]["threshold_label"] == "10 nM"
        assert "10 nM" in strict["reason"]

        # The stored row is unchanged: the class is a property of the stated
        # policy, so the default read still reports the default class.
        again = stated_client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert again["compounds_active"] == 1

    def test_candidate_rows_expose_the_source_declared_patent_separately(
        self, stated_client, stated_investigation
    ):
        target_id = stated_investigation["target_id"]
        page = stated_client.get(f"/api/v1/targets/{target_id}/candidates").json()
        active = next(row for row in page["items"] if row["activity_class"] == "active")
        assert active["source_declared_patents"] == ["US20130089624"]
        # No corpus occurrence was loaded for it: the two facts stay distinct.
        assert active["patent_occurrences"] == 0

    def test_export_uses_the_requested_policy_and_records_it(
        self, stated_client, stated_investigation
    ):
        target_id = stated_investigation["target_id"]
        page = stated_client.get(f"/api/v1/targets/{target_id}/candidates").json()
        compound_id = next(
            row["compound_id"] for row in page["items"] if row["activity_class"] == "active"
        )
        response = stated_client.post(
            "/api/v1/export",
            json={
                "target_id": target_id,
                "compound_ids": [compound_id],
                "activity_threshold_nm": 10,
                "format": "csv",
            },
        )
        assert response.status_code == 200, response.text
        fields = next(csv.DictReader(io.StringIO(response.text)))
        assert fields["activity_class"] == "weak"
        assert fields["reference_qualifies"] == "false"
        assert fields["reference_threshold_nM"] == "10"
        assert fields["reference_policy_version"] == "potency-gate-v1"
        assert fields["source_declared_patents"] == "US20130089624"

    def test_measurements_carry_the_source_declared_patent(
        self, stated_client, stated_investigation
    ):
        target_id = stated_investigation["target_id"]
        rows = stated_client.get(
            f"/api/v1/targets/{target_id}/measurements", params={"limit": 50}
        ).json()
        patents = {row["document_patent_number"] for row in rows}
        assert "US20130089624" in patents
        # The measurement names the source that reported it, not the resolver.
        assert {row["source_name"] for row in rows} == {"chembl"}
