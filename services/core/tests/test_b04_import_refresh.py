"""B-04: import refresh completeness and interrupted-import resume.

Two halves, one honesty rule: a refresh states what its release no longer
contains, and a resume is visible in the record instead of folklore.

1. A corpus refresh retracts the measurements its activity release no longer
   carries (source-scoped: the fixture file *is* the source), and restores rows
   a later release carries again — never deletes. Hand-added rows carry their
   own source name and are never touched by a corpus refresh.
2. A compound a release drops entirely leaves every current surface (its
   occurrences are retracted); the identity row itself stays, because identity
   is not a mapping and another source may hold the same structure.
3. Current-state reads (compound/family activity) go through the current
   views, so a retracted measurement stops rendering the moment it is retracted.
4. An interrupted import is resumed by re-running it: the completed job names
   the interrupted jobs whose package (file checksums) it re-imported, and the
   redo writes no duplicate rows.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from conftest import compound_id_by_inchikey
from test_real_source_import import _build_real_schema_package

#: Distinct activity source name for this module, so its retraction rule never
#: touches the demo fixture's measurements (`bioactivity_simplified_fixture`)
#: or hand-added rows (`user_supplement`) in the shared scratch database.
ACTIVITY_SOURCE = "b04_activity_source"


@pytest.fixture(scope="module")
def b04_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    from spago_core.db import run_migrations
    from spago_core.seed import seed

    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)  # demo dataset stays loadable
    return pg_engine


def _activity_fixture(root: Path, records: list[dict], dataset_version: str) -> Path:
    """A fixture dir the way `BioactivityFixtureAdapter` reads one: a manifest
    naming the dataset version plus one activities parquet."""
    (root / "bioactivity").mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.table(
            {
                "compound_id": pa.array([r["compound_id"] for r in records], pa.string()),
                "target_key": pa.array([r["target_key"] for r in records], pa.string()),
                "target_name": pa.array([r["target_name"] for r in records], pa.string()),
                "assay_key": pa.array([r["assay_key"] for r in records], pa.string()),
                "assay_type": pa.array([r["assay_type"] for r in records], pa.string()),
                "standard_type": pa.array([r["standard_type"] for r in records], pa.string()),
                "value": pa.array([r["value"] for r in records], pa.float64()),
                "unit": pa.array([r["unit"] for r in records], pa.string()),
                "relation": pa.array([r["relation"] for r in records], pa.string()),
            }
        ),
        root / "bioactivity" / "bioactivity_demo_fixture.parquet",
    )
    (root / "manifest.json").write_text(
        json.dumps({"dataset_version": dataset_version, "synthetic": True})
    )
    return root


def _ingest_with_activity(engine, package: Path, activity_dir: Path, monkeypatch) -> object:
    """Ingest a package with the activity fixture under this module's own source
    name. `ingest` constructs its adapter internally, so the class attribute is
    what the envelope carries; monkeypatch scopes the rename to this call's test
    and keeps the demo fixture's measurements (`bioactivity_simplified_fixture`)
    out of the retraction rule's scope in the shared scratch database."""
    from spago_core.adapters import bioactivity_fixture
    from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter
    from spago_core.seed import ingest

    monkeypatch.setattr(bioactivity_fixture.BioactivityFixtureAdapter, "source_name", ACTIVITY_SOURCE)
    result = SureChemblBulkAdapter(package).load()
    return ingest(engine, result, bioactivity_dir=activity_dir)


