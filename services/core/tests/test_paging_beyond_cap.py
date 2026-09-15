"""Ordinary compound paging beyond the 500-row response cap (UI review UI-07).

The historical fixture (`test_paging_contract.py`, 150 rows) cannot reach the
boundary this test targets. Here the family holds 601 unique synthetic esters
built from two chain-length axes, so rows 501+ (rather than "longer and longer
alkanes") are exercised, every structure is chemically distinct after RDKit
normalization, and each response stays under the documented hard cap.

Datasets built here are explicitly synthetic fixtures in a scratch database;
the developer/CI database is never used as test data.
"""
from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import create_engine, text

from spago_core.db import run_migrations
from spago_core.seed import seed

N_COMPOUNDS = 601  # > 500 so that offset=500 and the final partial page are reachable
PAGE = 100
MAX_ROWS = 500

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def beyond_cap_engine(pg_engine):
    fixture_dir = _build_fixture()
    run_migrations(pg_engine, REPO_ROOT / "migrations")
    seed(pg_engine, fixture_dir, REPO_ROOT / "migrations")
    return pg_engine


def _smiles_for(index: int) -> str:
    """Unique, bounded, valid structures: an ester with two chain lengths.

    Index → (acid-side carbons, alcohol-side carbons); 27 × 23 = 621 ≥ 601
    combinations. No duplicate structures, no unbounded molecule growth."""
    acid_side = index % 27
    alcohol_side = index // 27 + 1
    return f"{'C' * acid_side}C(=O)O{'C' * alcohol_side}"


