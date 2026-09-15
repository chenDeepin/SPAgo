"""Upgrade existing saved scopes without replacing their historical meaning."""
from __future__ import annotations

import os
import json
import uuid

import pytest
from sqlalchemy import create_engine, text

from conftest import _base_url, _family_id, compound_id_by_inchikey
from test_migration_0006_upgrade import _dir_up_to, MIGRATIONS_DIR, REPO_ROOT
from spago_core.db import run_migrations
from spago_core.seed import seed
from spago_core.services.projects import get_project


@pytest.fixture()
def snapshot_upgrade_engine():
    database = "spago_test_upgrade_0007"
    admin = create_engine(_base_url() + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {database}"))
    except Exception as exc:
        admin.dispose()
        if os.environ.get("SPAGO_REQUIRE_TEST_DATABASE") == "1":
            raise RuntimeError("Required snapshot upgrade database could not be prepared") from exc
        pytest.skip(f"PostgreSQL not reachable; snapshot upgrade skipped: {exc}")
    engine = create_engine(_base_url() + f"/{database}")
    try:
        su = create_engine(_base_url().replace("://spago:spago@", "://postgres:spago@") + f"/{database}",
                           isolation_level="AUTOCOMMIT")
        try:
            with su.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS rdkit"))
        finally:
            su.dispose()
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)"))
        admin.dispose()


def test_upgrade_preserves_legacy_and_saved_snapshots(snapshot_upgrade_engine):
    engine = snapshot_upgrade_engine
    previous = _dir_up_to(7)
    seed(engine, REPO_ROOT / "data" / "fixtures", previous)
    fid = _family_id(engine)
    cid = compound_id_by_inchikey(engine, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N")
    pid, selected, family = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO projects (id, name) VALUES (:id, 'snapshot upgrade')"), {"id": pid})
        # An old family reference has only its historical version label. A v7
        # selected item has identity snapshots that may differ from today's row.
        conn.execute(text("INSERT INTO project_items (id, project_id, family_id, dataset_version) "
                          "VALUES (:id, :pid, :fid, 'older-source-v0')"),
                     {"id": family, "pid": pid, "fid": fid})
        conn.execute(text("INSERT INTO project_items "
                          "(id, project_id, family_id, compound_id, inchikey, canonical_smiles, dataset_version, dataset_versions) "
                          "VALUES (:id, :pid, :fid, :cid, 'historical-identity', 'C', 'older-source-v0', "
                          "CAST(:versions AS jsonb))"),
                     {"id": selected, "pid": pid, "fid": fid, "cid": cid,
                      "versions": json.dumps([{"source_name": "historical-source", "dataset_version": "older-source-v0"}])})
    assert 8 in run_migrations(engine, MIGRATIONS_DIR)
    _, items = get_project(engine, pid)
    by_id = {item.id: item for item in items}
    assert by_id[family].dataset_versions == []
    assert by_id[family].dataset_version == "older-source-v0"
    assert by_id[family].source_updated is True
    assert by_id[selected].inchikey == "historical-identity"
    assert by_id[selected].canonical_smiles == "C"
    assert by_id[selected].dataset_versions == [
        {"source_name": "historical-source", "dataset_version": "older-source-v0"}
    ]
    assert by_id[selected].source_updated is True
    assert all(item.family_key == "DEMO-FAMILY-1" for item in items)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM patent_families WHERE id = :id"), {"id": fid})
        conn.execute(text("DELETE FROM compounds WHERE id = :id"), {"id": cid})
    summary, missing = get_project(engine, pid)
    assert summary.item_count == 2
    assert all(item.record_missing for item in missing)
    assert next(item for item in missing if item.id == selected).inchikey == "historical-identity"
    # Project deletion still owns and removes its saved items.
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM projects WHERE id = :id"), {"id": pid})
        assert conn.execute(text("SELECT count(*) FROM project_items WHERE project_id = :id"),
                            {"id": pid}).scalar_one() == 0
