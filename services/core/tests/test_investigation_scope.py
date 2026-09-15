"""Defect round 2026-09-16: what counts as *this* investigation's evidence.

Three defects share one theme — a row that exists is not the same fact as a row
that still holds, and a row of *another* investigation is not this one's:

- **D1 scope.** A target's retrieval must not inherit a measurement of the same
  compound against an unrelated target (a cyclooxygenase IC50 counted in a TSLP
  verdict, say), while a measurement retrieved *through* an interaction/complex
  record of the same protein stays in scope and stays labelled with its object.
- **D2 filter.** A saved or deep-linked compound that the active filter excludes
  must come back as a labelled row, not as a silently widened filter.
- **D3 withdrawal.** A hand-added row the user owns can be taken back; the row is
  retracted, counted and reported, never deleted, and re-posting it makes it
  current again.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bioactivity_base import ActivityRecord
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.chemistry.activities import DEFAULT_THRESHOLD_NM
from spago_core.db import run_migrations
from spago_core.domain import EvidenceClass
from spago_core.main import create_app
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_candidates,
    list_target_measurements,
)
from spago_core.services.export import collect_candidate_export_rows
from spago_core.services.reference import policy_from_settings, reference_verdict
from spago_core.services.supplements import import_supplements, withdraw_supplement
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubActivityAdapter, StubSourceClient, load_fixture

SMALL_MOLECULE = "Cc1ccc(S(=O)(=O)Nc2ccc(C(=O)O)cc2)cc1"
#: A hexaglycine: five amide bonds, so the deterministic classifier reads the
#: backbone and the default small-molecule filter excludes the compound
#: (`PEPTIDE_AMIDE_MIN = 5`, `spago_core/chemistry/modality.py`).
PEPTIDE = "NCC(=O)NCC(=O)NCC(=O)NCC(=O)NCC(=O)NCC(=O)O"


class _Settings:
    def __init__(self, threshold_nm: float = DEFAULT_THRESHOLD_NM, min_compounds: int = 10):
        self.activity_threshold_nm = threshold_nm
        self.activity_min_compounds = min_compounds


def policy(**kwargs):
    return policy_from_settings(_Settings(), **kwargs)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def online_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_tables(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_payload(accession: str, gene: str, protein: str) -> dict:
    payload = json.loads(json.dumps(load_fixture("uniprot_TSLP_human.json")))
    hit = payload["results"][0]
    hit["primaryAccession"] = accession
    hit["uniProtkbId"] = f"{gene}_HUMAN"
    hit["proteinDescription"]["recommendedName"]["fullName"]["value"] = protein
    for entry in hit.get("genes", []):
        entry["geneName"]["value"] = gene
    return payload


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    if "CD40LG" in query or "P29965" in query:
        return _uniprot_payload("P29965", "CD40LG", "CD40 ligand")
    return {"results": [], "totalResults": 0}


def _resolver() -> UniProtTargetResolver:
    return UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))


def resolve(engine, query: str):
    outcome = TargetResolutionService(uniprot=_resolver()).resolve(engine, query, "human")
    assert outcome.target is not None, outcome.notes
    return outcome.target


def record(record_id: str, smiles: str, value: float, **overrides) -> ActivityRecord:
    payload = dict(
        source_record_id=record_id,
        compound_source_id=smiles,
        target_key="CHEMBL_STUB",
        assay_key=f"STUB:ASSAY:{record_id}",
        assay_type="B",
        standard_type="IC50",
        value=value,
        unit="nM",
        relation="=",
        evidence_class=EvidenceClass.MEASURED_DIRECT_BINDING,
        raw_value=str(value),
        raw_smiles=smiles,
        source_molecule_id=record_id,
        source_name="chembl",
        source_dataset_version="chembl:2026-09-16",
    )
    payload.update(overrides)
    return ActivityRecord(**payload)


def investigate(engine, target, records):
    service = TargetDiscoveryService(
        chembl=StubActivityAdapter(records),
        bindingdb=StubActivityAdapter([]),
        pubchem=PubChemAdapter(client=StubSourceClient({})),
    )
    service.investigate(engine, target, sources=["chembl"])
    return service


def app_client(engine) -> TestClient:
    app = create_app()
    app.state.engine = engine
    app.state.target_service = TargetResolutionService(uniprot=_resolver())
    return TestClient(app)


class TestScope:
    def test_another_investigations_measurement_is_not_this_targets_evidence(self, online_engine):
        """D1: the same compound measured against an unrelated target stays out.

        Reproduces the live finding: a TSLP strip reported `IC50 4100 nM` whose
        drawer row read `Demo cyclooxygenase (synthetic)` — a different object's
        number counted as this protein's potency, in the verdict and the export.
        """
        tslp = resolve(online_engine, "TSLP")
        cd40l = resolve(online_engine, "CD40LG")
        investigate(online_engine, tslp, [record("tslp:1", SMALL_MOLECULE, 5.0)])
        investigate(online_engine, cd40l, [record("cd40l:1", SMALL_MOLECULE, 4100.0)])

        verdict = reference_verdict(online_engine, tslp, policy())
        assert verdict.measurements == 1
        assert verdict.compounds == 1
        assert verdict.best_active is not None and verdict.best_active.value == 5.0

        rows = list_target_measurements(online_engine, tslp.id, limit=50)
        assert {r["source_record_id"] for r in rows} == {"tslp:1"}

        # The other investigation keeps its own number: this is scoping, not loss.
        other = reference_verdict(online_engine, cd40l, policy())
        assert other.measurements == 1
        assert other.best_active is not None and other.best_active.value == 4100.0

        # D1 was visible in the file a user takes away, so it is pinned there too.
        exported = collect_candidate_export_rows(online_engine, tslp.id, policy=policy())
        assert len(exported) == 1
        assert exported[0].potency_label == "IC50 5 nM"

    def test_a_measurement_retrieved_through_an_interaction_record_stays_in_scope(
        self, online_engine
    ):
        """The other half of the rule: what the retrieval *did* bring back counts.

        A protein–protein interaction record is a different scientific object, so
        its target row and its label are kept — but the measurement belongs to the
        investigation that asked for it (migration 0015).
        """
        tslp = resolve(online_engine, "TSLP")
        investigate(
            online_engine,
            tslp,
            [
                record(
                    "tslp:complex:1",
                    SMALL_MOLECULE,
                    12.0,
                    target_key="CHEMBL_COMPLEX_9",
                    target_name="TSLP–TSLPR complex",
                    target_type_declared="PROTEIN COMPLEX",
                )
            ],
        )
        verdict = reference_verdict(online_engine, tslp, policy())
        assert verdict.measurements == 1
        assert verdict.best_active is not None and verdict.best_active.value == 12.0

        with online_engine.connect() as conn:
            related = conn.execute(
                text(
                    """
                    SELECT t.target_key, r.relation, r.note
                      FROM target_relations r JOIN targets t ON t.id = r.related_target_id
                     WHERE r.target_id = :tid
                    """
                ),
                {"tid": tslp.id},
            ).mappings().all()
        assert [r["target_key"] for r in related] == ["CHEMBL_COMPLEX_9"]
        assert related[0]["relation"] == "interaction_record_of"
        assert "interaction/complex record" in related[0]["note"]

        # The row is stored against the complex, so the drawer can label it as such.
        rows = list_target_measurements(online_engine, tslp.id, limit=50)
        assert len(rows) == 1
        assert rows[0]["target_key"] == "CHEMBL_COMPLEX_9"

    def test_the_scope_views_expose_every_measurement_column(self, online_engine):
        """A new column must not silently vanish behind the views.

        `investigation_measurements` and `current_measurements` select `m.*`, so a
        column added to `measurements` in a later migration is invisible through
        them until the view is recreated. This fails on purpose when that happens
        (migration 0015's note for later migrations).
        """
        with online_engine.connect() as conn:
            def columns(table: str) -> set[str]:
                return {
                    r[0]
                    for r in conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :t"
                        ),
                        {"t": table},
                    )
                }

            base = columns("measurements")
            assert base
            for view in ("investigation_measurements", "current_measurements"):
                missing = base - columns(view)
                assert not missing, f"{view} does not expose: {sorted(missing)}"


class TestPinnedCompound:
    """D2: a filter is a control, not something that moves by itself."""

    @pytest.fixture()
    def peptide_target(self, online_engine):
        target = resolve(online_engine, "TSLP")
        investigate(online_engine, target, [record("peptide:1", PEPTIDE, 2.0)])
        _total, items = list_candidates(online_engine, target.id, include_all_modalities=True)
        peptide = next(i for i in items if i.modality.value == "peptide")
        return target, peptide

    def test_a_compound_outside_the_filter_comes_back_labelled(self, online_engine, peptide_target):
        target, peptide = peptide_target
        total, items = list_candidates(online_engine, target.id)
        assert items == [] and total == 0, "the default filter excludes the peptide"

        total, items = list_candidates(
            online_engine, target.id, pin_compound_id=peptide.compound_id
        )
        assert total == 0, "the pinned row is not part of the filtered set"
        assert [i.compound_id for i in items] == [peptide.compound_id]
        assert items[0].outside_filter is True

    def test_every_saved_item_of_a_reopened_project_stays_visible(self, online_engine):
        """A project can hold several items; each one has to come back visible.

        The walkthrough that found D2 saved a small molecule and later a peptide
        into one project. Reopening it with the small-molecule scope must show the
        peptide as a labelled outsider rather than dropping a saved item.
        """
        target = resolve(online_engine, "TSLP")
        investigate(
            online_engine,
            target,
            [record("small:1", SMALL_MOLECULE, 5.0), record("peptide:1", PEPTIDE, 2.0)],
        )
        _total, all_items = list_candidates(online_engine, target.id, include_all_modalities=True)
        small = next(i for i in all_items if i.modality.value == "small_molecule")
        peptide = next(i for i in all_items if i.modality.value == "peptide")

        total, items = list_candidates(online_engine, target.id)
        assert total == 1 and [i.outside_filter for i in items] == [False]

        total, items = list_candidates(
            online_engine, target.id, pin_compound_ids=[small.compound_id, peptide.compound_id]
        )
        assert total == 1, "pinning never changes the filtered total"
        by_id = {i.compound_id: i for i in items}
        assert set(by_id) == {small.compound_id, peptide.compound_id}
        assert by_id[small.compound_id].outside_filter is False
        assert by_id[peptide.compound_id].outside_filter is True

        # The HTTP contract takes the parameter once per saved compound.
        client = app_client(online_engine)
        response = client.get(
            f"/api/v1/targets/{target.id}/candidates",
            params=[
                ("include_compound_id", str(small.compound_id)),
                ("include_compound_id", str(peptide.compound_id)),
            ],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        labelled = {i["compound_id"]: i["outside_filter"] for i in body["items"]}
        assert labelled == {
            str(small.compound_id): False,
            str(peptide.compound_id): True,
        }

    def test_a_compound_inside_the_filter_is_not_marked_or_duplicated(self, online_engine):
        target = resolve(online_engine, "TSLP")
        investigate(online_engine, target, [record("small:1", SMALL_MOLECULE, 5.0)])
        _total, items = list_candidates(online_engine, target.id)
        compound = items[0]

        total, pinned = list_candidates(online_engine, target.id, pin_compound_id=compound.compound_id)
        assert total == 1
        assert [i.compound_id for i in pinned] == [compound.compound_id]
        assert pinned[0].outside_filter is False

    def test_the_http_contract_carries_the_label(self, online_engine, peptide_target):
        target, peptide = peptide_target
        client = app_client(online_engine)
        plain = client.get(f"/api/v1/targets/{target.id}/candidates")
        assert plain.status_code == 200
        assert plain.json()["items"] == []

        pinned = client.get(
            f"/api/v1/targets/{target.id}/candidates",
            params={"include_compound_id": str(peptide.compound_id)},
        )
        assert pinned.status_code == 200
        body = pinned.json()
        assert body["total"] == 0
        assert [i["compound_id"] for i in body["items"]] == [str(peptide.compound_id)]
        assert body["items"][0]["outside_filter"] is True


class TestWithdrawal:
    """D3: the user owns a hand-added row and can take it back."""

    def _add(self, engine, target, value: float = 4.0) -> str:
        result = import_supplements(
            engine,
            target.id,
            [
                {
                    "name": "compound 7",
                    "note": "placeholder typed to exercise the withdrawal path",
                    "smiles": SMALL_MOLECULE,
                    "activity_type": "IC50",
                    "value": value,
                    "unit": "nM",
                }
            ],
        )
        assert result.measurements == 1, result.rows
        return result.rows[0].record_id

    def test_a_withdrawn_row_stops_counting_and_says_why(self, online_engine):
        target = resolve(online_engine, "TSLP")
        record_id = self._add(online_engine, target)
        assert reference_verdict(online_engine, target, policy()).measurements == 1

        outcome = withdraw_supplement(
            online_engine, target.id, record_id, "typed by mistake during acceptance"
        )
        assert outcome.kind == "measurement"
        assert outcome.candidate_retracted is True

        verdict = reference_verdict(online_engine, target, policy())
        assert verdict.measurements == 0
        assert verdict.compounds == 0
        assert verdict.withdrawn_supplements == 1
        assert "withdrawn by the user" in verdict.reason
        assert "typed by mistake during acceptance" not in verdict.reason, (
            "the reason is stored, not shouted into the verdict sentence"
        )

        # The candidate row is retracted, so the compound leaves this investigation.
        total, items = list_candidates(online_engine, target.id)
        assert total == 0 and items == []
        # ... while the row itself, its note and its reason stay readable: the
        # withdrawn list is the audit trail behind the verdict's count.
        client = app_client(online_engine)
        withdrawn = client.get(f"/api/v1/targets/{target.id}/supplements/withdrawn")
        assert withdrawn.status_code == 200
        rows = withdrawn.json()
        assert [r["kind"] for r in rows] == ["measurement"]
        assert rows[0]["record_id"] == record_id
        assert rows[0]["retracted_reason"] == "typed by mistake during acceptance"
        assert rows[0]["candidate_retracted"] is True
        assert "withdrawal path" in rows[0]["note"]

    def test_a_row_that_returns_is_current_again(self, online_engine):
        target = resolve(online_engine, "TSLP")
        record_id = self._add(online_engine, target)
        withdraw_supplement(online_engine, target.id, record_id, "taken back for now")
        assert reference_verdict(online_engine, target, policy()).withdrawn_supplements == 1

        again = import_supplements(
            online_engine,
            target.id,
            [
                {
                    "name": "compound 7",
                    "note": "re-entered after the note was checked",
                    "smiles": SMALL_MOLECULE,
                    "activity_type": "IC50",
                    "value": 4.0,
                    "unit": "nM",
                }
            ],
        )
        assert again.rows[0].record_id == record_id, "identity, not a second claim"
        verdict = reference_verdict(online_engine, target, policy())
        assert verdict.measurements == 1
        assert verdict.withdrawn_supplements == 0

    def test_the_api_requires_a_reason_and_reports_the_state(self, online_engine):
        target = resolve(online_engine, "TSLP")
        record_id = self._add(online_engine, target)
        client = app_client(online_engine)

        refused = client.post(
            f"/api/v1/targets/{target.id}/supplements/{record_id}/withdraw",
            json={"reason": ""},
        )
        assert refused.status_code == 422

        accepted = client.post(
            f"/api/v1/targets/{target.id}/supplements/{record_id}/withdraw",
            json={"reason": "superseded by the paper's corrected table"},
        )
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["status"] == "withdrawn" and body["candidate_retracted"] is True

        withdrawn = client.get(f"/api/v1/targets/{target.id}/supplements/withdrawn")
        assert withdrawn.status_code == 200
        rows = withdrawn.json()
        assert [r["kind"] for r in rows] == ["measurement"]
        assert rows[0]["retracted_reason"] == "superseded by the paper's corrected table"

        reference = client.get(f"/api/v1/targets/{target.id}/reference")
        assert reference.status_code == 200
        payload = reference.json()
        assert payload["measurements"] == 0
        assert payload["withdrawn_supplements"] == 1
