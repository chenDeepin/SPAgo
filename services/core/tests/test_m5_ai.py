"""M5 tests: extractive summary with citations, deterministic planner, API."""
from __future__ import annotations

from pathlib import Path

import pytest

from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services import ai
from conftest import _family_id


@pytest.fixture(scope="module")
def m5_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


class TestPlanner:
    def test_extracts_publication_numbers_deterministically(self):
        plan = ai.plan_query("CDK4 inhibitors like EP1234567A1 or us10102057b2, 2023+")
        assert plan["patent_queries"] == ["EP1234567A1", "US10102057B2"]
        assert "CDK4" in plan["unresolved_text"]
        assert "LLM" in plan["note"]

    def test_empty_query_is_safe(self):
        assert ai.plan_query("")["patent_queries"] == []


class TestFamilySummary:
    def test_summary_is_extractive_with_citations(self, m5_engine):
        result = ai.summarize_family(m5_engine, _family_id(m5_engine))
        assert result["provider"] == "offline-extractive"
        # No LLM configured: the output must NOT claim llm_inferred status.
        assert result["provenance_state"] == "machine_extracted"
        # Measurements are cited to stored evidence rows.
        assert len(result["citations"]) >= 5
        assert all(c["evidence_id"] for c in result["citations"])
        assert "610" in result["text"]  # S-ibuprofen demo value appears with its assay
        assert "not ranked" in result["text"]

    def test_summary_is_stable_and_persisted(self, m5_engine):
        engine = m5_engine
        first = ai.summarize_family(engine, _family_id(engine))
        second = ai.summarize_family(engine, _family_id(engine))
        assert first["analysis_id"] == second["analysis_id"]
        from sqlalchemy import text

        with engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM ai_analyses WHERE family_id = :f"),
                {"f": _family_id(engine)},
            ).scalar_one()
        assert n == 1

    def test_unknown_family_404(self, m5_engine):
        import uuid as uuid_mod

        from spago_core.services import NotFoundError

        with pytest.raises(NotFoundError) as exc_info:
            ai.summarize_family(m5_engine, uuid_mod.UUID(int=1))
        assert "not found" in str(exc_info.value)


class TestSummaryApi:
    def test_summary_endpoint(self, m5_engine):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = m5_engine
        client = TestClient(app)
        res = client.post(f"/api/v1/families/{_family_id(m5_engine)}/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["provider"] == "offline-extractive"
        assert body["provenance_state"] == "machine_extracted"
        assert isinstance(body["citations"], list)

    def test_plan_endpoint(self, m5_engine):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = m5_engine
        client = TestClient(app)
        res = client.post("/api/v1/ai/plan", json={"query": "patents like US10000000B2"})
        assert res.status_code == 200
        assert res.json()["patent_queries"] == ["US10000000B2"]
