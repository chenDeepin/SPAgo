"""Real-source import path (product readiness PROD-01).

Builds a tiny package in the *real* SureChEMBL bulk schema (synthetic content,
clearly marked in the manifest note) and verifies the whole local path:
adapter mapping, durable import job, idempotent ingest, provenance in the
database, and honest failure recording.

The remote extraction itself (scripts/extract_surechembl.py against the
EMBL-EBI FTP) is exercised separately against the real release; these tests
never touch the network.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from sqlalchemy import text

from spago_core.db import run_migrations
from spago_core.seed import ingest, seed
from conftest import _family_id

REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_real_schema_package(root: Path, *, include_bad_smiles: bool = True) -> Path:
    """A package with the official bulk columns. Content is synthetic; the
    manifest and synthetic flag say so; this exercises schema handling,
    not live-source chemistry claims."""
    root.mkdir(parents=True, exist_ok=True)
    patents = pa.table(
        {
            "id": pa.array([7001, 7002], pa.int64()),
            "patent_number": ["XX-1111111-A", "XX-1111111-B"],
            "country": ["XX", "XX"],
            "publication_date": pa.array(
                [__import__("datetime").date(2001, 1, 4), __import__("datetime").date(2003, 6, 5)],
                pa.date32(),
            ),
            "family_id": pa.array([990001, 990001], pa.int64()),
            "cpc": pa.array([["A61K31/00"], ["A61K31/00"]], pa.list_(pa.string())),
            "ipcr": pa.array([[], []], pa.list_(pa.string())),
            "ipc": pa.array([[], []], pa.list_(pa.string())),
            "ecla": pa.array([[], []], pa.list_(pa.string())),
            "assignee": pa.array([["Example Pharma AG"], ["Example Pharma AG"]], pa.list_(pa.string())),
            "title": ["Real-schema fixture family (synthetic)", "Grant of the same family (synthetic)"],
        }
    )
    # field ids per the official fields.parquet: 1 desc, 2 clms, 4 ttl.
    mapping = pa.table(
        {
            "patent_id": pa.array([7001, 7001, 7001, 7002, 7002], pa.int64()),
            "compound_id": pa.array([500001, 500001, 500002, 500001, 500003], pa.int64()),
            "field_id": pa.array([1, 2, 1, 4, 1], pa.int64()),
        }
    )
    smiles_rows = ["CCO", "c1ccccc1O", "CC(=O)Oc1ccccc1C(=O)O"]
    if include_bad_smiles:
        smiles_rows[1] = ""  # missing structure in the source package
    compounds = pa.table(
        {
            "id": pa.array([500001, 500002, 500003], pa.int64()),
            "smiles": smiles_rows,
            "inchi": ["InChI=1S/C2H6O/c1-2-3/h3H,2H2,1H3", None, "InChI=1S/C9H8O4/c1-6(10)13-8-5-3-2-4-7(8)9(11)12/h2-5H,1H3,(H,11,12)"],
            "inchi_key": ["LFQSCWFLJHTTHZ-UHFFFAOYSA-N", None, "BSYNRYMUTXBXSQ-UHFFFAOYSA-N"],
            "mol_weight": pa.array([46.07, None, 180.16], pa.float64()),
        }
    )
    pq.write_table(patents, root / "patents.parquet")
    pq.write_table(mapping, root / "patent_compound_map.parquet")
    pq.write_table(compounds, root / "compounds.parquet")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "adapter": "surechembl_bulk",
                "release": "test-release",
                "dataset_version": "surechembl-test-release",
                "synthetic": True,  # test package content is synthetic
                "retrieved_at": "2026-09-08T00:00:00+00:00",
                "requested_patents": ["XX-1111111-A"],
                "family_ids": [990001],
                "note": "Synthetic test package in the real SureChEMBL bulk schema.",
            }
        )
    )
    return root


@pytest.fixture(scope="module")
def real_source_engine(pg_engine, fixture_dir: Path, migrations_dir: Path):
    run_migrations(pg_engine, migrations_dir)
    seed(pg_engine, fixture_dir, migrations_dir)  # demo dataset stays loadable
    return pg_engine


@pytest.fixture()
def real_package(tmp_path: Path) -> Path:
    return _build_real_schema_package(tmp_path / "pkg")


class TestBulkAdapter:
    def test_quoted_directory_and_original_retrieval_time(self, tmp_path):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        package = _build_real_schema_package(tmp_path / "chemist's extract")
        result = SureChemblBulkAdapter(package).load()
        assert result.envelope.retrieved_at.isoformat() == "2026-09-08T00:00:00+00:00"
        assert all(e.retrieved_at == result.envelope.retrieved_at for e in result.evidence)

    @pytest.mark.parametrize("key,value", [("synthetic", "false"), ("dataset_version", ""), ("retrieved_at", "2026-09-08")])
    def test_rejects_ambiguous_provenance(self, real_package, key, value):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        manifest_path = real_package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest[key] = value
        manifest_path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError):
            SureChemblBulkAdapter(real_package)

    def test_unknown_field_is_not_description(self, real_package):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        path = real_package / "patent_compound_map.parquet"
        rows = pq.read_table(path).to_pydict()
        rows["field_id"][0] = 99
        pq.write_table(pa.table(rows), path)
        result = SureChemblBulkAdapter(real_package).load()
        unknown = next(e for e in result.evidence if "unknown field 99" in e.section)
        assert unknown.source_type.value == "external_database"
        assert any("Unknown patent field id 99" in w for w in result.envelope.warnings)

    def test_source_identity_difference_is_recorded_without_replacing_smiles(self, real_package):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        path = real_package / "compounds.parquet"
        rows = pq.read_table(path).to_pydict()
        rows["inchi_key"][0] = "SOURCE-KEY"
        pq.write_table(pa.table(rows), path)
        result = SureChemblBulkAdapter(real_package).load()
        assert any("SOURCE-KEY" in w and "LFQSCWFLJHTTHZ" in w for w in result.envelope.warnings)
        assert next(m for m in result.mentions if m.source_record_id == "SC-500001").raw_smiles == "CCO"

    def test_rejects_unbounded_package_before_materializing(self, real_package, monkeypatch):
        from spago_core.adapters import surechembl_bulk

        monkeypatch.setattr(surechembl_bulk, "MAX_PACKAGE_ROWS", 3)
        with pytest.raises(ValueError, match="family-extract limit"):
            surechembl_bulk.SureChemblBulkAdapter(real_package).load()

    def test_conflicting_compound_ids_are_rejected(self, real_package):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        path = real_package / "compounds.parquet"
        rows = pq.read_table(path).to_pydict()
        rows["id"][1] = rows["id"][0]
        pq.write_table(pa.table(rows), path)
        with pytest.raises(ValueError, match="duplicate compound identifiers"):
            SureChemblBulkAdapter(real_package).load()

    def test_maps_real_schema_to_domain(self, real_package):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        result = SureChemblBulkAdapter(real_package).load()
        assert result.envelope.source_name == "surechembl_bulk"
        assert result.envelope.dataset_version == "surechembl-test-release"
        assert len(result.families) == 1
        assert result.families[0].family_key == "SURECHEMBL-990001"
        assert [d.publication_number for d in result.documents] == [
            "XX-1111111-A",
            "XX-1111111-B",
        ]
        # doc_type from the kind code
        assert [d.doc_type for d in result.documents] == ["application", "grant"]
        # Mentions are (compound, document, field) occurrences, deduplicated.
        assert len(result.mentions) == 5
        assert len({m.mention_id for m in result.mentions}) == 5
        by_label = {m.source_record_id: m for m in result.mentions}
        assert set(by_label) == {"SC-500001", "SC-500002", "SC-500003"}
        # Evidence: field id → source type, honest excerpt, espacenet link.
        ev = {e.compound_local_id: e for e in result.evidence}
        assert ev["SC-500001"].source_url.startswith(
            "https://worldwide.espacenet.com/patent/search?q=pn%3DXX1111111"
        )
        assert "not part of the bulk extract" in ev["SC-500001"].raw_excerpt
        title_evidence = [e for e in result.evidence if e.source_type.value == "title"]
        assert title_evidence, "field_id 4 maps to title evidence"
        # Missing structures are recorded as issues, never invented.
        assert any(i.issue == "missing_smiles_in_source_package" for i in result.issues)

    def test_missing_files_are_a_clear_error(self, tmp_path):
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        with pytest.raises(FileNotFoundError, match="extract_surechembl"):
            SureChemblBulkAdapter(tmp_path / "empty")


class TestImportCommand:
    @pytest.mark.parametrize("content", ["{bad json", "[]", '{"adapter": []}'])
    def test_malformed_manifest_records_failed_job(self, real_source_engine, real_package, content):
        from spago_core.import_package import import_package

        (real_package / "manifest.json").write_text(content)
        with pytest.raises(ValueError):
            import_package(real_source_engine, real_package)
        with real_source_engine.connect() as conn:
            job = conn.execute(text("SELECT status, started_at, finished_at FROM import_jobs ORDER BY created_at DESC LIMIT 1")).mappings().one()
        assert job["status"] == "failed"
        assert job["started_at"] is not None and job["finished_at"] is not None

    def test_checksum_mismatch_records_failed_job(self, real_source_engine, real_package):
        from spago_core.import_package import import_package

        path = real_package / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["files"] = {"compounds.parquet": {"sha256": "wrong", "bytes": 1}}
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="checksum mismatch"):
            import_package(real_source_engine, real_package)

    def test_import_records_job_and_is_idempotent(self, real_source_engine, real_package):
        from spago_core.import_package import import_package

        engine = real_source_engine
        outcome = import_package(engine, real_package)
        assert outcome["status"] == "completed"
        summary = outcome["summary"]
        assert summary["families"] == 1 and summary["documents"] == 2
        # 2 valid compounds (one structure is missing in the package).
        assert summary["compounds"] == 2
        assert summary["mentions"] == 4  # 5 map rows minus the missing-structure one
        assert summary["issues"] >= 1

        with engine.connect() as conn:
            job = conn.execute(
                text("SELECT status, files, summary FROM import_jobs WHERE id = :i"),
                {"i": outcome["job_id"]},
            ).mappings().first()
        assert job is not None and job["status"] == "completed"
        files = job["files"]
        assert set(files) == {
            "compounds.parquet",
            "patent_compound_map.parquet",
            "patents.parquet",
            "manifest.json",
        }
        assert all("sha256" in f for f in files.values())

        # Re-import: idempotent, still one completed job per run, no dup rows.
        again = import_package(engine, real_package)
        assert again["status"] == "completed"
        assert again["summary"]["mentions"] == summary["mentions"]
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT count(*) FROM compound_mentions m
                    JOIN patent_documents d ON d.id = m.document_id
                    JOIN patent_families f ON f.id = d.family_id
                    WHERE f.family_key = 'SURECHEMBL-990001'
                    """
                )
            ).scalar_one()
        assert rows == summary["mentions"]

    def test_import_serves_real_schema_data(self, real_source_engine, real_package):
        from spago_core.import_package import import_package

        engine = real_source_engine
        import_package(engine, real_package)
        from fastapi.testclient import TestClient

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = engine
        client = TestClient(app)

        patent = client.get("/api/v1/patents/XX-1111111-A")
        assert patent.status_code == 200
        body = patent.json()
        assert body["family"]["family_key"] == "SURECHEMBL-990001"
        assert len(body["documents"]) == 2  # family-wide: application + grant
        fid = body["family"]["id"]
        page = client.get(f"/api/v1/families/{fid}/compounds").json()
        assert page["total"] == 2

        # Evidence for a real-schema compound: provenance + link, page honestly null.
        # (A compound shared with the demo dataset carries both sources' evidence;
        # the bulk-sourced rows are the ones under test.)
        cid = page["items"][0]["compound"]["id"]
        evidence = client.get(f"/api/v1/compounds/{cid}/evidence").json()
        assert evidence
        bulk_rows = [e for e in evidence if e["extraction_method"] == "surechembl_bulk_import"]
        assert bulk_rows, "the imported source must contribute evidence"
        assert all(e["page"] is None for e in bulk_rows)
        assert all(e["source_url"] for e in bulk_rows)
        assert all(e["provenance_state"] == "machine_extracted" for e in bulk_rows)

        # Datasets inventory lists the imported source alongside the demo data.
        info = client.get("/api/v1/datasets/info").json()
        names = {d["source_name"] for d in info["datasets"]}
        assert {"surechembl_bulk", "surechembl_simplified_fixture"} <= names

    def test_failed_import_records_the_error(self, real_source_engine, tmp_path):
        from spago_core.import_package import import_package

        pkg = _build_real_schema_package(tmp_path / "bad")
        manifest = json.loads((pkg / "manifest.json").read_text())
        manifest["adapter"] = "not_a_source"
        (pkg / "manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="refusing to guess"):
            import_package(real_source_engine, pkg)
        with real_source_engine.connect() as conn:
            failed = conn.execute(
                text("SELECT status, error FROM import_jobs WHERE status = 'failed'")
            ).mappings().all()
        assert failed and "refusing to guess" in failed[-1]["error"]

    def test_a_release_that_drops_a_row_retracts_it(self, real_source_engine, tmp_path):
        """D4: a refresh is a statement about its source's current content.

        The second release of the same source does not carry one mapping row, so
        that row is retracted with the version that dropped it — not deleted, not
        left current — and the dropped row's evidence goes with it.
        """
        from spago_core.import_package import import_package

        engine = real_source_engine
        first = _build_real_schema_package(tmp_path / "v1")
        summary = import_package(engine, first)["summary"]
        assert summary["retracted_mentions"] == 0
        assert summary["retracted_evidence"] == 0
        with engine.connect() as conn:
            baseline = conn.execute(
                text(
                    "SELECT count(*) FROM current_compound_mentions "
                    "WHERE source_name = 'surechembl_bulk'"
                )
            ).scalar_one()

        # The same family, one compound mention fewer, a new dataset version.
        second = tmp_path / "v2"
        second.mkdir()
        for name in ("patents.parquet", "compounds.parquet"):
            (second / name).write_bytes((first / name).read_bytes())
        mapping = pq.read_table(first / "patent_compound_map.parquet").to_pydict()
        dropped = {
            (patent, compound, field)
            for patent, compound, field in zip(
                mapping["patent_id"], mapping["compound_id"], mapping["field_id"]
            )
        }
        dropped_row = (7002, 500003, 1)
        assert dropped_row in dropped
        keep = [i for i, row in enumerate(zip(mapping["patent_id"], mapping["compound_id"], mapping["field_id"])) if row != dropped_row]
        pq.write_table(
            pa.table({key: pa.array([values[i] for i in keep], type=pa.array(values).type) for key, values in mapping.items()}),
            second / "patent_compound_map.parquet",
        )
        manifest = json.loads((first / "manifest.json").read_text())
        manifest["dataset_version"] = "surechembl-test-release-2"
        manifest["release"] = "test-release-2"
        (second / "manifest.json").write_text(json.dumps(manifest))

        again = import_package(engine, second)
        assert again["status"] == "completed"
        assert again["summary"]["retracted_mentions"] == 1
        assert again["summary"]["retracted_evidence"] == 1

        with engine.connect() as conn:
            retracted = conn.execute(
                text(
                    """
                    SELECT m.patent_label, m.dataset_version, m.retracted_reason,
                           m.retracted_by_dataset_version
                      FROM compound_mentions m
                     WHERE m.source_name = 'surechembl_bulk' AND m.retracted_at IS NOT NULL
                    """
                )
            ).mappings().all()
            assert len(retracted) == 1
            assert retracted[0]["retracted_by_dataset_version"] == "surechembl-test-release-2"
            assert "not in dataset_version surechembl-test-release-2" == retracted[0]["retracted_reason"]
            # The rows the release still carries are current, not collateral.
            current = conn.execute(
                text(
                    """
                    SELECT count(*) FROM current_compound_mentions m
                     WHERE m.source_name = 'surechembl_bulk'
                    """
                )
            ).scalar_one()
            assert current == baseline - 1, "only the dropped mention stops counting"

        # A later release that carries the row again makes it current (identity, not
        # a second record) — the same rule the hand-added rows follow.
        back = import_package(engine, first)
        assert back["status"] == "completed"
        assert back["summary"]["retracted_mentions"] == 0
        with engine.connect() as conn:
            still_retracted = conn.execute(
                text(
                    """
                    SELECT count(*) FROM compound_mentions
                     WHERE source_name = 'surechembl_bulk' AND retracted_at IS NOT NULL
                    """
                )
            ).scalar_one()
        assert still_retracted == 0, "re-importing a release clears the earlier retraction"

    def test_a_killed_import_is_recovered_as_interrupted(self, real_source_engine, real_package):
        """D5: a `running` row whose process died must not read as in progress."""
        from spago_core.import_package import import_package, list_jobs

        engine = real_source_engine
        stale_id = uuid.uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO import_jobs (id, source_name, dataset_version, synthetic, status,
                                             started_at)
                    VALUES (:id, 'surechembl_bulk', 'surechembl-test-release', true, 'running',
                            now() - interval '2 hours')
                    """
                ),
                {"id": stale_id},
            )

        outcome = import_package(engine, real_package)
        assert outcome["recovered_jobs"] == 1

        jobs = {job["id"]: job for job in list_jobs(engine)}
        stale = jobs[stale_id]
        assert stale["status"] == "interrupted"
        assert stale["finished_at"] is not None
        assert "stopped before finishing" in stale["error"]
        assert str(uuid.UUID(outcome["job_id"])) in stale["error"]
        # The run that recovered it is untouched.
        assert jobs[uuid.UUID(outcome["job_id"])]["status"] == "completed"

        # A second import finds nothing to recover: the state is not re-written.
        assert import_package(engine, real_package)["recovered_jobs"] == 0

    def test_seed_mode_none_leaves_real_data_unmixed(self, real_source_engine, real_package, monkeypatch):
        """SPAGO_SEED_MODE only gates the *demo* fixture; imported packages are
        the explicit real-data path and re-running them stays idempotent."""
        from spago_core.config import get_settings
        from spago_core.import_package import import_package

        get_settings.cache_clear()
        monkeypatch.setenv("SPAGO_SEED_MODE", "none")
        try:
            settings = get_settings()
            assert settings.seed_mode == "none"
        finally:
            get_settings.cache_clear()
            monkeypatch.delenv("SPAGO_SEED_MODE", raising=False)
        engine = real_source_engine
        out = import_package(engine, real_package)
        assert out["status"] == "completed"
        with engine.connect() as conn:
            demo = conn.execute(
                text(
                    "SELECT count(*) FROM dataset_info "
                    "WHERE source_name = 'surechembl_simplified_fixture' "
                    "AND dataset_version = 'demo-fixture-v1'"
                )
            ).scalar_one()
            real = conn.execute(
                text(
                    "SELECT count(*) FROM dataset_info "
                    "WHERE source_name = 'surechembl_bulk' "
                    "AND dataset_version = 'surechembl-test-release'"
                )
            ).scalar_one()
        assert demo == 1  # pre-seeded by the fixture; the mode gate is startup-only
        assert real == 1


class TestExtractor:
    @pytest.fixture()
    def extractor(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("extract_surechembl_test", REPO_ROOT / "scripts/extract_surechembl.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_httpfs_reuses_installed_extension_without_installer(self, extractor, monkeypatch):
        from unittest.mock import Mock

        con = Mock()
        installer = Mock(side_effect=AssertionError("cached extension must not run installer"))
        monkeypatch.setattr(extractor.subprocess, "run", installer)
        extractor._load_httpfs(con)
        con.execute.assert_called_once_with("LOAD httpfs")
        installer.assert_not_called()

    def test_missing_httpfs_installs_from_https_with_deadline(self, extractor, monkeypatch):
        from unittest.mock import Mock, call

        con = Mock()
        con.execute.side_effect = [extractor.duckdb.IOException("not installed"), None]
        installer = Mock()
        monkeypatch.setattr(extractor.subprocess, "run", installer)
        extractor._load_httpfs(con)
        command = installer.call_args.args[0]
        assert command[0] == extractor.sys.executable
        assert "INSTALL httpfs FROM 'https://extensions.duckdb.org'" in command[-1]
        assert installer.call_args.kwargs["timeout"] == 60
        assert installer.call_args.kwargs["check"] is True
        assert con.execute.call_args_list == [call("LOAD httpfs"), call("LOAD httpfs")]

    @pytest.mark.parametrize("failure", ["timeout", "download"])
    def test_httpfs_install_failure_stops_without_retry(self, extractor, monkeypatch, failure):
        from unittest.mock import Mock

        con = Mock()
        con.execute.side_effect = extractor.duckdb.IOException("not installed")
        error = (
            extractor.subprocess.TimeoutExpired("install", 60)
            if failure == "timeout"
            else extractor.subprocess.CalledProcessError(1, "install", stderr="download failed")
        )
        installer = Mock(side_effect=error)
        monkeypatch.setattr(extractor.subprocess, "run", installer)
        with pytest.raises(RuntimeError, match="timed out" if failure == "timeout" else "download failed"):
            extractor._load_httpfs(con)
        installer.assert_called_once()
        con.execute.assert_called_once_with("LOAD httpfs")

    def test_local_extract_preserves_family_and_checksums(self, extractor, real_package, tmp_path, monkeypatch):
        import hashlib
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        monkeypatch.setattr(extractor, "remote", lambda con, release: {
            "patents": str(real_package / "patents.parquet"),
            "map": str(real_package / "patent_compound_map.parquet"),
            "compounds": str(real_package / "compounds.parquet"),
        })
        output = tmp_path / "chemist's extracted package"
        result = extractor.extract(["XX-1111111-A", "XX-1111111-A"], output, "2026-09-08")
        assert result["counts"] == {"patents": 2, "map_rows": 5, "compounds": 3}
        assert len(SureChemblBulkAdapter(output).load().documents) == 2
        for name, expected in result["manifest"]["files"].items():
            assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected["sha256"]
        with pytest.raises(ValueError, match="must be empty"):
            extractor.extract(["XX-1111111-A"], output, "2026-09-08")

    def test_rejects_mutable_release_before_network(self, extractor, tmp_path):
        with pytest.raises(ValueError, match="explicit dated"):
            extractor.extract(["XX-1111111-A"], tmp_path / "out", "latest")

    def test_incomplete_compound_source_cannot_publish_manifest(self, extractor, real_package, tmp_path, monkeypatch):
        path = real_package / "compounds.parquet"
        pq.write_table(pq.read_table(path).slice(0, 1), path)
        monkeypatch.setattr(extractor, "remote", lambda con, release: {
            "patents": str(real_package / "patents.parquet"),
            "map": str(real_package / "patent_compound_map.parquet"),
            "compounds": str(path),
        })
        output = tmp_path / "out"
        with pytest.raises(ValueError, match="mapped IDs missing"):
            extractor.extract(["XX-1111111-A"], output, "2026-09-08")
        assert not (output / "manifest.json").exists()


class TestIngestCorrections:
    @staticmethod
    def _result(package: Path, patent_digits: str):
        """Isolate imported documents from the module's shared schema fixture."""
        from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter

        result = SureChemblBulkAdapter(package).load()
        family_ids = {f.id: uuid.uuid4() for f in result.families}
        doc_ids = {d.id: uuid.uuid4() for d in result.documents}
        numbers = {d.publication_number: d.publication_number.replace("1111111", patent_digits) for d in result.documents}
        mention_ids = {m.mention_id: uuid.uuid4() for m in result.mentions}
        for family in result.families:
            family.id = family_ids[family.id]
            family.family_key = f"TEST-INGEST-{patent_digits}"
        for doc in result.documents:
            doc.id = doc_ids[doc.id]
            doc.family_id = family_ids[doc.family_id]
            doc.publication_number = numbers[doc.publication_number]
        for mention in result.mentions:
            mention.mention_id = mention_ids[mention.mention_id]
            mention.document_id = numbers[mention.document_id]
        for evidence in result.evidence:
            evidence.id = uuid.uuid4()
            evidence.document_id = doc_ids[evidence.document_id]
            evidence.compound_mention_id = mention_ids[evidence.compound_mention_id]
        for issue in result.issues:
            issue.document_id = numbers[issue.document_id]
        return result

    def test_corrected_structure_updates_stable_mention_and_evidence(self, real_source_engine, real_package):
        from spago_core.chemistry import normalize
        from spago_core.seed import _compound_id

        result = self._result(real_package, "2222222")
        mention = next(m for m in result.mentions if m.raw_smiles == "CCO")
        mention_id = mention.mention_id
        evidence = next(e for e in result.evidence if e.compound_mention_id == mention_id)
        ingest(real_source_engine, result)
        original_id = _compound_id(normalize("CCO").inchikey)
        mention.raw_smiles = "CCCO"
        updated_id = _compound_id(normalize("CCCO").inchikey)
        ingest(real_source_engine, result)
        ingest(real_source_engine, result)  # a retry must remain idempotent
        with real_source_engine.connect() as conn:
            row = conn.execute(text("""
                SELECT m.compound_id AS mention_compound, e.compound_id AS evidence_compound,
                       e.compound_mention_id
                FROM compound_mentions m JOIN evidence_records e ON e.compound_mention_id = m.id
                WHERE m.id = :mention AND e.id = :evidence
            """), {"mention": mention_id, "evidence": evidence.id}).mappings().one()
        assert original_id != updated_id
        assert row["mention_compound"] == row["evidence_compound"] == updated_id
        assert row["compound_mention_id"] == mention_id

    def test_second_package_same_release_preserves_first_packages_issues(self, real_source_engine, real_package):
        first = self._result(real_package, "3333333")
        second = self._result(real_package, "4444444")
        assert first.envelope.dataset_version == second.envelope.dataset_version
        ingest(real_source_engine, first)
        with real_source_engine.connect() as conn:
            before = conn.execute(text("""
                SELECT id FROM ingestion_issues WHERE dataset_version = :version AND document_id = :doc
            """), {"version": first.envelope.dataset_version, "doc": "XX-3333333-A"}).scalars().all()
        assert before
        ingest(real_source_engine, second)
        with real_source_engine.connect() as conn:
            after = conn.execute(text("""
                SELECT id FROM ingestion_issues WHERE dataset_version = :version AND document_id = :doc
            """), {"version": first.envelope.dataset_version, "doc": "XX-3333333-A"}).scalars().all()
        assert set(after) == set(before)

    def test_distinct_source_occurrences_can_share_structure_document_and_label(self, real_source_engine, real_package):
        result = self._result(real_package, "5555555")
        mention = next(m for m in result.mentions if m.raw_smiles == "CCO")
        original_evidence = next(e for e in result.evidence if e.compound_mention_id == mention.mention_id)
        other = mention.model_copy(update={
            "mention_id": uuid.uuid4(), "source_record_id": "SC-DISTINCT-SYNTHETIC-OCCURRENCE",
        })
        result.mentions.append(other)
        result.evidence.append(original_evidence.model_copy(update={
            "id": uuid.uuid4(), "compound_mention_id": other.mention_id,
            "compound_local_id": other.source_record_id,
        }))
        ingest(real_source_engine, result)
        ingest(real_source_engine, result)
        with real_source_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.id, m.compound_id, m.document_id, m.patent_label, count(e.id) AS evidence_count
                FROM compound_mentions m LEFT JOIN evidence_records e ON e.compound_mention_id = m.id
                WHERE m.id = ANY(:ids)
                GROUP BY m.id
            """), {"ids": [mention.mention_id, other.mention_id]}).mappings().all()
        assert len(rows) == 2
        assert len({(r["compound_id"], r["document_id"], r["patent_label"]) for r in rows}) == 1
        assert all(r["evidence_count"] == 1 for r in rows)
