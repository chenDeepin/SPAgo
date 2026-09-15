"""Shared pytest fixtures.

PG-gated integration tests skip with a clear reason when PostgreSQL is not
reachable; unit/chemistry/adapter/DuckDB tests always run.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures"
MIGRATIONS_DIR = REPO_ROOT / "migrations"

TEST_DB = "spago_test"


def _base_url() -> str:
    url = os.environ.get(
        "SPAGO_TEST_DATABASE_URL",
        "postgresql+psycopg://spago:spago@localhost:5432/spago",
    )
    return url.rsplit("/", 1)[0]


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def migrations_dir() -> Path:
    return MIGRATIONS_DIR


@pytest.fixture()
def app_client(pg_engine):
    """TestClient bound to a fresh app over the scratch database."""
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = pg_engine
    client = TestClient(app)
    client.family_id = _family_id(pg_engine)
    return client


def _family_id(engine) -> _uuid.UUID:
    import uuid as _uuid2

    from sqlalchemy import text as _text

    with engine.connect() as conn:
        return _uuid2.UUID(
            str(
                conn.execute(
                    _text("SELECT id FROM patent_families WHERE family_key = 'DEMO-FAMILY-1'")
                ).scalar_one()
            )
        )


@pytest.fixture(scope="session")
def family_id(pg_engine):
    return _family_id(pg_engine)


def compound_id_by_inchikey(engine, inchikey: str):
    import uuid as _uuid3

    from sqlalchemy import text as _text2

    with engine.connect() as conn:
        return _uuid3.UUID(
            str(
                conn.execute(
                    _text2("SELECT id FROM compounds WHERE inchikey = :k"), {"k": inchikey}
                ).scalar_one()
            )
        )


@pytest.fixture(scope="session")
def pg_engine() -> Engine:
    """A fresh scratch database per test session; skips when PG is unreachable."""
    try:
        admin = create_engine(_base_url() + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
        admin.dispose()
    except Exception as exc:
        if os.environ.get("SPAGO_REQUIRE_TEST_DATABASE") == "1":
            raise RuntimeError("Required PostgreSQL test database could not be prepared") from exc
        pytest.skip(f"PostgreSQL not reachable; integration tests skipped: {exc}")

    # The RDKit cartridge needs superuser rights; the scratch database inherits
    # nothing, so enable it explicitly (postgres role password comes from db init).
    # Fail loudly rather than silently: migrations 0003+ need the cartridge.
    try:
        su = create_engine(
            _base_url().replace("://spago:spago@", "://postgres:spago@") + f"/{TEST_DB}",
            isolation_level="AUTOCOMMIT",
        )
        with su.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS rdkit"))
            probe = conn.execute(
                text("SELECT current_database(), count(*) FROM pg_extension WHERE extname='rdkit'")
            ).first()
            print(f"\n[conftest] extension probe: db={probe[0]} rdkit_installed={probe[1]}", flush=True)
        su.dispose()
    except Exception as exc:
        raise RuntimeError(
            f"Could not create the rdkit extension in the scratch database: {exc}"
        ) from exc

    engine = create_engine(_base_url() + f"/{TEST_DB}", pool_pre_ping=True)
    yield engine

    engine.dispose()
    try:
        admin = create_engine(_base_url() + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        admin.dispose()
    except Exception:
        pass
