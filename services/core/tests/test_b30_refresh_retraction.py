"""B-30: a complete source refresh retracts what its release no longer contains.

The rule under test, in one sentence: an ask that answered the whole question
(`complete`, or `empty`) retracts — never deletes — the candidate rows of the
same target, source and *access path* it did not re-deliver, records the
retrieval that withdrew them, and lets re-delivery restore them. A `failed` or
bound-limited `partial` ask establishes no absence, rows of another access path
are not SPAgo's to retract, and rows with no recorded access path are never
retracted (an unknown origin must not become an inferred absence).
"""
from __future__ import annotations

import copy
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.db import run_migrations
from spago_core.main import create_app
from spago_core.services.discovery import TargetDiscoveryService
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture


@pytest.fixture(scope="module")
def b30_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_tables(b30_engine):
    with b30_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


def _chembl_payload(keep: int) -> dict:
    """The TSLP fixture sliced to `keep` activities, with page_meta consistent
    so the adapter does not try to fetch the pages that were removed."""
    payload = copy.deepcopy(load_fixture("chembl_activities_TSLP.json"))
    payload["activities"] = payload["activities"][:keep]
    payload["page_meta"]["total_count"] = keep
    return payload


def _chembl_payload_records(record_ids: list[str]) -> dict:
    """The fixture reduced to exactly the activities that produced the given
    candidate rows — the refreshed release still returns those records and no
    others. (Not every activity produces a candidate row: one fixture record
    yields no normalizable structure, so slicing by position is not reliable.)"""
    payload = copy.deepcopy(load_fixture("chembl_activities_TSLP.json"))
    payload["activities"] = [
        a for a in payload["activities"] if str(a["activity_id"]) in set(record_ids)
    ]
    payload["page_meta"]["total_count"] = len(payload["activities"])
    return payload


class _ChemblSequencer:
    """Serve one payload per call so a test scripts two different releases."""

    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)

    def __call__(self, call):
        return self.payloads.pop(0) if self.payloads else self.payloads[-1]


def _client(b30_engine, chembl_route) -> TestClient:
    app = create_app()
    app.state.engine = b30_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(
            client=StubSourceClient({"uniprotkb/search": _uniprot_route})
        )
    )
    app.state.discovery_service = TargetDiscoveryService(
        chembl=ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_Q969D9.json"),
                    "activity.json": chembl_route,
                }
            )
        ),
        bindingdb=BindingDBRestAdapter(
            client=StubSourceClient({"getLigandsByUniprot": load_fixture("bindingdb_P05231.json")})
        ),
        pubchem=PubChemAdapter(
            client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
        ),
    )
    return TestClient(app)


def _resolve(client) -> str:
    resolved = client.post("/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"})
    assert resolved.status_code == 200, resolved.text
    return resolved.json()["target_id"]


def _discover(client, target_id: str, sources=("chembl", "bindingdb", "pubchem")):
    response = client.post(
        "/api/v1/targets/discover", json={"target_id": target_id, "sources": list(sources)}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _chembl_candidate_rows(b30_engine, target_id: str):
    with b30_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT source_record_id, retracted_at, retracted_reason, source_version "
                "FROM target_candidates WHERE target_id = :tid AND source_name = 'chembl' "
                "ORDER BY source_record_id"
            ),
            {"tid": target_id},
        ).mappings().all()