def _current_measurements(engine, source: str) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT m.source_record_id, m.dataset_version, m.retracted_at,
                       m.retracted_reason, m.retracted_by_dataset_version
                  FROM measurements m
                 WHERE m.source_name = :source
                 ORDER BY m.source_record_id
                """
            ),
            {"source": source},
        ).mappings().all()
    return [dict(r) for r in rows]


class TestMeasurementRetraction:
    def test_a_release_that_drops_a_measurement_retracts_it(self, b04_engine, tmp_path, monkeypatch):
        """B-04: the measurement the new activity release no longer carries stops
        counting as current, keeps its provenance, and names the version that
        dropped it. The release that still carries it is untouched."""
        from spago_core.chemistry import normalize
        from spago_core.seed import _compound_id

        engine = b04_engine
        package = _build_real_schema_package(tmp_path / "pkg", include_bad_smiles=False)
        v1 = _activity_fixture(
            tmp_path / "act-v1",
            [
                {"compound_id": "SC-500001", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
                 "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
                 "value": 120.0, "unit": "nM", "relation": "="},
                {"compound_id": "SC-500003", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
                 "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
                 "value": 340.0, "unit": "nM", "relation": "="},
            ],
            "b04-act-v1",
        )
        report = _ingest_with_activity(engine, package, v1, monkeypatch)
        assert report.retracted_measurements == 0
        ethanol_id = _compound_id(normalize("CCO").inchikey)
        aspirin_id = _compound_id(normalize("CC(=O)Oc1ccccc1C(=O)O").inchikey)
        assert len(_current_measurements(engine, ACTIVITY_SOURCE)) == 2

        # The same source, one measurement fewer, a new dataset version.
        v2 = _activity_fixture(
            tmp_path / "act-v2",
            [
                {"compound_id": "SC-500001", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
                 "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
                 "value": 125.0, "unit": "nM", "relation": "="},
            ],
            "b04-act-v2",
        )
        report2 = _ingest_with_activity(engine, package, v2, monkeypatch)
        assert report2.retracted_measurements == 1

        rows = {r["source_record_id"]: r for r in _current_measurements(engine, ACTIVITY_SOURCE)}
        assert set(rows) == {"B04-ASSAY:SC-500001", "B04-ASSAY:SC-500003"}
        dropped = rows["B04-ASSAY:SC-500003"]
        assert dropped["retracted_at"] is not None
        assert dropped["retracted_reason"] == "not in dataset_version b04-act-v2"
        assert dropped["retracted_by_dataset_version"] == "b04-act-v2"
        kept = rows["B04-ASSAY:SC-500001"]
        assert kept["retracted_at"] is None, "only the dropped measurement stops counting"

        # Current-state reads follow: the retracted measurement renders nowhere.
        from spago_core.services.bioactivity import compound_activity, family_activity

        ethanol_rows = [
            r for r in compound_activity(engine, ethanol_id) if r.source_name == ACTIVITY_SOURCE
        ]
        assert [r.dataset_version for r in ethanol_rows] == ["b04-act-v2"]
        aspirin_rows = [
            r for r in compound_activity(engine, aspirin_id) if r.source_name == ACTIVITY_SOURCE
        ]
        assert aspirin_rows == []
        with engine.connect() as conn:
            fid = conn.execute(
                text("SELECT id FROM patent_families WHERE family_key = 'SURECHEMBL-990001'")
            ).scalar_one()
        grouped = family_activity(engine, fid)
        kept_family = [
            r
            for r in grouped.get(str(ethanol_id), [])
            if r.source_name == ACTIVITY_SOURCE
        ]
        assert [r.dataset_version for r in kept_family] == ["b04-act-v2"]
        assert [
            r for r in grouped.get(str(aspirin_id), []) if r.source_name == ACTIVITY_SOURCE
        ] == []

    def test_a_release_that_carries_the_measurement_again_restores_it(self, b04_engine, tmp_path, monkeypatch):
        """Re-delivery clears the earlier retraction: identity, not a second record."""
        engine = b04_engine
        package = _build_real_schema_package(tmp_path / "pkg", include_bad_smiles=False)
        records = [
            {"compound_id": "SC-500001", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
             "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
             "value": 120.0, "unit": "nM", "relation": "="},
            {"compound_id": "SC-500003", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
             "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
             "value": 340.0, "unit": "nM", "relation": "="},
        ]
        v1 = _activity_fixture(tmp_path / "act-v1", records, "b04-act-v1")
        v2 = _activity_fixture(tmp_path / "act-v2", records[:1], "b04-act-v2")
        assert _ingest_with_activity(engine, package, v1, monkeypatch).retracted_measurements == 0
        assert _ingest_with_activity(engine, package, v2, monkeypatch).retracted_measurements == 1
        back = _ingest_with_activity(engine, package, v1, monkeypatch)
        assert back.retracted_measurements == 0
        rows = _current_measurements(engine, ACTIVITY_SOURCE)
        assert len(rows) == 2
        assert all(r["retracted_at"] is None for r in rows), (
            "re-importing the release clears the retraction"
        )

    def test_hand_added_rows_are_never_touched_by_a_corpus_refresh(self, b04_engine, tmp_path, monkeypatch):
        """The retraction rule is scoped to the activity source's own rows; a
        hand-added measurement carries a different source name and survives a
        corpus refresh untouched."""
        engine = b04_engine
        package = _build_real_schema_package(tmp_path / "pkg", include_bad_smiles=False)
        _ingest_with_activity(engine, package, _activity_fixture(tmp_path / "act-v1", [
            {"compound_id": "SC-500001", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
             "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
             "value": 120.0, "unit": "nM", "relation": "="},
        ], "b04-act-v1"), monkeypatch)
        with engine.begin() as conn:
            hand_added = conn.execute(
                text(
                    """
                    INSERT INTO measurements (id, compound_id, assay_id, standard_type, value,
                                              unit, relation, source_record_id, source_name,
                                              extraction_method, provenance_state, confidence,
                                              dataset_version, retrieved_at)
                    SELECT :mid, m.compound_id, m.assay_id, 'IC50', 42.0, 'nM', '=',
                           'b04-hand-added', 'user_supplement', 'user_entry', 'user_curated', 1.0,
                           'user-entry', now()
                      FROM measurements m
                     WHERE m.source_name = :source LIMIT 1
                    """
                ),
                {"mid": uuid.uuid4(), "source": ACTIVITY_SOURCE},
            )
            assert hand_added.rowcount == 1
        _ingest_with_activity(engine, package, _activity_fixture(tmp_path / "act-v2", [
            {"compound_id": "SC-500001", "target_key": "B04-TARGET", "target_name": "B04 target (synthetic)",
             "assay_key": "B04-ASSAY", "assay_type": "enzymatic", "standard_type": "IC50",
             "value": 130.0, "unit": "nM", "relation": "="},
        ], "b04-act-v2"), monkeypatch)
        with engine.connect() as conn:
            state = conn.execute(
                text(
                    "SELECT retracted_at FROM measurements "
                    "WHERE source_name = 'user_supplement' AND source_record_id = 'b04-hand-added'"
                )
            ).scalar_one()
        assert state is None, "a corpus refresh must not retract a hand-added row"


class TestCompoundRefreshCompleteness:
    def test_a_compound_the_release_drops_leaves_the_family_but_keeps_identity(
        self, b04_engine, tmp_path
    ):
        """Compounds are identity, not mappings: what a release drops is the
        compound's occurrences, and the family page follows them. The compounds
        row itself is never retracted — another source may hold the same
        structure, and identity is not a claim about presence."""
        from fastapi.testclient import TestClient

        from spago_core.chemistry import normalize
        from spago_core.main import create_app
        from spago_core.import_package import import_package

        engine = b04_engine
        first = _build_real_schema_package(tmp_path / "v1", include_bad_smiles=False)
        assert import_package(engine, first)["summary"]["retracted_mentions"] == 0

        app = create_app()
        app.state.engine = engine
        client = TestClient(app)
        family_id = client.get("/api/v1/patents/XX-1111111-A").json()["family"]["id"]
        assert client.get(f"/api/v1/families/{family_id}/compounds").json()["total"] == 3

        # v2 carries the same family but none of phenol's occurrences: the map
        # keeps 500001 and 500003 rows and drops 500002's only mapping row.
        second = tmp_path / "v2"
        second.mkdir()
        for name in ("patents.parquet", "compounds.parquet"):
            (second / name).write_bytes((first / name).read_bytes())
        mapping = pq.read_table(first / "patent_compound_map.parquet").to_pydict()
        keep = [
            i
            for i, compound in enumerate(mapping["compound_id"])
            if compound != 500002
        ]
        pq.write_table(
            pa.table(
                {
                    key: pa.array([values[i] for i in keep], type=pa.array(values).type)
                    for key, values in mapping.items()
                }
            ),
            second / "patent_compound_map.parquet",
        )
        manifest = json.loads((first / "manifest.json").read_text())
        manifest["dataset_version"] = "surechembl-test-release-2"
        manifest["release"] = "test-release-2"
        (second / "manifest.json").write_text(json.dumps(manifest))

        outcome = import_package(engine, second)
        assert outcome["status"] == "completed"
        assert outcome["summary"]["retracted_mentions"] == 1

        page = client.get(f"/api/v1/families/{family_id}/compounds").json()
        assert page["total"] == 2, "the dropped compound leaves the family page"
        assert all(item["compound"]["inchikey"] != normalize("c1ccccc1O").inchikey for item in page["items"])
        with engine.connect() as conn:
            identity = conn.execute(
                text("SELECT count(*) FROM compounds WHERE inchikey = :k"),
                {"k": normalize("c1ccccc1O").inchikey},
            ).scalar_one()
            retracted = conn.execute(
                text(
                    """
                    SELECT retracted_by_dataset_version FROM compound_mentions
                     WHERE source_name = 'surechembl_bulk' AND retracted_at IS NOT NULL
                """
                )
            ).scalar_one()
        assert identity == 1, "identity is not a mapping; the row stays readable"
        assert retracted == "surechembl-test-release-2"

        # Re-importing the earlier release restores the occurrences.
        back = import_package(engine, first)
        assert back["summary"]["retracted_mentions"] == 0
        assert client.get(f"/api/v1/families/{family_id}/compounds").json()["total"] == 3
        with engine.connect() as conn:
            still = conn.execute(
                text(
                    "SELECT count(*) FROM compound_mentions "
                    "WHERE source_name = 'surechembl_bulk' AND retracted_at IS NOT NULL"
                )
            ).scalar_one()
        assert still == 0
        assert compound_id_by_inchikey(engine, normalize("c1ccccc1O").inchikey)


class TestInterruptedImportResume:
    def test_rerun_resumes_an_interrupted_job_and_names_it(self, b04_engine, tmp_path):
        """D5 marked the dead job; B-04 makes the resume visible: the completed
        re-run names the interrupted jobs whose package (file checksums) it
        re-imported, and the redo writes no duplicate rows."""
        from spago_core.import_package import _file_checksums, import_package, list_jobs

        engine = b04_engine
        package = _build_real_schema_package(tmp_path / "pkg", include_bad_smiles=False)
        clean = import_package(engine, package)
        assert clean["status"] == "completed"
        mentions = clean["summary"]["mentions"]

        checksums = _file_checksums(package)
        with_unknown_package = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_jobs (id, source_name, dataset_version, synthetic,
                                             status, started_at, files)
                    VALUES (:id, 'surechembl_bulk', 'surechembl-test-release', true,
                            'running', now() - interval '1 hour', CAST(:files AS jsonb))
                    """
                ),
                {"id": with_unknown_package, "files": json.dumps(checksums)},
            )

        resumed = import_package(engine, package)
        assert resumed["status"] == "completed"
        assert resumed["summary"]["resumed_jobs"] == [str(with_unknown_package)]
        assert resumed["summary"]["mentions"] == mentions, "a resume writes no duplicate rows"

        jobs = {job["id"]: job for job in list_jobs(engine)}
        assert jobs[with_unknown_package]["status"] == "interrupted"
        assert str(with_unknown_package) not in resumed["summary"].get("warnings", [])

        # The interrupted job is now settled: another re-run claims nothing.
        again = import_package(engine, package)
        assert again["recovered_jobs"] == 0
        assert again["summary"]["resumed_jobs"] == []

    def test_an_interrupted_job_without_checksums_is_not_claimed(self, b04_engine, tmp_path):
        """A job that died before its package checksums were recorded proves
        nothing about which package it was on; the resume must not claim it."""
        from spago_core.import_package import import_package

        engine = b04_engine
        package = _build_real_schema_package(tmp_path / "pkg", include_bad_smiles=False)
        early = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_jobs (id, source_name, dataset_version, synthetic,
                                             status, started_at)
                    VALUES (:id, 'unknown', 'unknown', false, 'running', now())
                    """
                ),
                {"id": early},
            )
        outcome = import_package(engine, package)
        assert outcome["recovered_jobs"] == 1
        assert outcome["summary"]["resumed_jobs"] == []
