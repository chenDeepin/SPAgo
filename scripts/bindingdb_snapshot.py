#!/usr/bin/env python
"""Investigate a target from a local BindingDB snapshot file (B-23).

The web app asks BindingDB over REST, one target at a time, and is limited to what
that endpoint returns. An operator who holds a BindingDB release on disk (for
example `BindingDB_All_2609.tsv`, 8.9 GB / 640 columns / ~3.2 M rows) can answer
the same question from the file: the whole release, with the target organism, the
chain count and the document each row came from, and without spending a rate limit
or depending on a third party being up.

    services/core/.venv/bin/python scripts/bindingdb_snapshot.py \
        --target "Interleukin-6" \
        --file /media/chen/Machine_Disk/Datasets/BindingDB_All_2609.tsv \
        --json benchmarks/bindingdb-snapshot-il6.json

What it reads and what it writes:

  * The target comes from **stored rows** (`TargetResolutionService.find_target`):
    this script never resolves, never calls a source and never invents an
    accession. A target the database does not hold is refused, with the action
    that fixes it (resolve it in the app first).
  * The measurements land in the same tables the REST path writes, through the
    same service (`TargetDiscoveryService.investigate`), one source at a time:
    `--dry-run` measures the file without writing anything, and a non-dry run asks
    only `bindingdb`, so a snapshot refresh cannot re-date the ChEMBL or PubChem
    rows that are already stored (B-06).
  * Every row keeps the release it came from (`bindingdb-snapshot:<release>`) and
    the retrieval records the file digest, size, rows scanned and match mode, so a
    stored measurement states which snapshot produced it (AGENTS.md §25).

Matching is deliberate (B-23 D3): the reviewed UniProt accession first — against
every `UniProt (SwissProt|TrEMBL) … of Target Chain N` column, so a complex row
matches on any chain — and then `Target Name`, exactly by default. `--name-mode
auto` accepts a substring and is how a related protein's rows ("Interleukin-6
receptor subunit alpha") enter the requested target's set; it is opt-in for that
reason.

Organism: the target's own organism is taken from the stored target row and rows
stating a different one are excluded and counted (`--all-organisms` keeps them,
`--organism` overrides the filter). A human reference set that quietly contains a
rat IC50 is a scientific error, not extra coverage.

Bounds and honesty (AGENTS.md §21, §22): a full scan of a multi-gigabyte release is
minutes, so `--max-rows` / `--max-seconds` stop early — and a stopped scan is
reported as `partial` with a warning, is stored as `partial`, and records no file
digest, because a prefix is not the snapshot. A run that reads the file to the end
says so.

Exit code: 0 when the source completed or answered `empty` (nothing in the release
matched); 1 when it did not complete (`failed`, or `partial` because a bound
stopped it); 2 when the request was refused before any scan (no such stored target,
no such file, unknown name mode).

Usage:
  --target TEXT             the stored target to investigate: key (`uniprot:P05231`),
                            gene symbol (`IL6`) or accession (`P05231`).
  --file PATH               the BindingDB TSV release (required).
  --release TEXT            override the release named by the filename.
  --name TEXT               extra `Target Name` alias to accept (repeatable);
                            stored aliases and the gene symbol are used by default.
  --name-mode MODE          `exact` (default), `auto` or `contains`.
  --organism TEXT           override the organism filter (default: the target's own).
  --all-organisms           keep matched rows whatever organism they state.
  --max-rows N              stop after N data rows (the run becomes `partial`).
  --max-seconds S           stop after S seconds of scanning (`partial`).
  --progress-every N        print a scan line every N rows (default 1000000; 0 off).
  --dry-run                 scan and report, write nothing.
  --json PATH               write the machine-readable record (`-` for stdout, where
                            the human summary moves to stderr so the pipe stays
                            parseable).
  --quiet                   print the verdict line only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "core"))

from spago_core.adapters.bindingdb_snapshot import (  # noqa: E402
    BindingDBSnapshotAdapter,
    SOURCE_VERSION,
)
from spago_core.config import get_settings  # noqa: E402
from spago_core.db import make_engine, run_migrations  # noqa: E402
from spago_core.domain import RetrievalStatus  # noqa: E402
from spago_core.services.discovery import TargetDiscoveryService  # noqa: E402
from spago_core.services.targets import TargetResolutionService  # noqa: E402


def _progress(message: str) -> None:
    print(f"  {message}", file=sys.stderr, flush=True)


def _stored_target(engine, query: str):
    """The stored target, or None. No source is contacted to answer this."""
    service = TargetResolutionService()
    return service.find_target(engine, query)


def _names(target, extra: list[str]) -> list[str]:
    """Alias names for `Target Name` matching: stored ones plus the operator's.

    The accession is not repeated here — the adapter matches it separately — and
    the target's display name is the first candidate, because a snapshot writes the
    curated protein name, not the gene symbol.
    """
    names: list[str] = []
    for candidate in [target.name, target.gene_symbol, *(target.aliases or []), *extra]:
        text = (candidate or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def _summary_lines(
    query: dict, *, kept: int, seen: int, excluded: int, rejections: dict
) -> list[str]:
    lines = [
        f"file           {query.get('snapshot_file')} "
        f"({query.get('snapshot_size_bytes', 0):,} bytes scanned)",
        f"release        {query.get('snapshot_release')}",
        f"rows scanned   {query.get('snapshot_rows_scanned', 0):,}"
        + ("" if query.get("snapshot_complete") else "  (prefix: a bound stopped the scan)"),
        f"matched rows   {query.get('matched_rows', 0):,} "
        f"({query.get('matched_by_accession', 0):,} by accession, "
        f"{query.get('matched_by_name', 0):,} by name under '{query.get('match_mode')}')"
        + (f" · aliases: {query.get('matched_aliases')}" if query.get("matched_aliases") else ""),
        f"records kept   {kept:,} (one per filled endpoint column)",
        f"records seen   {seen:,} · excluded {excluded:,}",
        f"file digest    {query.get('snapshot_sha256') or 'not recorded (incomplete scan)'}",
    ]
    if rejections:
        counts = ", ".join(f"{name}: {value:,}" for name, value in sorted(rejections.items()))
        lines.append(f"rejections     {counts}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--release", default=None)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--name-mode", choices=("exact", "auto", "contains"), default="exact")
    parser.add_argument("--organism", default=None)
    parser.add_argument("--all-organisms", action="store_true")
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    snapshot = Path(args.file)
    if not snapshot.is_file():
        print(f"refused: no such snapshot file {snapshot}", file=sys.stderr)
        return 2

    settings = get_settings()
    engine = make_engine(args.database_url or settings.database_url)
    run_migrations(engine, settings.migrations_dir)

    target = _stored_target(engine, args.target)
    if target is None:
        print(
            f"refused: no stored target matches {args.target!r}. This script reads the target "
            "from the database and deliberately does not resolve one; resolve it in the app "
            "first (Resolve target), then re-run this command.",
            file=sys.stderr,
        )
        return 2
    if not target.uniprot_accession and not _names(target, args.name):
        print(
            f"refused: target {target.target_key} has no accession and no name to match on.",
            file=sys.stderr,
        )
        return 2

    organism = args.organism if args.organism is not None else (target.organism or None)
    adapter = BindingDBSnapshotAdapter(
        snapshot,
        release=args.release,
        names=_names(target, args.name),
        name_mode=args.name_mode,
        organism=organism,
        all_organisms=args.all_organisms,
        max_rows=args.max_rows,
        max_seconds=args.max_seconds,
        progress_every=args.progress_every,
        progress=None if args.quiet else _progress,
    )

    # `--json -` is a pipe (`… | jq`): the machine-readable record must be the only
    # thing on stdout, so every human line this script prints — the preamble below
    # included — goes to stderr there. Everything else keeps the summary on stdout,
    # where an operator reads it.
    summary = sys.stderr if args.json == "-" else sys.stdout

    if not args.quiet:
        print(f"target     {target.name or target.target_key} ({target.target_key})", file=summary)
        print(f"accession  {target.uniprot_accession or 'none — name matching only'}", file=summary)
        print(
            f"organism   {organism or 'not filtered'}"
            f"{' (all organisms kept)' if args.all_organisms else ''}",
            file=summary,
        )
        print(f"names      {', '.join(adapter.names) or 'none'}", file=summary)
        print(f"snapshot   {snapshot} as release {adapter.release}", file=summary)
        print(
            f"mode       "
            f"{'dry run — nothing will be written' if args.dry_run else 'investigate bindingdb and store the result'}",
            file=summary,
        )

    started = time.monotonic()
    lines: list[str] = []
    if args.dry_run:
        result = adapter.load(target.uniprot_accession or "")
        record = {
            "mode": "dry-run",
            "target_key": target.target_key,
            "uniprot": target.uniprot_accession,
            "source_version": SOURCE_VERSION,
            "dataset_version": adapter.dataset_version,
            "status": result.status,
            "records_kept": len(result.records),
            "records_seen": result.records_seen,
            "records_excluded": result.records_excluded,
            "rejection_counts": result.rejection_counts,
            "query": result.query_context,
            "warnings": result.warnings,
        }
        lines = _summary_lines(
            result.query_context,
            kept=len(result.records),
            seen=result.records_seen,
            excluded=result.records_excluded,
            rejections=result.rejection_counts,
        )
        status = result.status
    else:
        service = TargetDiscoveryService(bindingdb=adapter)
        report = service.investigate(engine, target, sources=["bindingdb"])
        retrieval = next(r for r in report.retrievals if r.source_name == "bindingdb")
        record = {
            "mode": "stored",
            "target_id": str(target.id),
            "target_key": target.target_key,
            "uniprot": target.uniprot_accession,
            "source_version": retrieval.source_version,
            "dataset_version": retrieval.dataset_version,
            "status": retrieval.status.value,
            "records_kept": retrieval.records_kept,
            "records_seen": retrieval.records_seen,
            "records_excluded": retrieval.records_excluded,
            "rejection_counts": retrieval.rejection_counts,
            "query": retrieval.query,
            "checksum": retrieval.checksum,
            "retrieved_at": retrieval.retrieved_at.isoformat(),
            "measurements_stored": report.measurements_stored,
            "candidates_stored": report.candidates_stored,
            "compounds_stored": report.compounds_stored,
            "compounds_reused": report.compounds_reused,
            "warnings": retrieval.warnings,
        }
        lines = _summary_lines(
            retrieval.query,
            kept=retrieval.records_kept,
            seen=retrieval.records_seen,
            excluded=retrieval.records_excluded,
            rejections=retrieval.rejection_counts,
        )
        lines.append(
            f"stored         {report.measurements_stored:,} measurement(s) · "
            f"{report.candidates_stored:,} candidate(s) · "
            f"{report.compounds_stored:,} new compound(s), {report.compounds_reused:,} reused"
        )
        status = retrieval.status.value

    record["seconds"] = round(time.monotonic() - started, 1)
    record["generated_at"] = datetime.now(timezone.utc).isoformat()

    if args.quiet:
        print(f"bindingdb {status} · {record['records_kept']} record(s) kept", file=summary)
    else:
        for line in lines:
            print(line, file=summary)
        print(f"elapsed        {record['seconds']} s", file=summary)
        for warning in record["warnings"]:
            print(f"warn: {warning}", file=summary)
        print(
            f"bindingdb {status} · target {target.target_key} · "
            f"{record['records_kept']} record(s) kept"
            + ("" if args.dry_run else " · stored"),
            file=summary,
        )

    if args.json:
        payload = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if args.json == "-":
            sys.stdout.write(payload)
        else:
            out = Path(args.json)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")

    return 0 if status in {RetrievalStatus.COMPLETE.value, RetrievalStatus.EMPTY.value} else 1


if __name__ == "__main__":
    raise SystemExit(main())
