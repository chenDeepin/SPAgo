"""Database + API integration tests.

Run against a scratch PostgreSQL database (see conftest). Skipped with a reason
when PostgreSQL is not reachable — reported as skipped, never as passed.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core import services
from spago_core.db import applied_versions, run_migrations
from spago_core.seed import seed


@pytest.fixture(scope="module")
def seeded_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    report = seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine, report


def _app_client(engine):
    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


class TestMigrations:
    def test_apply_from_zero(self, seeded_engine):
        engine, _ = seeded_engine
        assert applied_versions(engine) >= {1, 2}

    def test_rerun_applies_nothing(self, seeded_engine, migrations_dir: Path):
        engine, _ = seeded_engine
        assert run_migrations(engine, migrations_dir) == []

    def test_missing_migrations_dir_fails_loudly(self, seeded_engine, tmp_path: Path):
        engine, _ = seeded_engine
        with pytest.raises(FileNotFoundError):
            run_migrations(engine, tmp_path / "does-not-exist")


class TestSeed:
    def test_fixture_counts(self, seeded_engine):
        engine, report = seeded_engine
        assert (report.families, report.documents) == (1, 3)
        assert report.compounds == 10  # 12 valid records deduped to 10 identities
        assert report.mentions == 12
        assert report.evidence == 12
        assert len(report.issues) == 1  # the malformed SMILES
        assert report.issues[0]["source_record_id"] == "SC-DEMO-0009"

    def test_seed_is_idempotent(self, seeded_engine, fixture_dir: Path, migrations_dir: Path):
        engine, _ = seeded_engine
        seed(engine, fixture_dir, migrations_dir)
        # Scoped to the demo dataset: the shared session database also carries
        # other modules' fixtures (paging family, real-schema packages).
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT count(*) FROM compounds WHERE dataset_version = 'demo-fixture-v1'")
            ).scalar_one() == 10
            assert conn.execute(
                text("SELECT count(*) FROM compound_mentions WHERE dataset_version = 'demo-fixture-v1'")
            ).scalar_one() == 12
            assert conn.execute(
                text("SELECT count(*) FROM evidence_records WHERE dataset_version = 'demo-fixture-v1'")
            ).scalar_one() == 12
            assert conn.execute(
                text("SELECT count(*) FROM patent_families WHERE family_key = 'DEMO-FAMILY-1'")
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT count(*) FROM ingestion_issues WHERE dataset_version = 'demo-fixture-v1'")
            ).scalar_one() == 1

    def test_issue_recorded_never_as_compound(self, seeded_engine):
        engine, _ = seeded_engine
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT issue, source_record_id, raw_smiles FROM ingestion_issues "
                    "WHERE source_record_id = 'SC-DEMO-0009'"
                )
            ).mappings().first()
        assert row is not None
        assert "failed to parse" in row["issue"]
        assert row["raw_smiles"] == "N=C(N)this-is-not-valid-smiles"


class TestServices:
    def test_find_patent_and_family(self, seeded_engine):
        engine, _ = seeded_engine
        lookup = services.find_patent(engine, "DEMO-PATENT-A")
        assert lookup.document.publication_number == "DEMO-PATENT-A"
        assert lookup.overview.family.family_key == "DEMO-FAMILY-1"
        assert len(lookup.overview.documents) == 3
        assert lookup.exact is True and lookup.matched == "DEMO-PATENT-A"

    def test_find_unknown_patent(self, seeded_engine):
        engine, _ = seeded_engine
        with pytest.raises(services.NotFoundError):
            services.find_patent(engine, "WO9999999999A1")

    def test_family_compounds_dedupe_across_documents(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        page = services.list_family_compounds(engine, overview.family.id)
        assert page.total == 10
        aspirin = next(
            r for r in page.items if r.compound.inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        )
        docs = {m.publication_number for m in aspirin.mentions}
        assert docs == {"DEMO-PATENT-A", "DEMO-PATENT-B"}
        assert {m.patent_label for m in aspirin.mentions} == {"Example 01", "Compound 12"}

    def test_document_scope_narrows_results(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        doc_a = next(d for d in overview.documents if d.publication_number == "DEMO-PATENT-A")
        page = services.list_family_compounds(engine, overview.family.id, document_id=doc_a.id)
        assert page.total == 4  # aspirin, paracetamol, caffeine, rac-ibuprofen
        for row in page.items:
            assert {m.document_id for m in row.mentions} == {doc_a.id}

    def test_mention_counts_per_document(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        assert overview.mention_counts == {
            str(next(d.id for d in overview.documents if d.publication_number == "DEMO-PATENT-A")): 5,
            str(next(d.id for d in overview.documents if d.publication_number == "DEMO-PATENT-B")): 4,
            str(next(d.id for d in overview.documents if d.publication_number == "DEMO-PATENT-C")): 3,
        }

    def test_pagination_clamps_to_hard_cap(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        offset, limit = services.clamp_page(0, 10_000, default=100, maximum=500)
        assert (offset, limit) == (0, 500)
        page = services.list_family_compounds(engine, overview.family.id, offset=2, limit=3)
        assert page.total == 10
        assert len(page.items) == 3

    def test_compound_detail_with_all_mentions(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        page = services.list_family_compounds(engine, overview.family.id)
        caffeine = next(r for r in page.items if r.compound.molecular_formula == "C8H10N4O2")
        row = services.get_compound(engine, caffeine.compound.id)
        assert len(row.mentions) == 2
        assert {m.patent_label for m in row.mentions} == {"Example 03", "Compound A"}

    def test_evidence_for_compound(self, seeded_engine):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        page = services.list_family_compounds(engine, overview.family.id)
        caffeine = next(r for r in page.items if r.compound.molecular_formula == "C8H10N4O2")
        evidence = services.list_compound_evidence(engine, caffeine.compound.id)
        assert len(evidence) == 2
        assert {e.source_type.value for e in evidence} == {"description", "abstract"}
        assert all(e.provenance_state.value == "machine_extracted" for e in evidence)
        assert all(e.source_url is None for e in evidence)


def _family_id(engine) -> uuid.UUID:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT id FROM patent_families WHERE family_key = 'DEMO-FAMILY-1'")
        ).scalar_one()


class TestApi:
    def test_healthz(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        res = client.get("/healthz")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["database"] == "up"
        assert body["chemistry"] == "ok"
        assert body["rdkit_cartridge"] == "installed"
        assert body["dataset_version"] == "demo-fixture-v1"
        assert body["ingestion_issues"] == 1

    def test_patent_lookup(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        res = client.get("/api/v1/patents/DEMO-PATENT-A")
        assert res.status_code == 200
        body = res.json()
        assert body["document"]["publication_number"] == "DEMO-PATENT-A"
        assert body["family"]["family_key"] == "DEMO-FAMILY-1"
        assert len(body["documents"]) == 3

    def test_patent_not_found_is_404(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        res = client.get("/api/v1/patents/WO9999999999A1")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_compounds_endpoint_pagination(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        fid = _family_id(engine)
        res = client.get(f"/api/v1/families/{fid}/compounds?limit=2&offset=0")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 10
        assert len(body["items"]) == 2

        res_all = client.get(f"/api/v1/families/{fid}/compounds?limit=9999")
        assert res_all.json()["limit"] == 500  # hard cap enforced server-side

    def test_compounds_document_scope_param(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        fid = _family_id(engine)
        overview = services.get_family_overview(engine, fid)
        doc_a = next(d for d in overview.documents if d.publication_number == "DEMO-PATENT-A")
        res = client.get(f"/api/v1/families/{fid}/compounds?document_id={doc_a.id}")
        assert res.json()["total"] == 4

    def test_depiction_endpoint_serves_cached_svg(self, seeded_engine, tmp_path: Path, monkeypatch):
        engine, _ = seeded_engine
        overview = services.get_family_overview(engine, _family_id(engine))
        page = services.list_family_compounds(engine, overview.family.id)
        cid = page.items[0].compound.id

        monkeypatch.setenv("SPAGO_DEPICTION_CACHE_DIR", str(tmp_path / "depictions"))
        from spago_core.config import get_settings

        get_settings.cache_clear()
        client = _app_client(engine)
        res = client.get(f"/api/v1/compounds/{cid}/depiction")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("image/svg+xml")
        assert "Cache-Control" in res.headers
        assert res.text.lstrip().startswith("<?xml")
        get_settings.cache_clear()
        monkeypatch.delenv("SPAGO_DEPICTION_CACHE_DIR")

    def test_evidence_endpoint(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        overview = services.get_family_overview(engine, _family_id(engine))
        page = services.list_family_compounds(engine, overview.family.id)
        caffeine = next(r for r in page.items if r.compound.molecular_formula == "C8H10N4O2")
        res = client.get(f"/api/v1/compounds/{caffeine.compound.id}/evidence")
        assert res.status_code == 200
        items = res.json()
        assert len(items) == 2
        assert {i["source_type"] for i in items} == {"description", "abstract"}
        assert all(i["source_url"] is None for i in items)

    def test_bulk_counts_endpoint(self, seeded_engine, fixture_dir: Path, monkeypatch):
        engine, _ = seeded_engine
        monkeypatch.setenv("SPAGO_FIXTURE_DIR", str(fixture_dir))
        from spago_core.config import get_settings

        get_settings.cache_clear()
        client = _app_client(engine)
        res = client.get("/api/v1/bulk/compound-counts")
        assert res.status_code == 200
        body = res.json()
        assert body["dataset_version"] == "demo-fixture-v1"
        counts = {i["document_id"]: i["record_count"] for i in body["items"]}
        assert counts == {"DEMO-PATENT-A": 5, "DEMO-PATENT-B": 5, "DEMO-PATENT-C": 3}
        get_settings.cache_clear()
        monkeypatch.delenv("SPAGO_FIXTURE_DIR")

    def test_datasets_info_exposes_issues(self, seeded_engine):
        engine, _ = seeded_engine
        client = _app_client(engine)
        res = client.get("/api/v1/datasets/info")
        assert res.status_code == 200
        body = res.json()
        assert body["synthetic"] is True
        assert body["dataset_version"] == "demo-fixture-v1"
        assert len(body["ingestion_issues"]) == 1
