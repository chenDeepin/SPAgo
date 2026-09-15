"""M1 integration tests: project save (idempotent) + CSV/SDF export provenance."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core import services
from spago_core.db import run_migrations
from spago_core.seed import seed
from conftest import compound_id_by_inchikey


@pytest.fixture(scope="module")
def m1_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


def _compound_id(engine, inchikey: str) -> str:
    return str(compound_id_by_inchikey(engine, inchikey))


def _client(engine):
    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def _fid(engine) -> str:
    from conftest import _family_id

    return str(_family_id(engine))


class TestProjects:
    def test_create_list_get(self, m1_engine):
        engine = m1_engine
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = engine
        client = TestClient(app)
        created = client.post("/api/v1/projects", json={"name": "M1 test project"}).json()
        assert created["item_count"] == 0

        listed = client.get("/api/v1/projects").json()
        assert any(p["name"] == "M1 test project" for p in listed)

        detail = client.get(f"/api/v1/projects/{created['id']}").json()
        assert detail["items"] == []

    def test_save_family_scope_is_idempotent(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        pid = client.post("/api/v1/projects", json={"name": "Family scope project"}).json()["id"]
        fid = _fid(engine)

        first = client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": fid, "compound_ids": None, "dataset_version": "demo-fixture-v1"},
        ).json()
        assert first["created_rows"] == 1 and first["already_present_rows"] == 0 and first["scope_family"] is True
        # Server-derived version list travels with the save (PROD-03).
        assert first["dataset_versions"] == [
            {"source_name": "surechembl_simplified_fixture", "dataset_version": "demo-fixture-v1"}
        ]

        again = client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": fid, "compound_ids": None, "dataset_version": "demo-fixture-v1"},
        ).json()
        assert again["created_rows"] == 0 and again["already_present_rows"] == 1

        detail = client.get(f"/api/v1/projects/{pid}").json()
        assert detail["item_count"] == 1
        assert detail["items"][0]["compound_id"] is None
        assert detail["items"][0]["family_key"] == "DEMO-FAMILY-1"

    def test_save_selection_then_merge(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        pid = client.post("/api/v1/projects", json={"name": "Selection project"}).json()["id"]
        fid = _fid(engine)
        asp = _compound_id(engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
        caf = _compound_id(engine, "RYYVLZVUVIJVGH-UHFFFAOYSA-N")

        r1 = client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": fid, "compound_ids": [str(asp)], "dataset_version": "demo-fixture-v1"},
        ).json()
        assert r1["created_rows"] == 1

        # Re-save the same compound + add another: one duplicate, one new.
        r2 = client.post(
            f"/api/v1/projects/{pid}/items",
            json={
                "family_id": fid,
                "compound_ids": [str(asp), str(caf)],
                "dataset_version": "demo-fixture-v1",
            },
        ).json()
        assert r2["created_rows"] == 1 and r2["already_present_rows"] == 1

        detail = client.get(f"/api/v1/projects/{pid}").json()
        assert detail["item_count"] == 2

    def test_save_rejects_foreign_compound(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        pid = client.post("/api/v1/projects", json={"name": "Foreign project"}).json()["id"]
        res = client.post(
            f"/api/v1/projects/{pid}/items",
            json={
                "family_id": _fid(engine),
                "compound_ids": [str(uuid.uuid4())],
                "dataset_version": "demo-fixture-v1",
            },
        )
        assert res.status_code == 404

    def test_remove_item(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        pid = client.post("/api/v1/projects", json={"name": "Remove project"}).json()["id"]
        fid = _fid(engine)
        asp = _compound_id(engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
        client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": fid, "compound_ids": [str(asp)], "dataset_version": "demo-fixture-v1"},
        )
        detail = client.get(f"/api/v1/projects/{pid}").json()
        item_id = detail["items"][0]["id"]
        assert client.delete(f"/api/v1/projects/{pid}/items/{item_id}").status_code == 204
        assert client.get(f"/api/v1/projects/{pid}").json()["item_count"] == 0
        assert client.delete(f"/api/v1/projects/{pid}/items/{item_id}").status_code == 404


class TestExport:
    def test_csv_family_scope_has_provenance(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        fid = _fid(engine)
        res = client.post("/api/v1/export", json={"family_id": str(fid), "format": "csv"})
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/csv")
        lines = res.text.strip().splitlines()
        assert len(lines) == 11  # header + 10 compounds
        header = lines[0].split(",")
        assert {"inchikey", "canonical_smiles", "patent_numbers", "evidence_records"} <= set(header)

        # Aspirin row: two patents, two evidence records.
        import csv as csvmod

        rows = list(csvmod.DictReader(io.StringIO(res.text)))
        asp = next(r for r in rows if r["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
        assert asp["patent_numbers"] == "DEMO-PATENT-A|DEMO-PATENT-B"
        assert len(asp["evidence_records"].split("|")) == 2
        assert "machine_extracted" in asp["provenance_states"]
        assert asp["dataset_version"] == "demo-fixture-v1"

    def test_csv_document_scope_narrows(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        fid = _fid(engine)
        overview = services.get_family_overview(engine, fid)
        doc_a = next(d for d in overview.documents if d.publication_number == "DEMO-PATENT-A")
        res = client.post(
            "/api/v1/export",
            json={"family_id": str(fid), "document_id": str(doc_a.id), "format": "csv"},
        )
        rows = res.text.strip().splitlines()
        assert len(rows) == 5  # header + 4 compounds

    def test_selection_scope_wins(self, m1_engine):
        engine = m1_engine
        client = _client(engine)
        fid = _fid(engine)
        asp = _compound_id(engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
        res = client.post(
            "/api/v1/export",
            json={"family_id": str(fid), "compound_ids": [str(asp)], "format": "csv"},
        )
        assert len(res.text.strip().splitlines()) == 2

    def test_sdf_roundtrips_with_properties(self, m1_engine):
        from rdkit import Chem

        engine = m1_engine
        client = _client(engine)
        fid = _fid(engine)
        res = client.post("/api/v1/export", json={"family_id": str(fid), "format": "sdf"})
        assert res.headers["content-type"] == "chemical/x-mdl-sdfile"

        supplier = Chem.SDMolSupplier()
        supplier.SetData(res.text)
        mols = [m for m in supplier]
        assert len(mols) == 10
        asp = next(m for m in mols if m.GetProp("inchikey") == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
        assert asp.HasProp("patent_numbers")
        assert "DEMO-PATENT-A" in asp.GetProp("patent_numbers")
        assert asp.HasProp("evidence_records") and asp.HasProp("dataset_version")
        # Real chemistry roundtrip: the molblock parses back to the same identity.
        assert Chem.MolToInchiKey(asp) == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

    def test_export_requires_scope(self, m1_engine):
        client = _client(m1_engine)
        res = client.post("/api/v1/export", json={"format": "csv"})
        assert res.status_code == 422

    def test_unknown_selection_is_rejected(self, m1_engine):
        """PROD-02 scope contract: ids outside the requested family/document
        are rejected with 422 and a count (previously a 404 after loading)."""
        client = _client(m1_engine)
        res = client.post(
            "/api/v1/export",
            json={
                "family_id": str(_fid(m1_engine)),
                "compound_ids": [str(uuid.uuid4())],
                "format": "csv",
            },
        )
        assert res.status_code == 422
        assert "outside the requested" in res.json()["detail"]