class TestCompleteReask:
    def test_dropped_records_are_retracted_not_deleted(self, b30_engine):
        seq = _ChemblSequencer([_chembl_payload(4)])
        client = _client(b30_engine, seq)
        target_id = _resolve(client)
        _discover(client, target_id)
        rows1 = _chembl_candidate_rows(b30_engine, target_id)
        assert len(rows1) >= 2

        # The refreshed release returns only one of the stored records.
        seq.payloads.insert(0, _chembl_payload_records([rows1[0]["source_record_id"]]))
        run2 = _discover(client, target_id)
        chembl2 = next(r for r in run2["sources"] if r["source_name"] == "chembl")
        rows2 = _chembl_candidate_rows(b30_engine, target_id)
        live2 = [r for r in rows2 if r["retracted_at"] is None]
        retracted2 = [r for r in rows2 if r["retracted_at"] is not None]

        assert chembl2["retracted_candidates"] == len(rows1) - 1
        assert [r["source_record_id"] for r in live2] == [rows1[0]["source_record_id"]]
        assert len(retracted2) == len(rows1) - 1
        for row in retracted2:
            assert row["retracted_reason"]
            assert "chembl-web-services" in row["retracted_reason"]
            # Retracted, never deleted: the history stays queryable.
            assert row["retracted_at"] is not None

    def test_redelivery_clears_the_retraction(self, b30_engine):
        seq = _ChemblSequencer([_chembl_payload(4)])
        client = _client(b30_engine, seq)
        target_id = _resolve(client)
        _discover(client, target_id)
        rows1 = _chembl_candidate_rows(b30_engine, target_id)
        kept = rows1[0]["source_record_id"]

        seq.payloads.insert(0, _chembl_payload_records([kept]))
        _discover(client, target_id)
        rows = _chembl_candidate_rows(b30_engine, target_id)
        assert any(r["retracted_at"] is not None for r in rows)

        seq.payloads.insert(0, _chembl_payload(4))
        _discover(client, target_id)
        rows = _chembl_candidate_rows(b30_engine, target_id)
        assert all(r["retracted_at"] is None for r in rows)
        assert all(r["retracted_reason"] is None for r in rows)

    def test_candidate_read_and_verdict_agree_after_retraction(self, b30_engine):
        seq = _ChemblSequencer([_chembl_payload(4)])
        client = _client(b30_engine, seq)
        target_id = _resolve(client)
        _discover(client, target_id)
        rows1 = _chembl_candidate_rows(b30_engine, target_id)
        seq.payloads.insert(0, _chembl_payload_records([rows1[0]["source_record_id"]]))
        _discover(client, target_id)

        page = client.get(
            f"/api/v1/targets/{target_id}/candidates",
            params={"include_all_modalities": "true", "limit": 500},
        ).json()
        with b30_engine.connect() as conn:
            live_compounds = set(
                conn.execute(
                    text(
                        "SELECT DISTINCT compound_id FROM target_candidates "
                        "WHERE target_id = :tid AND retracted_at IS NULL"
                    ),
                    {"tid": target_id},
                ).scalars()
            )
        page_compounds = {i["compound_id"] for i in page["items"]}
        live_compounds = {str(c) for c in live_compounds}
        # The read path shows exactly the current rows — a retracted row's
        # compound is invisible unless a live row of any source still carries it.
        assert page_compounds == live_compounds
        assert page["total"] == len(live_compounds)


class TestNoAbsenceWithoutACompleteAnswer:
    def test_failed_ask_retracts_nothing(self, b30_engine):
        from spago_core.adapters.http import SourceUnavailableError

        seq = _ChemblSequencer([_chembl_payload(4)])
        client = _client(b30_engine, seq)
        target_id = _resolve(client)
        _discover(client, target_id)
        before = _chembl_candidate_rows(b30_engine, target_id)

        # The next ask fails outright — an outage must not become a deletion.
        failing = _client(
            b30_engine,
            lambda call: SourceUnavailableError("chembl", "stub outage"),
        )
        run = _discover(failing, target_id)
        chembl = next(r for r in run["sources"] if r["source_name"] == "chembl")
        assert chembl["status"] == "failed"
        assert chembl["retracted_candidates"] == 0
        after = _chembl_candidate_rows(b30_engine, target_id)
        assert {r["source_record_id"]: r["retracted_at"] for r in after} == {
            r["source_record_id"]: None for r in before
        }

    def test_empty_answer_retracts_the_whole_path(self, b30_engine):
        """`empty` is a positive statement — the source answered and holds
        nothing for this query now — so it does establish absence."""
        client = _client(b30_engine, _ChemblSequencer([_chembl_payload(4), _chembl_payload(0)]))
        target_id = _resolve(client)
        _discover(client, target_id)
        assert any(r["retracted_at"] is None for r in _chembl_candidate_rows(b30_engine, target_id))

        run = _discover(client, target_id)
        chembl = next(r for r in run["sources"] if r["source_name"] == "chembl")
        rows = _chembl_candidate_rows(b30_engine, target_id)
        assert all(r["retracted_at"] is not None for r in rows)
        assert chembl["retracted_candidates"] == len(rows)


