"""Structure-search paging acceptance (UI review UI-03).

Builds a minimal synthetic fixture with >100 compounds (deterministic alkane
chain SMILES) and verifies the server paging contract: real totals, offset
pages, the 500-row cap, and that no ordinary response exceeds it.
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from spago_core.db import run_migrations
from spago_core.seed import seed
from conftest import _base_url

N_COMPOUNDS = 150

from sqlalchemy import create_engine, text


@pytest.fixture(scope="module")
def paging_engine(pg_engine):
    """Seed a >100-compound family into the scratch database."""
    fixture_dir = _build_fixture()
    run_migrations(pg_engine, Path(__file__).resolve().parents[3] / "migrations")
    seed(pg_engine, fixture_dir, Path(__file__).resolve().parents[3] / "migrations")
    return pg_engine


def _build_fixture() -> Path:
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="spago-paging-fixture-"))
    smiles = ["C" * n for n in range(2, 2 + N_COMPOUNDS)]  # C..C150, all valid, unique

    patents_tbl = pa.table(
        {
            "publication_number": ["PAGING-PATENT-1"],
            "family_key": ["PAGING-FAMILY-1"],
            "title": ["Pagination fixture (synthetic)"],
            "abstract": ["Synthetic fixture for paging verification."],
            "assignee": ["Demo (illustrative)"],
            "publication_date": pa.array([__import__("datetime").date(2024, 1, 1)], pa.date32()),
            "jurisdiction": ["WO"],
            "doc_type": ["application"],
        }
    )
    records_tbl = pa.table(
        {
            "document_id": ["PAGING-PATENT-1"] * N_COMPOUNDS,
            "compound_id": [f"SC-PAGE-{i:04d}" for i in range(N_COMPOUNDS)],
            "patent_label": [f"Example {i:04d}" for i in range(N_COMPOUNDS)],
            "smiles": smiles,
            "source_field": ["description"] * N_COMPOUNDS,
            "section": [f"Example {i:04d}" for i in range(N_COMPOUNDS)],
            "page": [i + 1 for i in range(N_COMPOUNDS)],
        }
    )
    (root / "patents").mkdir(parents=True)
    (root / "surechembl").mkdir(parents=True)
    pq.write_table(patents_tbl, root / "patents" / "patent_documents_demo_fixture.parquet")
    pq.write_table(records_tbl, root / "surechembl" / "surechembl_demo_fixture.parquet")
    (root / "manifest.json").write_text(
        '{"source_name": "surechembl_simplified_fixture", "dataset_version": '
        '"paging-fixture-v1", "synthetic": true, "files": {}}'
    )
    return root


def _family_id(engine) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT id FROM patent_families WHERE family_key = 'PAGING-FAMILY-1'")
            ).scalar_one()
        )


def _client(engine):
    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


class TestPaging:
    def test_compounds_total_and_pages(self, paging_engine):
        engine = paging_engine
        client = _client(engine)
        fid = _family_id(engine)

        page1 = client.get(f"/api/v1/families/{fid}/compounds").json()
        assert page1["total"] == N_COMPOUNDS
        assert len(page1["items"]) == 100

        page2 = client.get(f"/api/v1/families/{fid}/compounds?offset=100&limit=100").json()
        assert len(page2["items"]) == 50
        keys1 = {i["compound"]["inchikey"] for i in page1["items"]}
        keys2 = {i["compound"]["inchikey"] for i in page2["items"]}
        assert keys1.isdisjoint(keys2)

        capped = client.get(f"/api/v1/families/{fid}/compounds?limit=99999").json()
        assert capped["limit"] == 500  # hard cap, never more rows than that

    def test_structure_search_paging_and_cap(self, paging_engine):
        engine = paging_engine
        client = _client(engine)
        fid = _family_id(engine)

        res = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C", "limit": 100},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == N_COMPOUNDS  # real total, not rows.length
        assert len(body["items"]) == 100

        res2 = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C", "limit": 100, "offset": 100},
        )
        body2 = res2.json()
        assert len(body2["items"]) == 50
        keys1 = {i["compound"]["inchikey"] for i in body["items"]}
        keys2 = {i["compound"]["inchikey"] for i in body2["items"]}
        assert keys1.isdisjoint(keys2)

        capped = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C", "limit": 99999},
        )
        assert capped.json()["limit"] == 500

        exact = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "exact", "smiles": "CCC"},
        )
        assert exact.json()["total"] == 1  # propane

    def test_responses_stay_under_hard_cap(self, paging_engine):
        engine = paging_engine
        client = _client(engine)
        fid = _family_id(engine)
        res = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C", "limit": 500, "offset": 0},
        )
        assert len(res.json()["items"]) <= 500
        compounds = client.get(f"/api/v1/families/{fid}/compounds?limit=500")
        assert len(compounds.json()["items"]) <= 500
