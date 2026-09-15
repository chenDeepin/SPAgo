"""M5 + LLM-interface tests: extractive summary, typed citations, content-key
caching, deterministic planner, status/mode API."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

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
    """The deterministic planner now lives in `services.planner` and emits the
    same typed contract the model produces (ONLINE-02)."""

    def test_extracts_publication_numbers_deterministically(self):
        from spago_core.services import planner

        plan = planner.offline_plan("CDK4 inhibitors like EP1234567A1 or us10102057b2, 2023+")
        ops = [step["op"] for step in plan.steps]
        assert ops == ["open_patent", "open_patent"]
        assert [s["publication_number"] for s in plan.steps] == ["EP1234567A1", "US10102057B2"]
        assert "CDK4" in " ".join(plan.unresolved)
        # Free text is reported unresolved, never interpreted.
        assert plan.producer == "offline"
        assert plan.clarification_required is True

    def test_empty_query_is_safe(self):
        from spago_core.services import planner

        plan = planner.offline_plan("")
        assert plan.steps == []
        assert plan.clarification_required is True


class TestFamilySummary:
    def test_summary_is_extractive_with_typed_citations(self, m5_engine):
        result = ai.summarize_family(m5_engine, _family_id(m5_engine))
        assert result["provider"] == "offline-extractive"
        # No LLM configured: the output must NOT claim llm_inferred status.
        assert result["provenance_state"] == "machine_extracted"
        # Measurements are cited as measurement records, never as patent-text
        # evidence (LLM-01).
        assert result["citations"], "summary must carry citations"
        assert result["citations"][0]["fact_ref"].startswith("family:")
        measurement_citations = [c for c in result["citations"] if c["kind"] == "measurement"]
        assert measurement_citations, "fixture has measurements"
        for c in measurement_citations:
            assert c["fact_ref"].startswith("measurement:")
            assert "evidence_id" not in c  # never attributed to patent text
            assert c["inchikey"]
        assert "610" in result["text"]  # S-ibuprofen demo value appears with its assay
        assert "not ranked" in result["text"]

    def test_global_issues_excluded_from_family_summary(self, m5_engine):
        # The fixture records one global ingestion issue; family conclusions
        # must not absorb it (LLM-04).
        result = ai.summarize_family(m5_engine, _family_id(m5_engine))
        assert "failed validation" not in result["text"]

    def test_scaffolds_counted_by_distinct_compound(self, m5_engine):
        # Aspirin has two mentions but one compound: scaffold counts use
        # compound granularity (LLM-04).
        result = ai.summarize_family(m5_engine, _family_id(m5_engine))
        benzene = next(
            s for s in result["input_snapshot"]["scaffolds"] if s["scaffold"] == "c1ccccc1"
        )
        assert benzene["compounds"] >= 2  # aspirin + racemic ibuprofen share it

    def test_summary_is_stable_and_persisted(self, m5_engine):
        engine = m5_engine
        first = ai.summarize_family(engine, _family_id(engine))
        second = ai.summarize_family(engine, _family_id(engine))
        assert first["analysis_id"] == second["analysis_id"]
        assert second["cached"] is True  # served from the content cache
        with engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM ai_analyses "
                    "WHERE family_id = :f AND provider = 'offline-extractive'"
                ),
                {"f": _family_id(engine)},
            ).scalar_one()
        assert n == 1

    def test_value_change_changes_cache_key(self, m5_engine):
        """LLM-02: identical record counts but a changed value must produce a
        new input hash and a fresh analysis row."""
        engine = m5_engine
        fid = _family_id(engine)
        before = ai.summarize_family(engine, fid)

        with engine.begin() as conn:
            conn.execute(text("UPDATE measurements SET value = value + 1 WHERE value = 610"))
        try:
            after = ai.summarize_family(engine, fid)
            assert after["analysis_id"] != before["analysis_id"]
            assert after["cached"] is False
            with engine.connect() as conn:
                n = conn.execute(
                    text(
                        "SELECT count(*) FROM ai_analyses "
                        "WHERE family_id = :f AND provider = 'offline-extractive'"
                    ),
                    {"f": fid},
                ).scalar_one()
            assert n == 2
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE measurements SET value = value - 1 WHERE value = 611")
                )

    def test_unknown_family_raises(self, m5_engine):
        from spago_core.services import NotFoundError

        with pytest.raises(NotFoundError):
            ai.summarize_family(m5_engine, uuid.UUID(int=1))


class TestSnapshotBudgetBoundary:
    """LLM-05: an unrepresentable input fails before any provider call and is
    never persisted as a successful analysis."""

    def test_unrepresentable_family_fails_without_provider_call_or_cache_write(self, m5_engine):
        from spago_core.domain import ProvenanceState

        engine = m5_engine
        family = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_families
                        (id, family_key, title, source_name, dataset_version, retrieved_at)
                    VALUES (:id, :key, 'Oversized fixture (synthetic)', 'fixture',
                            'budget-test-v1', now())
                    """
                ),
                {"id": family, "key": "K" * (ai.MAX_BODY_BYTES + 512)},
            )

        calls = {"n": 0}

        class _Provider:
            name = "llm-openai-compatible"
            model = "demo-model"
            endpoint_fingerprint = "unused"
            provenance_state = ProvenanceState.LLM_INFERRED

            def generate(self, snapshot):  # pragma: no cover - must not be reached
                calls["n"] += 1
                raise AssertionError("provider must not be called for an unrepresentable input")

        try:
            with pytest.raises(ai.SnapshotBudgetError):
                ai.summarize_family(engine, family, mode="llm", llm_provider=_Provider())
            assert calls["n"] == 0
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT count(*) FROM ai_analyses WHERE family_id = :f"),
                    {"f": family},
                ).scalar_one()
            assert rows == 0
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM patent_families WHERE id = :id"), {"id": family})


