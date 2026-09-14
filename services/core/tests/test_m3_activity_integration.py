"""M3 database + API integration: measurements, scaffolds, activity column."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from spago_core import services
from spago_core.db import run_migrations
from spago_core.seed import seed
from conftest import compound_id_by_inchikey, _family_id


@pytest.fixture(scope="module")
def m3_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    report = seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine, report


def _client(engine):
    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


class TestSeedActivity:
    def test_measurements_seeded(self, m3_engine):
        engine, report = m3_engine
        assert report.measurements == 6

    def test_scaffolds_computed(self, m3_engine):
        engine, _ = m3_engine
        with engine.connect() as conn:
            row = conn.execute(
                text := __import__("sqlalchemy").text,
                {},
            ) if False else None
        from sqlalchemy import text

        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT inchikey, scaffold FROM compounds WHERE inchikey = :k"),
                {"k": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"},
            ).first()
        assert rows is not None
        assert rows[1]  # aspirin has a non-empty Murcko scaffold


class TestActivityApi:
    def test_family_compounds_carry_activity(self, m3_engine):
        engine, _ = m3_engine
        client = _client(engine)
        res = client.get(f"/api/v1/families/{_family_id(engine)}/compounds")
        assert res.status_code == 200
        items = res.json()["items"]
        s_ibu = next(
            i for i in items if i["compound"]["inchikey"] == "HEFNNWSXXWATRW-SNVBAGLBSA-N"
        )
        assert len(s_ibu["activity"]) == 1
        a = s_ibu["activity"][0]
        assert a["standard_type"] == "IC50"
        assert a["value"] == 610.0
        assert a["unit"] == "nM"
        assert a["provenance_state"] == "machine_extracted"

        naproxen = next(
            i for i in items if i["compound"]["inchikey"] == "CMWTZPSULFXXJA-SECBINFHSA-N"
        )
        # two assays: listed separately, never merged into one ranking number
        assert len(naproxen["activity"]) == 2
        assert {x["assay_key"] for x in naproxen["activity"]} == {"DEMO-ASSAY-1", "DEMO-ASSAY-2"}

        caffeine = next(
            i for i in items if i["compound"]["inchikey"] == "RYYVLZVUVIJVGH-UHFFFAOYSA-N"
        )
        assert caffeine["activity"] == []  # no activity: shown as none, not as zero

    def test_compound_activity_endpoint(self, m3_engine):
        engine, _ = m3_engine
        client = _client(engine)
        cid = compound_id_by_inchikey(engine, "CMWTZPSULFXXJA-SECBINFHSA-N")
        res = client.get(f"/api/v1/compounds/{cid}/activity")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2
        assert {i["assay_type"] for i in items} == {"enzymatic", "cellular"}

    def test_compounds_include_scaffold(self, m3_engine):
        engine, _ = m3_engine
        client = _client(engine)
        res = client.get(f"/api/v1/families/{_family_id(engine)}/compounds")
        items = res.json()["items"]
        aspirin = next(
            i for i in items if i["compound"]["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        )
        assert aspirin["compound"]["scaffold"]
