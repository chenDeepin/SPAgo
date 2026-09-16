"""B-29: a stored analysis as a project artifact.

A project could hold compounds and families, not the analysis that explains
why they were picked. These tests pin the reference contract: attaching is
idempotent and owner-scoped, the project detail lists the reference with its
identity snapshot, reopening reads the stored text without a provider call,
and a vanished analysis row leaves the reference readable and marked — the
migration-0008 contract applied to analyses.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services import ai

from conftest import RESETTABLE_TABLES, _family_id


@pytest.fixture(scope="module")
def b29_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


@pytest.fixture(autouse=True)
def clean_tables(b29_engine):
    with b29_engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(RESETTABLE_TABLES) + " CASCADE"))
    # Re-seed after truncation so the family summary has data to summarize.
    seed(b29_engine, Path(__file__).resolve().parents[3] / "data" / "fixtures", None)
    yield


@pytest.fixture()
def client(b29_engine):
    app = __import__("spago_core.main", fromlist=["create_app"]).create_app()
    app.state.engine = b29_engine
    return TestClient(app)


@pytest.fixture()
def stored_analysis(client, b29_engine) -> str:
    """A real stored offline family summary (no provider)."""
    result = ai.summarize_family(b29_engine, _family_id(b29_engine))
    return str(result["analysis_id"])


def _project(client, name: str) -> str:
    res = client.post("/api/v1/projects", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()["id"]


class TestAttachAndRead:
    def test_attach_lists_and_reads_back(self, client, stored_analysis):
        project = _project(client, "b29-a")
        res = client.post(
            f"/api/v1/projects/{project}/analyses", json={"analysis_id": stored_analysis}
        )
        assert res.status_code == 201, res.text
        ref = res.json()
        assert ref["analysis_id"] == stored_analysis
        assert ref["scope"] == "family"
        assert ref["provider"]
        assert ref["analysis_missing"] is False

        detail = client.get(f"/api/v1/projects/{project}").json()
        assert len(detail["analyses"]) == 1
        assert detail["analyses"][0]["analysis_id"] == stored_analysis

        # Reopening is a pure read: the stored analysis text is served with no
        # provider configured (the suite blanks SPAGO_LLM_*).
        analysis = client.get(f"/api/v1/analyses/{stored_analysis}").json()
        assert analysis["text"]

    def test_attach_is_idempotent(self, client, stored_analysis):
        project = _project(client, "b29-b")
        first = client.post(
            f"/api/v1/projects/{project}/analyses", json={"analysis_id": stored_analysis}
        )
        second = client.post(
            f"/api/v1/projects/{project}/analyses", json={"analysis_id": stored_analysis}
        )
        assert first.status_code == 201 and second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        detail = client.get(f"/api/v1/projects/{project}").json()
        assert len(detail["analyses"]) == 1

    def test_unknown_analysis_is_refused(self, client):
        project = _project(client, "b29-c")
        res = client.post(
            f"/api/v1/projects/{project}/analyses",
            json={"analysis_id": str(uuid.uuid4())},
        )
        assert res.status_code == 404

    def test_remove_reference_leaves_the_analysis(self, client, stored_analysis):
        project = _project(client, "b29-d")
        ref = client.post(
            f"/api/v1/projects/{project}/analyses", json={"analysis_id": stored_analysis}
        ).json()
        res = client.delete(f"/api/v1/projects/{project}/analyses/{ref['id']}")
        assert res.status_code == 204
        detail = client.get(f"/api/v1/projects/{project}").json()
        assert detail["analyses"] == []
        # The stored artifact itself is untouched.
        assert client.get(f"/api/v1/analyses/{stored_analysis}").status_code == 200


class TestVanishedAnalysis:
    def test_missing_analysis_row_leaves_a_marked_readable_reference(self, client, b29_engine, stored_analysis):
        project = _project(client, "b29-e")
        client.post(
            f"/api/v1/projects/{project}/analyses", json={"analysis_id": stored_analysis}
        )
        # The analysis row disappears (no delete route exists today; the
        # reference contract has to survive one anyway).
        with b29_engine.begin() as conn:
            conn.execute(text("DELETE FROM ai_analyses WHERE id = :aid"), {"aid": stored_analysis})

        detail = client.get(f"/api/v1/projects/{project}").json()
        assert len(detail["analyses"]) == 1
        ref = detail["analyses"][0]
        assert ref["analysis_missing"] is True
        assert ref["scope_label"], "the snapshot stays readable"
        assert ref["provider"]
        # And the direct read of the gone analysis is a clean 404, not a
        # misleading render of the snapshot as if it were the artifact.
        assert client.get(f"/api/v1/analyses/{stored_analysis}").status_code == 404
