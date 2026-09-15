"""Project version contract (product readiness PROD-03).

- dataset versions are derived server-side from the saved rows; the client
  label is ignored;
- multi-version scopes store the full list with a 'mixed' label;
- selected-compound saves keep an identity snapshot;
- later source changes are reported as drift, never silently absorbed.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from spago_core.db import run_migrations
from spago_core.seed import seed
from conftest import _family_id, compound_id_by_inchikey


@pytest.fixture(scope="module")
def proj_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)
    return pg_engine


def _client(engine):
    from fastapi.testclient import TestClient

    from spago_core.main import create_app

    app = create_app()
    app.state.engine = engine
    return TestClient(app)


def _fid(engine) -> str:
    return str(_family_id(engine))


class TestServerDerivedVersions:
    def test_client_version_label_is_ignored(self, proj_engine):
        engine = proj_engine
        client = _client(engine)
        pid = client.post("/api/v1/projects", json={"name": "Version contract 1"}).json()["id"]
        res = client.post(
            f"/api/v1/projects/{pid}/items",
            json={
                "family_id": _fid(engine),
                "compound_ids": None,
                "dataset_version": "totally-fabricated-by-client",
            },
        ).json()
        assert res["created_rows"] == 1
        # The response carries the server-derived list, not the client string.
        assert res["dataset_versions"] == [
            {"source_name": "surechembl_simplified_fixture", "dataset_version": "demo-fixture-v1"}
        ]
        detail = client.get(f"/api/v1/projects/{pid}").json()
        assert detail["items"][0]["dataset_version"] == "demo-fixture-v1"
        assert detail["items"][0]["dataset_versions"] == res["dataset_versions"]

    def test_multi_version_scope_is_mixed_with_full_list(self, proj_engine):
        engine = proj_engine
        client = _client(engine)
        fid = _fid(engine)
        # A second source version contributes one document to the same family.
        extra_doc = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, title,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:d, :f, 'VERSIONED-PATENT-2', 'Second-version doc (synthetic)',
                            'surechembl_bulk', 'surechembl-2026-09-08', now())
                    """
                ),
                {"d": extra_doc, "f": fid},
            )
        try:
            pid = client.post("/api/v1/projects", json={"name": "Version contract 2"}).json()["id"]
            res = client.post(
                f"/api/v1/projects/{pid}/items",
                json={"family_id": fid, "compound_ids": None, "dataset_version": None},
            ).json()
            labels = sorted(v["dataset_version"] for v in res["dataset_versions"])
            assert labels == ["demo-fixture-v1", "surechembl-2026-09-08"]
            detail = client.get(f"/api/v1/projects/{pid}").json()
            assert detail["items"][0]["dataset_version"] == "mixed"
            assert len(detail["items"][0]["dataset_versions"]) == 2
        finally:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM patent_documents WHERE id = :d"), {"d": extra_doc})

    def test_selection_save_keeps_identity_snapshot(self, proj_engine):
        engine = proj_engine
        client = _client(engine)
        cid = str(compound_id_by_inchikey(engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"))
        pid = client.post("/api/v1/projects", json={"name": "Snapshot project"}).json()["id"]
        client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": _fid(engine), "compound_ids": [cid], "dataset_version": "x"},
        )
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT inchikey, canonical_smiles, dataset_versions
                    FROM project_items WHERE project_id = :p
                    """
                ),
                {"p": pid},
            ).mappings().first()
        assert row["inchikey"] == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"
        assert row["canonical_smiles"]
        assert row["dataset_versions"]

    def test_source_change_is_reported_as_drift_not_absorbed(self, proj_engine):
        engine = proj_engine
        client = _client(engine)
        cid = str(compound_id_by_inchikey(engine, "RYYVLZVUVIJVGH-UHFFFAOYSA-N"))
        pid = client.post("/api/v1/projects", json={"name": "Drift project"}).json()["id"]
        client.post(
            f"/api/v1/projects/{pid}/items",
            json={"family_id": _fid(engine), "compound_ids": [cid], "dataset_version": None},
        )
        detail = client.get(f"/api/v1/projects/{pid}").json()
        item = detail["items"][0]
        assert item["source_updated"] is False
        assert item["record_missing"] is False

        # A newer dataset version replaces the compound row upstream.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE compounds SET dataset_version = 'surechembl-2026-09-08' WHERE id = :c"),
                {"c": cid},
            )
        try:
            detail2 = client.get(f"/api/v1/projects/{pid}").json()
            item2 = detail2["items"][0]
            assert item2["source_updated"] is True
            # The saved version list is unchanged: the save keeps its meaning.
            assert item2["dataset_versions"] == item["dataset_versions"]
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE compounds SET dataset_version = 'demo-fixture-v1' WHERE id = :c"),
                    {"c": cid},
                )


@pytest.fixture()
def separate_source(proj_engine):
    """Synthetic second family shares aspirin, with two scoped source versions."""
    fid, doc, second_doc = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    aspirin = compound_id_by_inchikey(proj_engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
    caffeine = compound_id_by_inchikey(proj_engine, "RYYVLZVUVIJVGH-UHFFFAOYSA-N")
    with proj_engine.begin() as conn:
        conn.execute(text("INSERT INTO patent_families "
                          "(id, family_key, source_name, dataset_version, retrieved_at) "
                          "VALUES (:id, :key, 'synthetic-version-source', 'v1', now())"),
                     {"id": fid, "key": f"VERSIONS-{fid}"})
        for did, cid, version in ((doc, aspirin, 'v1'), (second_doc, caffeine, 'v2')):
            conn.execute(text("INSERT INTO patent_documents "
                              "(id, family_id, publication_number, source_name, dataset_version, retrieved_at) "
                              "VALUES (:id, :fid, :number, 'synthetic-version-source', :version, now())"),
                         {"id": did, "fid": fid, "number": f"VERSION-{did}", "version": version})
            conn.execute(text("INSERT INTO compound_mentions "
                              "(id, compound_id, document_id, source_name, dataset_version, retrieved_at) "
                              "VALUES (:id, :cid, :doc, 'synthetic-version-source', :version, now())"),
                         {"id": uuid.uuid4(), "cid": cid, "doc": did, "version": version})
    yield fid, aspirin, caffeine, doc
    with proj_engine.begin() as conn:
        conn.execute(text("DELETE FROM patent_families WHERE id = :id"), {"id": fid})


class TestSavedScopeIntegrity:
    def test_each_item_has_own_family_scoped_versions(self, proj_engine, separate_source):
        from spago_core.services.projects import create_project, get_project, save_scope

        fid, aspirin, caffeine, _ = separate_source
        pid = create_project(proj_engine, f"Scoped versions {uuid.uuid4()}").id
        result = save_scope(proj_engine, pid, fid, [aspirin, caffeine])
        assert len(result.dataset_versions) == 2
        _, items = get_project(proj_engine, pid)
        by_id = {item.compound_id: item for item in items}
        assert by_id[aspirin].dataset_versions == [
            {"source_name": "synthetic-version-source", "dataset_version": "v1"}
        ]
        assert by_id[caffeine].dataset_version == "v2"
        # Their global identities originated in demo-fixture-v1. This is not drift.
        assert all(not item.source_updated for item in items)

    def test_mixed_family_drift_and_retry_preserve_original_versions(self, proj_engine, separate_source):
        from spago_core.services.projects import create_project, get_project, save_scope

        fid, _, _, doc = separate_source
        pid = create_project(proj_engine, f"Family drift {uuid.uuid4()}").id
        saved = save_scope(proj_engine, pid, fid, None)
        _, items = get_project(proj_engine, pid)
        assert items[0].dataset_version == "mixed"
        assert items[0].source_updated is False
        with proj_engine.begin() as conn:
            conn.execute(text("UPDATE patent_documents SET dataset_version = 'v3' WHERE id = :id"), {"id": doc})
        _, updated = get_project(proj_engine, pid)
        assert updated[0].source_updated is True
        assert updated[0].dataset_versions == saved.dataset_versions
        retry = save_scope(proj_engine, pid, fid, None)
        assert retry.created_rows == 0
        assert retry.dataset_versions == saved.dataset_versions

    def test_removed_family_keeps_both_saved_scopes_readable(self, proj_engine, separate_source):
        from spago_core.services.projects import create_project, get_project, save_scope

        fid, aspirin, _, _ = separate_source
        pid = create_project(proj_engine, f"Removed family {uuid.uuid4()}").id
        save_scope(proj_engine, pid, fid, None)
        save_scope(proj_engine, pid, fid, [aspirin])
        _, before = get_project(proj_engine, pid)
        with proj_engine.begin() as conn:
            conn.execute(text("DELETE FROM patent_families WHERE id = :id"), {"id": fid})
        summary, after = get_project(proj_engine, pid)
        assert summary.item_count == len(after) == 2
        assert all(item.record_missing for item in after)
        assert {item.family_key for item in after} == {item.family_key for item in before}
        assert next(item for item in after if item.compound_id).inchikey == "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"

    def test_removed_compound_keeps_saved_identity(self, proj_engine, separate_source):
        from spago_core.chemistry import normalize
        from spago_core.services.projects import create_project, get_project, save_scope

        fid, _, _, doc = separate_source
        cid = uuid.uuid4()
        normalized = normalize("[Xe]")
        with proj_engine.begin() as conn:
            conn.execute(text("INSERT INTO compounds (id, canonical_smiles, inchikey, dataset_version) "
                              "VALUES (:id, :smiles, :key, 'v1')"),
                         {"id": cid, "smiles": normalized.canonical_smiles, "key": normalized.inchikey})
            conn.execute(text("INSERT INTO compound_mentions "
                              "(id, compound_id, document_id, source_name, dataset_version, retrieved_at) "
                              "VALUES (:id, :cid, :doc, 'synthetic-version-source', 'v1', now())"),
                         {"id": uuid.uuid4(), "cid": cid, "doc": doc})
        pid = create_project(proj_engine, f"Removed compound {uuid.uuid4()}").id
        save_scope(proj_engine, pid, fid, [cid])
        with proj_engine.begin() as conn:
            conn.execute(text("DELETE FROM compounds WHERE id = :id"), {"id": cid})
        summary, items = get_project(proj_engine, pid)
        assert summary.item_count == 1
        assert items[0].record_missing is True
        assert items[0].compound_id == cid
        assert items[0].inchikey == normalized.inchikey
        assert items[0].canonical_smiles == normalized.canonical_smiles

    def test_mention_version_drift_is_detected_and_retry_is_idempotent(self, proj_engine, separate_source):
        from spago_core.services.projects import create_project, get_project, save_scope

        fid, aspirin, _, doc = separate_source
        pid = create_project(proj_engine, f"Mention drift {uuid.uuid4()}").id
        saved = save_scope(proj_engine, pid, fid, [aspirin, aspirin])
        assert saved.created_rows == 1
        assert saved.already_present_rows == 0
        with proj_engine.begin() as conn:
            conn.execute(text("UPDATE compound_mentions SET dataset_version = 'v3' WHERE document_id = :id"),
                         {"id": doc})
        _, items = get_project(proj_engine, pid)
        assert items[0].source_updated is True
        retry = save_scope(proj_engine, pid, fid, [aspirin])
        assert retry.created_rows == 0
        assert retry.dataset_versions == saved.dataset_versions
