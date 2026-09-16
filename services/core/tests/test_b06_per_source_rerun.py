"""B-06: retrying one source must rewrite that source and nothing else.

The recovery path for a `failed` (or `partial`) source is a run that asks **one**
source. The thing that makes that safe is what it does *not* touch: the other
sources' stored retrieval, their counts, their `retrieved_at`, their candidate
rows and the verdict that counts them. These tests pin exactly that, because the
failure mode is silent — one source's status quietly replaced by `not_queried`
while its rows stay in the database, so the status machine contradicts the rows.

Sources are driven from recorded payloads (`data/fixtures/open_sources/`), so the
run itself is offline and deterministic; what is asserted is the database state
and the HTTP contract after a subset run.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.http import SourceUnavailableError
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.uniprot import UniProtTargetResolver
from spago_core.db import run_migrations
from spago_core.domain import RetrievalStatus
from spago_core.main import create_app
from spago_core.services.discovery import (
    TargetDiscoveryService,
    list_source_retrievals,
)
from spago_core.services.targets import TargetResolutionService

from conftest import RESETTABLE_TABLES
from tests.open_source_stubs import StubSourceClient, load_fixture


@pytest.fixture(scope="module")
def b06_engine(pg_engine, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_b06_tables(b06_engine):
    with b06_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    yield


def _uniprot_route(call):
    _url, params = call
    query = (params.get("query") or "").upper()
    if "TSLP" in query or "Q969D9" in query:
        return load_fixture("uniprot_TSLP_human.json")
    return {"results": [], "totalResults": 0}


def healthy(adapters: dict) -> dict:
    """The recorded-payload adapters, all three able to answer."""
    return {
        "chembl": ChEMBLDiscoveryAdapter(
            client=StubSourceClient(
                {
                    "target.json": load_fixture("chembl_targets_Q969D9.json"),
                    "activity.json": load_fixture("chembl_activities_TSLP.json"),
                }
            )
        ),
        "bindingdb": BindingDBRestAdapter(
            client=StubSourceClient({"getLigandsByUniprot": load_fixture("bindingdb_P05231.json")})
        ),
        "pubchem": PubChemAdapter(
            client=StubSourceClient({"genesymbol": load_fixture("pubchem_assays_TSLP.json")})
        ),
        **adapters,
    }


def failing_bindingdb() -> BindingDBRestAdapter:
    return BindingDBRestAdapter(
        client=StubSourceClient(
            {"getLigandsByUniprot": SourceUnavailableError("bindingdb", "HTTP 503")}
        )
    )


@pytest.fixture()
def resolved_target(b06_engine):
    service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    outcome = service.resolve(b06_engine, "TSLP", "human")
    assert outcome.target is not None
    return outcome.target


def rows_by_source(engine, target_id) -> dict:
    return {r.source_name: r for r in list_source_retrievals(engine, target_id)}


def candidate_rows(engine, target_id) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT source_name, source_record_id, retrieved_at, retracted_at,
                           retrieval_id
                    FROM target_candidates
                    WHERE target_id = :tid
                    ORDER BY source_name, source_record_id
                    """
                ),
                {"tid": target_id},
            ).mappings()
        ]


# --- the service: what a subset run writes, and what it must not -------------


