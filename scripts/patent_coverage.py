#!/usr/bin/env python
"""Audit what SPAgo holds for a publication, from where, and what nobody asked (B-26).

The browser path is the patent view's coverage strip. This script is the same
service read without a browser, for the operator's jobs:

  * audit a portfolio list on the workstation and see which publications have no
    stored answer anywhere (and which were simply never asked);
  * produce the artifact behind a coverage claim, on a real database:

      services/core/.venv/bin/python scripts/patent_coverage.py \
          --patents-file portfolio.txt --json > benchmarks/coverage-portfolio.json

What it does *not* do: it calls no source, and it writes nothing. Every number in
the report comes from stored rows (corpus mentions, stored source lookups,
target-led rows, hand-added rows), so an audit never changes what the database
holds and never spends a rate limit (AGENTS.md §16).

The three states an operator has to keep apart are the reason this exists:

  * `empty`   — a leg was asked and holds no records (for example the source knows
                no compound for that number);
  * `failed`  — a leg's ask did not complete; re-run it instead of reading it;
  * `not_queried` — nobody asked. It is *not* "this publication has no compounds",
                and it is never an `absent` verdict.

Exit code: 0 when nothing needs the operator's attention, 1 when it does — any
publication with no stored answer anywhere (`not_queried`: nobody has looked yet), or
any ask that did not complete (`failed`: re-run it). A publication a source answered
`empty` for is an answer, not a gap, and exits 0: the difference between "we asked and
there is nothing" and "we never asked" is the whole point of the rule.

Usage:
  --patents NUM [NUM ...]   publication numbers, in any separator style the
                            normalizer accepts (`US-10508115-B2`, `US10508115`).
  --patents-file FILE       read numbers from a file, one per line (`#` comments
                            and blank lines ignored).
  --database-url URL        defaults to $SPAGO_DATABASE_URL.
  --out PATH                write the report to a file; `-` is stdout (default).
  --format FORMAT           `text` (default), `json`, `csv` or `markdown`.
  --json                    shorthand for `--format json`.
  --quiet                   print one line per publication only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "core"))

from spago_core.config import get_settings  # noqa: E402
from spago_core.db import make_engine, run_migrations  # noqa: E402

from spago_core.services.coverage import (  # noqa: E402
    CoverageError,
    MAX_COVERAGE_PUBLICATIONS,
    audit_publications,
    merge_coverage_reports,
    render_coverage_csv,
    render_coverage_markdown,
)

_LEG_LABEL = {"corpus": "corpus", "declared": "declared", "supplement": "by hand"}


def _numbers(args: argparse.Namespace) -> list[str]:
    numbers = list(args.patents or [])
    if args.patents_file:
        for line in Path(args.patents_file).read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                numbers.append(stripped)
    return numbers


def _answer_label(answer) -> str:
    """Name the path that stored this answer, in the operator's terms."""
    if answer.kind == "corpus":
        return "stored corpus document"
    if answer.kind == "hand_added":
        return "hand-added rows"
    if answer.kind == "patent_source_lookup":
        return f"{answer.source_name} per-publication lookup"
    return f"{answer.source_name} target-led rows"


def _leg_line(leg) -> str:
    label = _LEG_LABEL.get(leg.leg, leg.leg)
    counts = ""
    if leg.records:
        counts = f" · {leg.records} row(s)"
        if leg.compounds:
            counts += f", {leg.compounds} compound(s)"
        if leg.unconfirmed_records:
            counts += f", {leg.unconfirmed_records} awaiting confirmation"
    return f"{label}: {leg.state}{counts}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patents", nargs="*", default=[])
    parser.add_argument("--patents-file")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--out", default="-")
    parser.add_argument("--format", choices=("text", "json", "csv", "markdown"), default="text")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    numbers = _numbers(args)
    if not numbers:
        parser.error("give at least one publication number (--patents or --patents-file)")
    fmt = "json" if args.json else args.format

    settings = get_settings()
    engine = make_engine(args.database_url or settings.database_url)
    run_migrations(engine, settings.migrations_dir)

    try:
        report = merge_coverage_reports(
            [
                audit_publications(engine, numbers[index : index + MAX_COVERAGE_PUBLICATIONS])
                for index in range(0, len(numbers), MAX_COVERAGE_PUBLICATIONS)
            ]
        )
    except CoverageError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    stream = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8")
    try:
        if fmt == "json":
            json.dump(report.model_dump(mode="json"), stream, indent=2, sort_keys=True)
            stream.write("\n")
        elif fmt == "csv":
            stream.write(render_coverage_csv(report))
        elif fmt == "markdown":
            stream.write(render_coverage_markdown(report))
        else:
            for row in report.publications:
                stored = row.matched or row.requested
                if not args.quiet:
                    print(f"{stored} · {row.status}", file=stream)
                    for leg in row.legs:
                        print(f"  {_leg_line(leg)}", file=stream)
                        for answer in leg.answers:
                            counts = f" · {answer.records} row(s)"
                            if answer.compounds:
                                counts += f", {answer.compounds} compound(s)"
                            if answer.unconfirmed_records:
                                counts += (
                                    f", {answer.unconfirmed_records} awaiting confirmation"
                                )
                            print(
                                f"    {_answer_label(answer)} · {answer.status}{counts}",
                                file=stream,
                            )
                    if row.unqueried:
                        print(f"  never asked: {', '.join(row.unqueried)}", file=stream)
                    if row.ambiguous:
                        print(
                            f"  also matches (not merged): {', '.join(row.ambiguous)}",
                            file=stream,
                        )
                    print(f"  why: {row.status_reason}", file=stream)
                else:
                    print(
                        f"{stored} · {row.status} · "
                        + "; ".join(_leg_line(leg) for leg in row.legs),
                        file=stream,
                    )
            print("", file=stream)
            print(f"rule: {report.rule}", file=stream)
            print(
                "publications: {publications} · holding records: {holds_records} · "
                "never fully asked: {not_fully_asked} · "
                "incomplete asks: {failed_legs} · ambiguous: {ambiguous}".format(
                    **{
                        key: report.totals.get(key, 0)
                        for key in (
                            "publications",
                            "holds_records",
                            "not_fully_asked",
                            "failed_legs",
                            "ambiguous",
                        )
                    }
                ),
                file=stream,
            )
            for note in report.notes:
                print(f"note: {note}", file=stream)
    finally:
        if stream is not sys.stdout:
            stream.close()

    # Two things need the operator: a publication nobody has asked anything about,
    # and an ask that did not complete. A leg deliberately never asked is a gap the
    # report names per row (and the strip offers the action); it is not a failure.
    gaps = report.totals.get("not_queried", 0) or report.totals.get("failed_legs", 0)
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