class TestAccessPathIsolation:
    def test_another_access_paths_rows_are_preserved(self, b30_engine):
        """BindingDB rows exist under the snapshot path; a complete REST
        re-ask that drops records must not touch them (same source_name)."""
        client = _client(b30_engine, _ChemblSequencer([_chembl_payload(4), _chembl_payload(1)]))
        target_id = _resolve(client)
        _discover(client, target_id)

        with b30_engine.begin() as conn:
            compound = conn.execute(text("SELECT id FROM compounds LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, evidence_class, modality,
                                                   source_version, dataset_version, retrieved_at)
                    VALUES (:id, :tid, :cid, 'bindingdb', 'snapshot-row-1',
                            'measured_direct_binding', 'small_molecule',
                            'bindingdb-snapshot-tsv', 'bindingdb-snapshot:2609',
                            now() - interval '1 day')
                    """
                ),
                {"id": uuid.uuid4(), "tid": target_id, "cid": compound},
            )

        _discover(client, target_id)
        with b30_engine.connect() as conn:
            snapshot_row = conn.execute(
                text(
                    "SELECT retracted_at FROM target_candidates "
                    "WHERE target_id = :tid AND source_name = 'bindingdb' "
                    "AND source_record_id = 'snapshot-row-1'"
                ),
                {"tid": target_id},
            ).scalar_one()
        assert snapshot_row is None

    def test_legacy_rows_without_an_access_path_are_never_retracted(self, b30_engine):
        client = _client(b30_engine, _ChemblSequencer([_chembl_payload(4), _chembl_payload(1)]))
        target_id = _resolve(client)
        _discover(client, target_id)
        with b30_engine.begin() as conn:
            conn.execute(
                text("UPDATE target_candidates SET source_version = NULL WHERE target_id = :tid"),
                {"tid": target_id},
            )

        _discover(client, target_id)
        rows = _chembl_candidate_rows(b30_engine, target_id)
        assert all(r["retracted_at"] is None for r in rows)

    def test_another_targets_rows_are_untouched(self, b30_engine):
        client = _client(b30_engine, _ChemblSequencer([_chembl_payload(4), _chembl_payload(1)]))
        target_a = _resolve(client)
        _discover(client, target_a)

        # A second investigation of another target keeps its own rows when the
        # first target refreshes; identity compounds are shared, rows are not.
        with b30_engine.begin() as conn:
            other = uuid.uuid4()
            conn.execute(
                text(
                    """
                    INSERT INTO targets (id, target_key, name, organism, source_name,
                                         dataset_version, retrieved_at, target_type)
                    VALUES (:id, 'B30OTHER', 'Other', 'Homo sapiens', 'uniprot',
                            'uniprot:v', now(), 'single_protein')
                    """
                ),
                {"id": other},
            )
            compound = conn.execute(text("SELECT id FROM compounds LIMIT 1")).scalar_one()
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, evidence_class, modality,
                                                   source_version, dataset_version, retrieved_at)
                    VALUES (:id, :tid, :cid, 'chembl', 'other-1', 'measured_direct_binding',
                            'small_molecule', 'chembl-web-services', 'chembl:v',
                            now() - interval '1 day')
                    """
                ),
                {"id": uuid.uuid4(), "tid": other, "cid": compound},
            )

        _discover(client, target_a)
        with b30_engine.connect() as conn:
            other_row = conn.execute(
                text(
                    "SELECT retracted_at FROM target_candidates "
                    "WHERE source_record_id = 'other-1'"
                ),
            ).scalar_one()
        assert other_row is None


class TestInvestigationViewFollows:
    def test_retracting_the_last_candidate_takes_its_measurements_out(self, b30_engine):
        """The compound-level candidacy rule: measurements stay (shared rows),
        but the investigation no longer sees them through the retracted
        candidate — which is the absence B-30 promises."""
        client = _client(b30_engine, _ChemblSequencer([_chembl_payload(4), _chembl_payload(0)]))
        target_id = _resolve(client)
        _discover(client, target_id)

        with b30_engine.connect() as conn:
            before = conn.execute(
                text("SELECT count(*) FROM investigation_measurements "
                     "WHERE investigation_target_id = :tid"),
                {"tid": target_id},
            ).scalar_one()
            stored = conn.execute(
                text("SELECT count(*) FROM measurements"),
            ).scalar_one()
        assert before > 0
        assert stored >= before

        _discover(client, target_id)
        with b30_engine.connect() as conn:
            after = conn.execute(
                text("SELECT count(*) FROM investigation_measurements "
                     "WHERE investigation_target_id = :tid"),
                {"tid": target_id},
            ).scalar_one()
            still_stored = conn.execute(text("SELECT count(*) FROM measurements")).scalar_one()
            orphaned = conn.execute(
                text(
                    "SELECT count(*) FROM investigation_measurements im "
                    "JOIN target_candidates tc ON tc.target_id = im.investigation_target_id "
                    "  AND tc.compound_id = im.compound_id "
                    "WHERE im.investigation_target_id = :tid AND tc.retracted_at IS NOT NULL "
                    "  AND NOT EXISTS (SELECT 1 FROM target_candidates tc2 "
                    "                  WHERE tc2.target_id = :tid AND tc2.compound_id = im.compound_id "
                    "                  AND tc2.retracted_at IS NULL)"
                ),
                {"tid": target_id},
            ).scalar_one()
        assert after < before, "retracting the candidates must shrink the investigation"
        assert orphaned == 0, "no measurement of a fully-retracted compound may stay in scope"
        # Never deleted: the shared measurement rows remain for other scopes.
        assert still_stored == stored