def _build_fixture() -> Path:
    import datetime
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="spago-paging501-fixture-"))
    smiles = [_smiles_for(i) for i in range(N_COMPOUNDS)]

    patents_tbl = pa.table(
        {
            "publication_number": ["CAP-PATENT-1"],
            "family_key": ["CAP-FAMILY-1"],
            "title": ["501+ compound paging fixture (synthetic)"],
            "abstract": ["Synthetic fixture for ordinary paging beyond the 500-row cap."],
            "assignee": ["Demo (illustrative)"],
            "publication_date": pa.array([datetime.date(2024, 2, 2)], pa.date32()),
            "jurisdiction": ["WO"],
            "doc_type": ["application"],
        }
    )
    records_tbl = pa.table(
        {
            "document_id": ["CAP-PATENT-1"] * N_COMPOUNDS,
            "compound_id": [f"SC-CAP-{i:04d}" for i in range(N_COMPOUNDS)],
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
        '"paging-501-fixture-v1", "synthetic": true, "files": {}}'
    )
    return root


def _family_id(engine) -> str:
    with engine.connect() as conn:
        return str(
            conn.execute(
                text("SELECT id FROM patent_families WHERE family_key = 'CAP-FAMILY-1'")
            ).scalar_one()
        )


def _client(engine):
    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def _walk_pages(client, fid: str) -> list[dict]:
    """Page through the ordinary endpoint exactly as the UI does."""
    rows: list[dict] = []
    offset = 0
    while True:
        body = client.get(
            f"/api/v1/families/{fid}/compounds?offset={offset}&limit={PAGE}"
        ).json()
        assert body["offset"] == offset
        assert body["total"] == N_COMPOUNDS
        assert len(body["items"]) <= MAX_ROWS
        rows.extend(body["items"])
        offset = body["offset"] + len(body["items"])
        if offset >= body["total"]:
            return rows


class TestOrdinaryPagingBeyondCap:
    def test_fixture_structures_are_unique_and_synthetic(self, beyond_cap_engine):
        engine = beyond_cap_engine
        fid = _family_id(engine)
        # Scoped to this family: the session scratch database also holds the
        # other modules' fixtures (seeding is additive).
        with engine.connect() as conn:
            distinct = conn.execute(
                text(
                    """
                    SELECT count(DISTINCT c.inchikey)
                    FROM compounds c
                    JOIN compound_mentions m ON m.compound_id = c.id
                    JOIN patent_documents d ON d.id = m.document_id
                    WHERE d.family_id = :fid
                    """
                ),
                {"fid": fid},
            ).scalar_one()
            synthetic = conn.execute(
                text("SELECT synthetic FROM dataset_info WHERE dataset_version = 'paging-501-fixture-v1'")
            ).scalar_one()
        assert distinct == N_COMPOUNDS, "fixture must not collapse into duplicate structures"
        assert synthetic is True

    def test_all_pages_are_reachable_and_disjoint_in_a_stable_order(self, beyond_cap_engine):
        engine = beyond_cap_engine
        client = _client(engine)
        fid = _family_id(engine)

        first = client.get(f"/api/v1/families/{fid}/compounds?offset=0&limit={PAGE}").json()
        assert first["total"] == N_COMPOUNDS
        assert len(first["items"]) == PAGE

        rows = _walk_pages(client, fid)
        keys = [r["compound"]["inchikey"] for r in rows]
        assert len(keys) == N_COMPOUNDS
        assert len(set(keys)) == N_COMPOUNDS, "pages must not repeat rows or skip them"

        # A repeated walk yields the identical order (stable ORDER BY).
        again = [r["compound"]["inchikey"] for r in _walk_pages(client, fid)]
        assert again == keys

    def test_row_501_and_the_final_partial_page_are_reachable(self, beyond_cap_engine):
        engine = beyond_cap_engine
        client = _client(engine)
        fid = _family_id(engine)

        # Rows 501..600: the window the old limit-growing client could not reach.
        page6 = client.get(f"/api/v1/families/{fid}/compounds?offset=500&limit={PAGE}").json()
        assert page6["offset"] == 500
        assert len(page6["items"]) == 100
        assert len(page6["items"]) <= MAX_ROWS

        # The final partial page is one row (601 = 500 + 100 + 1).
        last = client.get(
            f"/api/v1/families/{fid}/compounds?offset={N_COMPOUNDS - 1}&limit={PAGE}"
        ).json()
        assert len(last["items"]) == 1
        assert last["total"] == N_COMPOUNDS

        beyond = client.get(f"/api/v1/families/{fid}/compounds?offset={N_COMPOUNDS}&limit={PAGE}").json()
        assert beyond["items"] == []  # past the end: no invented rows
        assert beyond["total"] == N_COMPOUNDS

        # No gap between the capped first window and the next one.
        first_window = client.get(f"/api/v1/families/{fid}/compounds?offset=0&limit={MAX_ROWS}").json()
        keys_a = {i["compound"]["inchikey"] for i in first_window["items"]}
        keys_b = {i["compound"]["inchikey"] for i in page6["items"]} | {
            i["compound"]["inchikey"] for i in last["items"]
        }
        assert keys_a.isdisjoint(keys_b)
        assert len(keys_a | keys_b) == N_COMPOUNDS

    def test_single_response_never_exceeds_the_hard_cap(self, beyond_cap_engine):
        engine = beyond_cap_engine
        client = _client(engine)
        fid = _family_id(engine)
        capped = client.get(f"/api/v1/families/{fid}/compounds?offset=0&limit=99999").json()
        assert capped["limit"] == MAX_ROWS
        assert len(capped["items"]) == MAX_ROWS
        # The next window continues from the clamped page, not from offset 0.
        rest = client.get(f"/api/v1/families/{fid}/compounds?offset=500&limit=99999").json()
        assert len(rest["items"]) == N_COMPOUNDS - MAX_ROWS
        keys = {i["compound"]["inchikey"] for i in capped["items"]}
        keys_rest = {i["compound"]["inchikey"] for i in rest["items"]}
        assert keys.isdisjoint(keys_rest)
        assert len(keys | keys_rest) == N_COMPOUNDS

    def test_structure_search_pages_beyond_500_too(self, beyond_cap_engine):
        engine = beyond_cap_engine
        client = _client(engine)
        fid = _family_id(engine)
        first = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C(=O)O", "offset": 0, "limit": PAGE},
        ).json()
        assert first["total"] == N_COMPOUNDS
        assert len(first["items"]) == PAGE
        tail = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C(=O)O", "offset": 500, "limit": PAGE},
        ).json()
        assert tail["offset"] == 500
        assert len(tail["items"]) == 100
        assert len(tail["items"]) <= MAX_ROWS
        final = client.post(
            f"/api/v1/families/{fid}/structure-search",
            json={"mode": "substructure", "smiles": "C(=O)O", "offset": N_COMPOUNDS - 1, "limit": PAGE},
        ).json()
        assert len(final["items"]) == 1
        keys_first = {i["compound"]["inchikey"] for i in first["items"]}
        keys_tail = {i["compound"]["inchikey"] for i in tail["items"]} | {
            i["compound"]["inchikey"] for i in final["items"]
        }
        assert keys_first.isdisjoint(keys_tail)
