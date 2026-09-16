#!/usr/bin/env python
"""What the loaded corpus covers — from the terminal (B-01).

The same numbers as `GET /api/v1/corpus` (the UI opens them from the corpus
badge), for the two jobs an operator has that the UI cannot do:

    # 1. after a batch import: what is actually in this database, by release?
    python -m spago_core.corpus_status
    python -m spago_core.corpus_status --json > corpus-2026-09-16.json

    # 2. before drawing a conclusion from a list: is this list really loaded?
    python -m spago_core.corpus_status --patents my-patents.txt
    # exits non-zero and prints every number that is NOT in the corpus

Rule this tool follows: "not in the corpus" is reported as exactly that. A number
that was never imported is not evidence that a patent has no chemistry, and the
exit code says so instead of leaving it to the reader (AGENTS.md §10, §4).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from spago_core.db import make_engine
from spago_core.services.core import (
    corpus_summary,
    publications_in_corpus,
    read_publication_list,
)

logger = logging.getLogger("corpus_status")


def format_summary(summary: dict) -> str:
    """A fixed-width table whose columns fit the longest value present.

    Truncating or overlapping a version string would defeat the purpose: the
    version is the thing the operator is reading the table to learn."""
    rows = summary["sources"]
    version_w = max([len("dataset version")] + [len(r["dataset_version"]) for r in rows])
    source_w = max([len("source")] + [len(r["source_name"] or "—") for r in rows])
    lines = []
    header = (
        f"{'dataset version':<{version_w}}  {'source':<{source_w}}  "
        f"{'fam':>5} {'docs':>5} {'cpds':>7} {'ment':>7} {'evid':>7} {'meas':>7} {'issues':>6}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        lines.append(
            f"{row['dataset_version']:<{version_w}}  {(row['source_name'] or '—'):<{source_w}}  "
            f"{row['families']:>5} {row['documents']:>5} {row['compounds']:>7} "
            f"{row['mentions']:>7} {row['evidence']:>7} {row['measurements']:>7} "
            f"{row['issues']:>6}"
            + ("" if row["registered"] else "  (not a registered package)")
        )
    totals = summary["totals"]
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<{version_w}}  {'':<{source_w}}  "
        f"{totals['families']:>5} {totals['documents']:>5} "
        f"{totals['compounds']:>7} {totals['mentions']:>7} {totals['evidence']:>7} "
        f"{totals['measurements']:>7} {totals['issues']:>6}"
    )
    imports = summary["imports"]
    lines.append("")
    lines.append(
        "import jobs: "
        f"{imports['completed']} completed, {imports['running']} running, "
        f"{imports['queued']} queued, {imports['failed']} failed, "
        f"{imports['interrupted']} interrupted"
    )
    if imports["last_error"]:
        last = imports["last_error"]
        lines.append(
            f"last failed job: {last['dataset_version']} — {last['error']}"
        )
    for note in summary["notes"]:
        lines.append(f"note: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--patents", type=Path, default=None,
        help="list/CSV of publication numbers to check against the corpus",
    )
    parser.add_argument("--column", default=None, help="column name or index for a tabular --patents file")
    args = parser.parse_args(argv)

    requested: list[str] = []
    if args.patents is not None:
        if not args.patents.is_file():
            logger.error("patent list not found: %s", args.patents)
            return 2
        try:
            requested = read_publication_list(args.patents, args.column)
        except ValueError as exc:
            logger.error("%s", exc)
            return 2
        if not requested:
            logger.error("no publication numbers in %s", args.patents)
            return 2

    engine = make_engine()
    try:
        summary = corpus_summary(engine)
        present = publications_in_corpus(engine, requested) if requested else set()
    finally:
        engine.dispose()

    missing = [number for number in requested if number not in present]
    if args.json:
        payload = dict(summary)
        if requested:
            payload["coverage_check"] = {
                "requested": len(requested),
                "found": len(present),
                "missing": missing,
            }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_summary(summary))
        if requested:
            print("")
            print(f"coverage check: {len(present)}/{len(requested)} publication(s) in the corpus")
            if missing:
                print(f"NOT in the corpus ({len(missing)}):")
                for number in missing:
                    print(f"  {number}")
    if missing:
        logger.error(
            "%s publication(s) are not in this corpus; that is a coverage gap, not a "
            "statement about the patents themselves", len(missing),
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
