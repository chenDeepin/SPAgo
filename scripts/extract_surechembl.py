#!/usr/bin/env python
"""Extract a minimal real SureChEMBL package for SPAgo (PROD-01).

SureChEMBL bulk data (EMBL-EBI FTP, CC BY 4.0) ships as Parquet snapshots:
patents.parquet (~5.5 GB), patent_compound_map.parquet (~4.7 GB),
compounds.parquet (~3.9 GB). DuckDB reads them over HTTPS with range requests,
pruning row groups by id where the release statistics permit, and
writes only the rows of the requested patent families into a small local
package that `python -m spago_core.import_package` ingests.

Usage:
    python scripts/extract_surechembl.py --release 2026-09-08 --patent US-5153197-A --out /tmp/pkg-losartan
    python scripts/extract_surechembl.py --release 2026-09-08 --patent US-5250534-A --out /tmp/pkg-sildenafil

Multiple --patent values are allowed; every extraction also includes all other
published documents of the same patent family (family scope, PROD-01
closure requires multi-document families).

Coverage honesty: if a publication number is not in the release, the script
fails with the numbers it could not find — SPAgo never serves a "not found" as
if the patent had no chemistry.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb

MAX_PACKAGE_ROWS = 100_000


def _sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


BASE_URL = "https://ftp.ebi.ac.uk/pub/databases/chembl/SureChEMBL/bulk_data"
ADAPTER_NAME = "surechembl_bulk"

logger = logging.getLogger("extract_surechembl")


def _load_httpfs(con: duckdb.DuckDBPyConnection) -> None:
    """Reuse a cached extension, or install the signed core build over HTTPS.

    The first-install download runs separately so its wall time is bounded even
    before httpfs exposes the HTTP timeout settings on the query connection.
    """
    try:
        con.execute("LOAD httpfs")
        return
    except duckdb.IOException:
        logger.info("installing DuckDB httpfs from the official HTTPS extension repository…")
    try:
        subprocess.run(
            [sys.executable, "-c", "import duckdb; duckdb.connect().execute(\"INSTALL httpfs FROM 'https://extensions.duckdb.org'\")"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        con.execute("LOAD httpfs")
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("DuckDB httpfs installation timed out after 60 seconds; no source extraction was started.") from exc
    except (subprocess.CalledProcessError, duckdb.Error) as exc:
        detail = exc.stderr[-1000:] if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise RuntimeError(f"DuckDB httpfs could not be installed/loaded from the official HTTPS repository: {detail}") from exc


def remote(con: duckdb.DuckDBPyConnection, release: str) -> dict[str, str]:
    return {
        "patents": f"{BASE_URL}/{release}/patents.parquet",
        "map": f"{BASE_URL}/{release}/patent_compound_map.parquet",
        "compounds": f"{BASE_URL}/{release}/compounds.parquet",
    }


def extract(
    patents_numbers: list[str],
    out_dir: Path,
    release: str,
    compounds_override: str | None = None,
) -> dict:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release):
        raise ValueError("Use an explicit dated SureChEMBL release (YYYY-MM-DD), not a mutable latest alias.")
    if not patents_numbers or any(not p.strip() for p in patents_numbers):
        raise ValueError("At least one nonempty publication number is required.")
    patents_numbers = list(dict.fromkeys(patents_numbers))
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output directory must be empty; refusing to mix or overwrite source packages.")
    out_dir.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET enable_progress_bar=false")
        con.execute("SET memory_limit='2GB'")
        urls = remote(con, release)
        if compounds_override:
            # A pre-downloaded local compounds.parquet makes the batch phase local
            # (the file is not needed remotely when network throughput is poor).
            urls["compounds"] = compounds_override
        if any(url.startswith("https://") for url in urls.values()):
            _load_httpfs(con)
            con.execute("SET http_timeout=30")
            con.execute("SET http_retries=3")

        # Phase 1 — narrow scan: only id/patent_number/family_id (small columns)
        # to resolve the requested publications and their families.
        quoted = ", ".join(_sql_literal(p) for p in patents_numbers)
        logger.info("resolving %d publication number(s) in the release index…", len(patents_numbers))
        resolved = con.execute(
            f"""
            SELECT id, family_id FROM read_parquet({_sql_literal(urls['patents'])})
            WHERE patent_number IN ({quoted})
            """
        ).fetchall()
        if len(resolved) != len(patents_numbers):
            # Re-fetch with the number to report exactly which are missing.
            found = set(
                con.execute(
                    f"""
                    SELECT patent_number FROM read_parquet({_sql_literal(urls['patents'])})
                    WHERE patent_number IN ({quoted})
                    """
                ).fetchall()
            )
            missing = [p for p in patents_numbers if p not in {f[0] for f in found}]
            if missing:
                raise SystemExit(
                    f"Not covered by SureChEMBL release {release}: {', '.join(missing)}. "
                    "The current source has no chemistry for these publication numbers."
                )

        if any(r[1] is None for r in resolved):
            raise ValueError("Source publication has no family ID; family expansion cannot be established.")
        family_ids = sorted({r[1] for r in resolved})
        fam_list = ", ".join(str(f) for f in family_ids)
        logger.info("found %d family(ies): %s", len(family_ids), fam_list)

        # Phase 2 — wide rows for the whole family (one scan, projected columns;
        # the copy materializes only matching rows locally).
        patents_out = out_dir / "patents.parquet"
        con.execute(
            f"""
            COPY (
                SELECT id, patent_number, country, publication_date, family_id,
                       cpc, ipcr, ipc, ecla, assignee, title
                FROM read_parquet({_sql_literal(urls['patents'])})
                WHERE family_id IN ({fam_list})
                ORDER BY family_id, publication_date, patent_number
            ) TO {_sql_literal(patents_out.as_posix())} (FORMAT PARQUET)
            """
        )
        if con.execute(f"SELECT count(*) FROM read_parquet({_sql_literal(patents_out)})").fetchone()[0] > MAX_PACKAGE_ROWS:
            raise ValueError("Patent extract exceeds the family-extract row limit.")
        patent_ids = [
            r[0]
            for r in con.execute(
                f"SELECT id FROM read_parquet({_sql_literal(patents_out.as_posix())})"
            ).fetchall()
        ]
        pid_list = ", ".join(str(p) for p in patent_ids)

        map_out = out_dir / "patent_compound_map.parquet"
        con.execute(
            f"""
            COPY (
                SELECT patent_id, compound_id, field_id
                FROM read_parquet({_sql_literal(urls['map'])})
                WHERE patent_id IN ({pid_list})
                ORDER BY patent_id, compound_id, field_id
            ) TO {_sql_literal(map_out.as_posix())} (FORMAT PARQUET)
            """
        )
        if con.execute(f"SELECT count(*) FROM read_parquet({_sql_literal(map_out)})").fetchone()[0] > MAX_PACKAGE_ROWS:
            raise ValueError("Mapping extract exceeds the family-extract row limit; request fewer families.")
        compounds_out = out_dir / "compounds.parquet"
        # Fetched in small batches: a short literal IN list prunes row groups on
        # the id-sorted compounds file. A subquery — or one huge IN list — can
        # degrade to streaming the whole ~4 GB file over HTTP range requests.
        compound_ids = [
            r[0]
            for r in con.execute(
                f"SELECT DISTINCT compound_id FROM read_parquet({_sql_literal(map_out.as_posix())}) ORDER BY compound_id"
            ).fetchall()
        ]
        logger.info("fetching %d unique compound row(s) in batches…", len(compound_ids))
        con.execute(
            """
            CREATE TEMP TABLE extracted_compounds (
                id BIGINT, smiles VARCHAR, inchi VARCHAR, inchi_key VARCHAR, mol_weight DOUBLE
            )
            """
        )
        batch_size = 100
        for start in range(0, len(compound_ids), batch_size):
            batch = compound_ids[start : start + batch_size]
            cid_list = ", ".join(str(c) for c in batch)
            con.execute(
                f"""
                INSERT INTO extracted_compounds
                SELECT c.id, c.smiles, c.inchi, c.inchi_key, c.mol_weight
                FROM read_parquet({_sql_literal(urls['compounds'])}) c
                WHERE c.id IN ({cid_list})
                """
            )
        con.execute(
            f"""
            COPY (SELECT * FROM extracted_compounds ORDER BY id)
            TO {_sql_literal(compounds_out.as_posix())} (FORMAT PARQUET)
            """
        )

        extracted_ids = {r[0] for r in con.execute("SELECT id FROM extracted_compounds").fetchall()}
        missing_compounds = set(compound_ids) - extracted_ids
        if missing_compounds:
            raise ValueError(f"Compound source is incomplete: {len(missing_compounds)} mapped IDs missing.")
        files = {}
        for path in (patents_out, map_out, compounds_out):
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(chunk)
            files[path.name] = {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}
        manifest = {
            "adapter": ADAPTER_NAME,
            "schema_version": 1,
            "ingestion_version": 1,
            "files": files,
            "source": "EMBL-EBI SureChEMBL bulk data (CC BY 4.0)",
            "release": release,
            "dataset_version": f"surechembl-{release}",
            "synthetic": False,
            "requested_patents": patents_numbers,
            "family_ids": family_ids,
            "remote_files": {name: url for name, url in urls.items()},
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Real SureChEMBL extract. Page numbers and patent-local text labels are "
                "not part of the bulk data and are shown as not provided in SPAgo."
            ),
        }
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

        counts = {
            "patents": con.execute(
                f"SELECT count(*) FROM read_parquet({_sql_literal(patents_out.as_posix())})"
            ).fetchone()[0],
            "map_rows": con.execute(
                f"SELECT count(*) FROM read_parquet({_sql_literal(map_out.as_posix())})"
            ).fetchone()[0],
            "compounds": con.execute(
                f"SELECT count(*) FROM read_parquet({_sql_literal(compounds_out.as_posix())})"
            ).fetchone()[0],
        }
        return {"manifest": manifest, "counts": counts, "out_dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--patent", action="append", required=True,
        help="publication number as written by SureChEMBL (e.g. US-5153197-A); repeatable",
    )
    parser.add_argument("--out", type=Path, required=True, help="output package directory")
    parser.add_argument(
        "--release", required=True,
        help="immutable SureChEMBL release directory (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--compounds", default=None,
        help="optional local path to a pre-downloaded compounds.parquet",
    )
    args = parser.parse_args(argv)

    result = extract(args.patent, args.out, args.release, args.compounds)
    counts = result["counts"]
    manifest = result["manifest"]
    logger.info(
        "package written to %s: %s family docs, %s mapping rows, %s compounds",
        result["out_dir"], counts["patents"], counts["map_rows"], counts["compounds"],
    )
    logger.info(
        "import it with: python -m spago_core.import_package %s", result["out_dir"]
    )
    if manifest["family_ids"]:
        logger.info("SureChEMBL families covered: %s", manifest["family_ids"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
