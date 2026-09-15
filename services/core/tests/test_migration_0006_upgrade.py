"""Forward migration from 0005 to 0006 on an already-populated database.

The historical record says migration 0006 was applied to an empty database.
This test covers the upgrade path an existing deployment actually takes:

- migrate and seed up to 0005, then insert an analysis row in the *pre-0006*
  column shape (the 0005 INSERT statement, quoted from migration 0005);
- apply 0006;
- verify the legacy row is still there with its text and citations unchanged,
  that it is not treated as a new-protocol cache hit, and that new analyses use
  the content key without rewriting it.

The database used here is a dedicated scratch database; a running deployment
database is never touched.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from conftest import _base_url
from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services import ai

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "migrations"
UPGRADE_DB = "spago_test_upgrade_0005"


@pytest.fixture(scope="module")
def upgrade_engine():
    """Scratch database migrated only through 0005, then upgraded in-test."""
    try:
        admin = create_engine(_base_url() + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {UPGRADE_DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {UPGRADE_DB}"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL not reachable; upgrade test skipped: {exc}")

    su = create_engine(
        _base_url().replace("://spago:spago@", "://postgres:spago@") + f"/{UPGRADE_DB}",
        isolation_level="AUTOCOMMIT",
    )
    with su.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS rdkit"))
    su.dispose()

    engine = create_engine(_base_url() + f"/{UPGRADE_DB}", pool_pre_ping=True)
    yield engine
    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {UPGRADE_DB} WITH (FORCE)"))
    admin.dispose()


def _dir_up_to(version: int) -> Path:
    """A temporary migrations directory containing only NNNN_name.sql ≤ version."""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="spago-migrations-"))
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        number = int(path.name.split("_", 1)[0])
        if number <= version:
            (root / path.name).write_text(path.read_text())
    return root


def _family_id(engine) -> uuid.UUID:
    with engine.connect() as conn:
        return uuid.UUID(
            str(
                conn.execute(
                    text("SELECT id FROM patent_families WHERE family_key = 'DEMO-FAMILY-1'")
                ).scalar_one()
            )
        )


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t AND table_schema = current_schema()"
            ),
            {"t": table},
        ).all()
    return {r[0] for r in rows}


class TestForwardUpgrade0005To0006:
    def _insert_legacy_analysis(self, engine, family: uuid.UUID) -> uuid.UUID:
        """The pre-0006 insert shape (migration 0005 columns only)."""
        legacy_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ai_analyses (id, family_id, provider, analysis_kind, text,
                                             citations, provenance_state, dataset_version)
                    VALUES (:id, :family_id, 'offline-extractive', 'family_summary',
                            :text, CAST(:citations AS jsonb), 'machine_extracted',
                            'demo-fixture-v1')
                    """
                ),
                {
                    "id": legacy_id,
                    "family_id": family,
                    "text": "Legacy offline summary written before migration 0006.",
                    "citations": json.dumps([{"fact_ref": f"family:{family}", "kind": "family"}]),
                },
            )
        return legacy_id

    def test_existing_analyses_survive_and_do_not_false_hit(self, upgrade_engine):
        engine = upgrade_engine
        run_migrations(engine, _dir_up_to(5))
        seed(engine, REPO_ROOT / "data" / "fixtures", _dir_up_to(5))
        assert "input_hash" not in _columns(engine, "ai_analyses")  # pre-0006 shape

        family = _family_id(engine)
        legacy_id = self._insert_legacy_analysis(engine, family)

        # Upgrade: the family and its existing analysis row must survive.
        applied = run_migrations(engine, MIGRATIONS_DIR)
        assert 6 in applied
        assert {"input_hash", "prompt_version", "input_snapshot", "usage"} <= _columns(
            engine, "ai_analyses"
        )
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT provider, text, citations, input_hash, input_snapshot "
                    "FROM ai_analyses WHERE id = :id"
                ),
                {"id": legacy_id},
            ).mappings().first()
        assert row is not None
        assert row["text"] == "Legacy offline summary written before migration 0006."
        assert row["citations"] == [{"fact_ref": f"family:{family}", "kind": "family"}]
        # Pre-0006 rows keep NULL new columns: they must not look like cache hits.
        assert row["input_hash"] is None
        assert row["input_snapshot"] is None

        # A summary requested after the upgrade recomputes under the new content
        # key and adds one row; the legacy row is neither a hit nor rewritten.
        refreshed = ai.summarize_family(engine, family, mode="offline")
        assert refreshed["cached"] is False
        assert refreshed["analysis_id"] != legacy_id
        assert refreshed["coverage"], "new rows carry coverage/version information"
        with engine.connect() as conn:
            total = conn.execute(
                text("SELECT count(*) FROM ai_analyses WHERE family_id = :f"), {"f": family}
            ).scalar_one()
            stored = conn.execute(
                text("SELECT text, citations FROM ai_analyses WHERE id = :id"),
                {"id": legacy_id},
            ).mappings().first()
        assert total == 2  # legacy row + new content-keyed row
        assert stored["text"] == "Legacy offline summary written before migration 0006."

        # And the new row is a genuine content cache: the same call is a hit.
        again = ai.summarize_family(engine, family, mode="offline")
        assert again["cached"] is True
        assert again["analysis_id"] == refreshed["analysis_id"]
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM ai_analyses WHERE family_id = :f"), {"f": family}
                ).scalar_one()
                == 2
            )

    def test_llm_key_does_not_collide_with_the_offline_key(self, upgrade_engine):
        engine = upgrade_engine
        family = _family_id(engine)
        offline = ai.summarize_family(engine, family, mode="offline")

        calls = {"n": 0}

        class _Provider:
            name = "llm-openai-compatible"
            model = "upgrade-model"
            endpoint_fingerprint = "fingerprint"
            provenance_state = __import__(
                "spago_core.domain", fromlist=["ProvenanceState"]
            ).ProvenanceState.LLM_INFERRED

            def generate(self, snapshot):
                calls["n"] += 1
                from spago_core.adapters.llm import ProviderOutput

                refs = [snapshot["family"]["ref"]]
                refs += [m["ref"] for m in snapshot["measurements"][:2]]
                return ProviderOutput(
                    content=json.dumps(
                        {"paragraphs": [{"text": "Upgrade path check.", "fact_refs": refs}]}
                    ),
                    finish_reason="stop",
                    tool_calls=False,
                    usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    model="upgrade-model",
                )

        llm = ai.summarize_family(engine, family, mode="llm", llm_provider=_Provider())
        assert calls["n"] == 1
        assert llm["provenance_state"] == "llm_inferred"
        assert llm["analysis_id"] != offline["analysis_id"]
        with engine.connect() as conn:
            snapshot = conn.execute(
                text("SELECT input_snapshot FROM ai_analyses WHERE id = :id"),
                {"id": llm["analysis_id"]},
            ).scalar_one()
        # The stored snapshot is bounded and annotated; no secrets are stored.
        assert len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) <= ai.MAX_BODY_BYTES
        assert snapshot["input_note"] == ai.INPUT_NOTE