class TestSummaryApi:
    def _client(self, engine):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = engine
        return TestClient(app)

    def test_summary_endpoint_default_offline(self, m5_engine):
        client = self._client(m5_engine)
        # Legacy call shape: no body at all must stay offline.
        res = client.post(f"/api/v1/families/{_family_id(m5_engine)}/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["provider"] == "offline-extractive"
        assert body["provenance_state"] == "machine_extracted"
        assert body["mode"] == "offline"
        assert body["cached"] is True  # cached by the earlier service-level test
        assert isinstance(body["citations"], list)
        assert body["model"] is None

    def test_summary_llm_without_config_is_503(self, m5_engine):
        client = self._client(m5_engine)
        res = client.post(
            f"/api/v1/families/{_family_id(m5_engine)}/summary",
            json={"mode": "llm"},
        )
        assert res.status_code == 503

    def test_plan_endpoint_returns_the_typed_plan(self, m5_engine):
        client = self._client(m5_engine)
        res = client.post("/api/v1/ai/plan", json={"query": "patents like US10000000B2"})
        assert res.status_code == 200
        body = res.json()
        assert body["plan_version"] == "search-plan-v1"
        assert body["producer"] == "offline"
        assert [s["op"] for s in body["steps"]] == ["open_patent"]
        assert body["steps"][0]["parameters"]["publication_number"] == "US10000000B2"
        # The rest of the sentence was not interpreted; it is reported.
        assert body["unresolved"]


class TestAiStatus:
    def _client(self):
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        return TestClient(create_app())

    def test_default_offline(self, monkeypatch):
        from spago_core.config import get_settings

        for var in ("SPAGO_LLM_BASE_URL", "SPAGO_LLM_MODEL", "SPAGO_LLM_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        get_settings.cache_clear()
        body = self._client().get("/api/v1/ai/status").json()
        assert body["state"] == "offline"
        assert body["model"] is None and body["target"] is None
        get_settings.cache_clear()

    def test_config_invalid_when_half_configured(self, m5_engine, monkeypatch):
        from spago_core.config import get_settings

        monkeypatch.setenv("SPAGO_LLM_BASE_URL", "https://provider.example/v1")
        monkeypatch.delenv("SPAGO_LLM_MODEL", raising=False)
        get_settings.cache_clear()
        body = self._client().get("/api/v1/ai/status").json()
        assert body["state"] == "config_invalid"
        assert "SPAGO_LLM_MODEL" in body["reason"]
        get_settings.cache_clear()

    def test_configured_reports_sanitized_target(self, m5_engine, monkeypatch):
        from spago_core.config import get_settings

        monkeypatch.setenv("SPAGO_LLM_BASE_URL", "https://provider.example/v1")
        monkeypatch.setenv("SPAGO_LLM_MODEL", "demo-model")
        monkeypatch.setenv("SPAGO_LLM_API_KEY", "sk-secret")
        get_settings.cache_clear()
        body = self._client().get("/api/v1/ai/status").json()
        assert body["state"] == "configured"
        assert body["model"] == "demo-model"
        assert body["target"] == "https://provider.example/v1"
        assert "sk-secret" not in json.dumps(body)
        get_settings.cache_clear()
        monkeypatch.delenv("SPAGO_LLM_API_KEY", raising=False)