class TestSubsetRunPersistence:
    def test_a_never_asked_source_is_still_recorded_as_not_queried(
        self, b06_engine, resolved_target
    ):
        """The placeholder keeps "nobody asked this one" visible in the matrix."""
        service = TargetDiscoveryService(**healthy({}))
        service.investigate(b06_engine, resolved_target, sources=["chembl"])

        stored = rows_by_source(b06_engine, resolved_target.id)
        assert stored["chembl"].status is RetrievalStatus.COMPLETE
        assert stored["bindingdb"].status is RetrievalStatus.NOT_QUERIED
        assert stored["pubchem"].status is RetrievalStatus.NOT_QUERIED
        assert "Not requested." in " ".join(stored["bindingdb"].warnings)

    def test_a_later_subset_run_does_not_rewrite_the_sources_it_did_not_ask(
        self, b06_engine, resolved_target
    ):
        """The defect this round exists for: one source's outcome must survive
        another source's run — status, counts and `retrieved_at` alike."""
        TargetDiscoveryService(**healthy({})).investigate(b06_engine, resolved_target)
        before = rows_by_source(b06_engine, resolved_target.id)

        TargetDiscoveryService(**healthy({"bindingdb": failing_bindingdb()})).investigate(
            b06_engine, resolved_target, sources=["bindingdb"]
        )
        after = rows_by_source(b06_engine, resolved_target.id)

        assert after["bindingdb"].status is RetrievalStatus.FAILED
        for source in ("chembl", "pubchem"):
            assert after[source].status is before[source].status is RetrievalStatus.COMPLETE
            assert after[source].records_kept == before[source].records_kept
            assert after[source].retrieved_at == before[source].retrieved_at
            assert after[source].checksum == before[source].checksum
            assert after[source].latency_ms == before[source].latency_ms
        # The retry is visible as its own fact, not as a changed matrix.
        assert after["bindingdb"].retrieved_at > before["bindingdb"].retrieved_at

    def test_the_report_reports_stored_state_for_a_source_it_did_not_ask(
        self, b06_engine, resolved_target
    ):
        TargetDiscoveryService(**healthy({})).investigate(b06_engine, resolved_target)
        stored = rows_by_source(b06_engine, resolved_target.id)

        report = TargetDiscoveryService(**healthy({"bindingdb": failing_bindingdb()})).investigate(
            b06_engine, resolved_target, sources=["bindingdb"]
        )

        assert report.requested_sources == ["bindingdb"]
        by_source = {r.source_name: r for r in report.retrievals}
        assert set(by_source) == {"chembl", "bindingdb", "pubchem"}
        # A completed source is never reported as "not queried" beside its rows.
        assert by_source["chembl"].status is RetrievalStatus.COMPLETE
        assert by_source["chembl"].retrieved_at == stored["chembl"].retrieved_at
        assert by_source["chembl"].records_kept == stored["chembl"].records_kept
        assert by_source["bindingdb"].status is RetrievalStatus.FAILED

    def test_a_retry_re_dates_only_that_sources_candidate_rows(
        self, b06_engine, resolved_target
    ):
        TargetDiscoveryService(**healthy({})).investigate(b06_engine, resolved_target)
        before = candidate_rows(b06_engine, resolved_target.id)
        # PubChem contributes screening context, not candidate rows, so the rows
        # a retry must leave alone are ChEMBL's (measured against a healthy run).
        assert {row["source_name"] for row in before} == {"chembl", "bindingdb"}

        TargetDiscoveryService(**healthy({"bindingdb": failing_bindingdb()})).investigate(
            b06_engine, resolved_target, sources=["bindingdb"]
        )
        after = candidate_rows(b06_engine, resolved_target.id)

        untouched = {
            (row["source_name"], row["source_record_id"]): row["retrieved_at"]
            for row in before
            if row["source_name"] != "bindingdb"
        }
        for row in after:
            key = (row["source_name"], row["source_record_id"])
            if row["source_name"] == "bindingdb":
                continue
            assert row["retrieved_at"] == untouched[key]

    def test_a_failed_retry_retracts_nothing(self, b06_engine, resolved_target):
        """A failed ask establishes no absence (migration 0015's rule): the rows
        the earlier successful retrieval stored stay current and readable."""
        TargetDiscoveryService(**healthy({})).investigate(b06_engine, resolved_target)
        before = candidate_rows(b06_engine, resolved_target.id)

        TargetDiscoveryService(**healthy({"bindingdb": failing_bindingdb()})).investigate(
            b06_engine, resolved_target, sources=["bindingdb"]
        )
        after = candidate_rows(b06_engine, resolved_target.id)

        assert len(after) == len(before)
        assert all(row["retracted_at"] is None for row in after)

    def test_a_successful_retry_leaves_the_stored_rows_in_place(
        self, b06_engine, resolved_target
    ):
        TargetDiscoveryService(**healthy({})).investigate(b06_engine, resolved_target)
        before = candidate_rows(b06_engine, resolved_target.id)

        TargetDiscoveryService(**healthy({})).investigate(
            b06_engine, resolved_target, sources=["bindingdb"]
        )
        after = candidate_rows(b06_engine, resolved_target.id)

        assert {(r["source_name"], r["source_record_id"]) for r in after} == {
            (r["source_name"], r["source_record_id"]) for r in before
        }
        assert all(row["retracted_at"] is None for row in after)


