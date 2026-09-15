"""Import a source package into PostgreSQL (PROD-01).

Usage (inside the app container or a local venv):

    python -m spago_core.import_package <package_dir>

A package is a directory produced by an extractor, e.g.
`scripts/extract_surechembl.py` (real SureChEMBL bulk extract) — Parquet files
in the source schema plus a manifest with provenance. This command:

- refuses to guess the source type (the manifest's `adapter` field selects it);
- records a durable import job (import_jobs): queued → running → completed /
  failed, with the package file checksums and the ingest summary;
- runs the same deterministic ingestion pipeline as the demo seed
  (RDKit normalization, typed mentions/evidence, recorded issues);
- is idempotent: re-importing the same package updates, never duplicates.

This is the user-completable real-data path: no Python edits, no manual SQL,
no faked Parquet.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from pathlib import Path

from sqlalchemy import text

from spago_core.adapters.surechembl_bulk import SureChemblBulkAdapter
from spago_core.config import get_settings
from spago_core.db import make_engine
from spago_core.seed import ingest

logger = logging.getLogger("spago_core.import_package")

ADAPTERS = {
    "surechembl_bulk": SureChemblBulkAdapter,
}


def _file_checksums(package_dir: Path) -> dict[str, dict]:
    """SHA-256 + size for every package file: recorded provenance, and the
    basis for detecting a changed package later."""
    files = {}
    for path in sorted(package_dir.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            files[str(path.relative_to(package_dir))] = {
                "sha256": digest.hexdigest(),
                "bytes": path.stat().st_size,
            }
    return files


def import_package(engine, package_dir: Path) -> dict:
    from spago_core.db import run_migrations

    settings = get_settings()
    run_migrations(engine, settings.migrations_dir)

    package_dir = Path(package_dir)
    job_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO import_jobs (id, source_name, dataset_version, synthetic, status)
                VALUES (:id, 'unknown', 'unknown', false, 'queued')
            """),
            {"id": job_id},
        )
        # A `running` job whose process died would otherwise read as "in progress"
        # forever (defect D5). This run declares it interrupted — the state the
        # row is really in — and says who recovered it.
        recovered = conn.execute(
            text(
                """
                UPDATE import_jobs
                   SET status = 'interrupted',
                       finished_at = now(),
                       error = 'interrupted: the process that owned this job stopped before '
                               'finishing; recovered when import job ' || :job || ' started'
                 WHERE status = 'running'
                """
            ),
            {"job": str(job_id)},
        ).rowcount
    if recovered:
        logger.warning(
            "%s unfinished import job(s) marked interrupted before this run", recovered
        )

    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE import_jobs SET status = 'running', started_at = now() WHERE id = :id"),
                {"id": job_id},
            )
        manifest = json.loads((package_dir / "manifest.json").read_text())
        if not isinstance(manifest, dict):
            raise ValueError("Package manifest must be an object.")
        adapter_name = manifest.get("adapter")
        adapter_cls = ADAPTERS.get(adapter_name) if isinstance(adapter_name, str) else None
        if adapter_cls is None:
            known = ", ".join(sorted(ADAPTERS)) or "none"
            raise ValueError(
                f"Package manifest field 'adapter' must be one of: {known}. "
                f"Got {adapter_name!r}; refusing to guess a source type."
            )
        adapter = adapter_cls(package_dir)
        files = _file_checksums(package_dir)
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE import_jobs SET source_name = :source, dataset_version = :version,
                        synthetic = :synthetic, files = CAST(:files AS jsonb) WHERE id = :id
                """),
                {"id": job_id, "source": adapter_name, "version": manifest["dataset_version"],
                 "synthetic": manifest["synthetic"], "files": json.dumps(files)},
            )
        expected = manifest.get("files", {})
        if not isinstance(expected, dict):
            raise ValueError("Package manifest files must be an object.")
        for name, checksum in expected.items():
            if files.get(name) != checksum:
                raise ValueError(f"Package checksum mismatch: {name}")
        result = adapter.load()
        if _file_checksums(package_dir) != files:
            raise ValueError("Package changed while it was being loaded; retry with a stable package.")
        if result.dataset_info is not None:
            result.dataset_info.files = files
        report = ingest(engine, result)
        summary = {
            "families": report.families,
            "documents": report.documents,
            "compounds": report.compounds,
            "mentions": report.mentions,
            "evidence": report.evidence,
            "measurements": report.measurements,
            "issues": len(report.issues),
            "warnings": report.warnings,
            "package_files": len(files),
            # Defect D4: rows of this source the release no longer contains.
            "retracted_mentions": report.retracted_mentions,
            "retracted_evidence": report.retracted_evidence,
        }
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE import_jobs SET status = 'completed', summary = CAST(:s AS jsonb),
                                           finished_at = now()
                    WHERE id = :id
                    """
                ),
                {"s": json.dumps(summary), "id": job_id},
            )
        return {
            "job_id": str(job_id),
            "status": "completed",
            "recovered_jobs": recovered,
            "summary": summary,
        }
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE import_jobs SET status = 'failed', error = :err,
                                           finished_at = now()
                    WHERE id = :id
                    """
                ),
                {"err": f"{type(exc).__name__}: {exc}"[:2000], "id": job_id},
            )
        raise


def list_jobs(engine, limit: int = 20) -> list[dict]:
    """Recent import jobs, newest first — how an operator sees `interrupted`
    rather than reading the table by hand (defect D5)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, source_name, dataset_version, status, synthetic,
                       created_at, started_at, finished_at, error, summary
                  FROM import_jobs
                 ORDER BY created_at DESC
                 LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    return [dict(row) for row in rows]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        description="Import a SPAgo source package (e.g. a SureChEMBL extract)."
    )
    parser.add_argument("package_dir", type=Path, nargs="?", help="package directory to import")
    parser.add_argument(
        "--status",
        action="store_true",
        help="list recent import jobs (status, error, summary) and exit",
    )
    args = parser.parse_args(argv)

    if args.status:
        engine = make_engine()
        try:
            jobs = list_jobs(engine)
        finally:
            engine.dispose()
        if not jobs:
            logger.info("no import job has run against this database")
            return 0
        for job in jobs:
            line = (
                f"{job['created_at']} {job['id']} {job['source_name']}@"
                f"{job['dataset_version']} {job['status']}"
            )
            if job["error"]:
                line += f" error={job['error']}"
            logger.info(line)
        return 0

    if args.package_dir is None:
        parser.error("a package directory is required unless --status is given")
    if not args.package_dir.is_dir():
        logger.error("package directory not found: %s", args.package_dir)
        return 2
    engine = make_engine()
    try:
        outcome = import_package(engine, args.package_dir)
    except Exception as exc:
        logger.error("import failed: %s: %s", type(exc).__name__, exc)
        return 1
    finally:
        engine.dispose()
    logger.info("import completed: %s", json.dumps(outcome["summary"]))
    logger.info("import job %s recorded (status=completed)", outcome["job_id"])
    if outcome.get("recovered_jobs"):
        logger.warning(
            "%s earlier job(s) marked interrupted; `--status` lists them",
            outcome["recovered_jobs"],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
