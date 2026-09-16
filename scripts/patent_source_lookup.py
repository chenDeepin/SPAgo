#!/usr/bin/env python
"""Ask a public source what it declares for a publication, and record the answer (B-24).

The browser path is the patent view's "Ask ChEMBL what it declares" control. This
script is the same service path without a browser, for two jobs:

  * run a lookup for a publication nobody is looking at, so the set is stored and
    the panel opens instantly;
  * produce the artifact behind B-24's claim, on the real API and a real database,
    instead of a fixture:

      services/core/.venv/bin/python scripts/patent_source_lookup.py \
          --patents US10508115 --json > benchmarks/patent-source-US10508115.json

What it does *not* do: it never writes into the corpus. A declared set lands in
`patent_source_lookups` / `patent_source_compounds`, it is never a
`compound_mentions` row, and nothing here changes a family's compound count
(AGENTS.md §11). A publication the source does not know is reported as `empty`
**with the match rule that produced it**, which is a different answer from
`failed` (the source could not be asked) and from `not_queried` (nobody asked).

Exit code: non-zero if any lookup `failed`, because a run that silently reports
source trouble as "nothing declared" would be the worst possible outcome. `empty`
is a successful run.

Usage:
  --patents NUM [NUM ...]   publication numbers, in any separator style the
                            normalizer accepts (`US-10508115-B2`, `US10508115`).
  --patents-file FILE       read numbers from a file, one per line (`#` comments
                            and blank lines ignored).
  --database-url URL        defaults to $SPAGO_DATABASE_URL.
  --max-activities N        bound the activity records read per publication.
  --json                    print each stored view as JSON (for an artifact).
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


def _numbers(args: argparse.Namespace) -> list[str]:
    numbers = list(args.patents or [])
    if args.patents_file:
        for line in Path(args.patents_file).read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                numbers.append(stripped)
    return numbers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patents", nargs="*", default=[])
    parser.add_argument("--patents-file")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--max-activities", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    numbers = _numbers(args)
    if not numbers:
        parser.error("give at least one publication number (--patents or --patents-file)")

    settings = get_settings()
    database_url = args.database_url or settings.database_url
    engine = make_engine(database_url)
    run_migrations(engine, settings.migrations_dir)

    from spago_core.services.patent_sources import (
        PatentSourceError,
        PatentSourceService,
    )

    service = PatentSourceService()
    views: list[dict] = []
    failures = 0
    bounds: dict[str, int] = {}
    if args.max_activities is not None:
        bounds["max_activities"] = args.max_activities
    for number in numbers:
        try:
            view = service.lookup(engine, number, **bounds)
        except PatentSourceError as exc:
            print(f"{number}: refused — {exc}", file=sys.stderr)
            failures += 1
            continue
        views.append(view)
        if view["status"] == "failed":
            failures += 1
        headline = (
            f"{view['publication_number']} · {view['source_name']} · {view['status']} · "
            f"{view['row_count']} declared record(s) for {view['compound_count']} "
            f"compound(s) · {view['records_seen']} seen, "
            f"{view['records_excluded']} not usable · rule {view['match_rule']}"
        )
        print(headline, file=sys.stderr if args.quiet else sys.stdout)
        for warning in view["warnings"]:
            print(f"  note: {warning}", file=sys.stderr if args.quiet else sys.stdout)
        if not args.quiet and view["documents"]:
            for document in view["documents"]:
                print(
                    f"  document the source matched: {document['patent_id']} "
                    f"({document['document_chembl_id']})",
                    file=sys.stdout,
                )
        if not args.quiet and view["near_matches"]:
            for match in view["near_matches"]:
                print(
                    f"  near match, excluded: {match['patent_id']} ({match['reason']})",
                    file=sys.stdout,
                )

    if args.json:
        payload = views[0] if len(views) == 1 else views
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