# --- the API contract -------------------------------------------------------


@pytest.fixture()
def client(b06_engine):
    app = create_app()
    app.state.engine = b06_engine
    app.state.target_service = TargetResolutionService(
        uniprot=UniProtTargetResolver(client=StubSourceClient({"uniprotkb/search": _uniprot_route}))
    )
    app.state.discovery_service = TargetDiscoveryService(**healthy({}))
    return TestClient(app)


@pytest.fixture()
def resolved_api(client) -> dict:
    response = client.post("/api/v1/targets/resolve", json={"query": "TSLP", "species": "human"})
    assert response.status_code == 200, response.text
    return response.json()


class TestDiscoverContract:
    def test_every_source_reports_and_the_run_says_which_it_asked(
        self, client, resolved_api, b06_engine
    ):
        target_id = resolved_api["target_id"]
        full = client.post("/api/v1/targets/discover", json={"target_id": target_id})
        assert full.status_code == 200, full.text
        assert all(row["requested_in_run"] for row in full.json()["sources"])

        stored_before = {
            r["source_name"]: r
            for r in client.get(f"/api/v1/targets/{target_id}/coverage").json()
        }
        retry = client.post(
            "/api/v1/targets/discover",
            json={"target_id": target_id, "sources": ["bindingdb"]},
        )
        assert retry.status_code == 200, retry.text
        rows = {r["source_name"]: r for r in retry.json()["sources"]}
        assert set(rows) == {"chembl", "bindingdb", "pubchem"}
        assert rows["bindingdb"]["requested_in_run"] is True
        assert rows["chembl"]["requested_in_run"] is False
        assert rows["pubchem"]["requested_in_run"] is False
        # The rows it did not ask still describe the earlier retrieval.
        assert rows["chembl"]["status"] == stored_before["chembl"]["status"] == "complete"
        assert rows["chembl"]["records_kept"] == stored_before["chembl"]["records_kept"]
        assert rows["chembl"]["retrieved_at"] == stored_before["chembl"]["retrieved_at"]

    def test_the_coverage_read_carries_no_run_marker(self, client, resolved_api):
        target_id = resolved_api["target_id"]
        client.post("/api/v1/targets/discover", json={"target_id": target_id})
        rows = client.get(f"/api/v1/targets/{target_id}/coverage").json()
        assert rows
        assert all(row["requested_in_run"] is None for row in rows)

    def test_a_retry_leaves_the_verdict_counting_every_source(
        self, client, resolved_api
    ):
        """The point of asking one source is that the investigation — the verdict
        included — still speaks for all of them."""
        target_id = resolved_api["target_id"]
        client.post("/api/v1/targets/discover", json={"target_id": target_id})
        before = client.get(f"/api/v1/targets/{target_id}/reference").json()

        retry = client.post(
            "/api/v1/targets/discover",
            json={"target_id": target_id, "sources": ["bindingdb"]},
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["reference"]["compounds"] == before["compounds"]
        after = client.get(f"/api/v1/targets/{target_id}/reference").json()
        assert after["compounds"] == before["compounds"]
        assert after["class_counts"] == before["class_counts"]

    def test_a_run_that_asks_nothing_is_refused(self, client, resolved_api):
        response = client.post(
            "/api/v1/targets/discover",
            json={"target_id": resolved_api["target_id"], "sources": []},
        )
        assert response.status_code == 422
        assert "at least one source" in response.json()["detail"]

    def test_an_unknown_source_is_still_refused(self, client, resolved_api):
        response = client.post(
            "/api/v1/targets/discover",
            json={"target_id": resolved_api["target_id"], "sources": ["bindingdb", "espacenet"]},
        )
        assert response.status_code == 422
        assert "espacenet" in response.json()["detail"]
