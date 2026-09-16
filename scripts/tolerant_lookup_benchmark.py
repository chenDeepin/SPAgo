#!/usr/bin/env python
"""Measure what the tolerant publication lookup costs (B-03).

B-03 answers the number a scientist actually types by normalizing it and comparing it
with the corpus, instead of comparing strings. That comparison runs **only after the
indexed exact lookup misses**, and it reads one small metadata table
(`patent_documents: id, family_id, publication_number`) rather than maintaining a second
normalized column that every import path would have to keep in step. The decision is
only defensible while the scan is cheap, so this script measures it on a corpus of known
size and prints the artifact behind the claim:

    services/core/.venv/bin/python scripts/tolerant_lookup_benchmark.py \
        --documents 50000 --runs 7 --json > benchmarks/tolerant-lookup-bench.json

Three numbers are reported, all end-to-end through `services.find_patent`:

  * `exact`      — the common case: the stored identifier, verbatim (indexed lookup).
  * `tolerant`   — a number written differently that hits: exact miss, then the scan.
  * `miss`       — a shape-valid number the corpus does not hold: the scan's worst case,
                   because it reads every document and answers nothing.

The synthetic family is named `TOLERANT-BENCH-FAMILY` and is removed again in a
`finally` block, so a crash does not leave 50 000 rows in the operator's database. It is
inserted into whatever database `--database-url` / `$SPAGO_DATABASE_URL` names, which is
the point: the cost that matters is the cost on the real storage engine, not on SQLite.

What this does *not* do: it does not touch the demo corpus (the synthetic rows live in
their own family), it makes no external call, and it is not a latency budget — a
measurement is not a target (AGENTS.md §20).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "core"))

from sqlalchemy import text  # noqa: E402

from spago_core.config import get_settings  # noqa: E402
from spago_core.db import make_engine  # noqa: E402
from spago_core.services import find_patent  # noqa: E402

FAMILY_KEY = "TOLERANT-BENCH-FAMILY"

#: Documents per synthetic family — a real patent family holds a handful of members, and
#: `find_patent` ends in a family overview whose cost scales with this number, not with
#: the corpus. Seeding one huge family would measure the overview instead of the lookup.
FAMILY_SIZE = 4

#: Family ids, filled by :func:`_seed`, so the documents can be inserted in one pass.
_family_ids: list[uuid.UUID] = []

#: Jurisdictions cycled so the corpus is not one country repeated, which is what a real
#: corpus looks like and what keeps the string comparison honest.
COUNTRIES = ("WO", "US", "EP", "JP", "CN", "KR", "DE", "FR")

#: The document the two hits are aimed at, and how many of its neighbours are inserted
#: before it, so the target is not the first row a scan meets.
TARGET_INDEX = 137

#: A number that is shape-valid and is not in the corpus: the scan's worst case.
MISS_QUERY = "WO-2099-999999-A1"


def _stored_number(index: int) -> str:
    country = COUNTRIES[index % len(COUNTRIES)]
    return f"{country}-{2000 + index % 25}-{100000 + index}-A1"


def _tolerant_query(index: int) -> str:
    """The same patent as :func:`_stored_number`, written the way a person writes it."""
    country = COUNTRIES[index % len(COUNTRIES)]
    return f"{country.lower()} {2000 + index % 25}/{100000 + index}"


def _family_key(index: int) -> str:
    return f"{FAMILY_KEY}-{index // FAMILY_SIZE}"


def _seed(engine, documents: int) -> None:
    """Seed a corpus of realistic *shape*: many small families, not one huge one.

    The size of a family is not cosmetic here. `find_patent` ends in
    `get_family_overview`, which loads that family's documents and mention counts, so a
    synthetic corpus made of one 50 000-document family would measure the overview rather
    than the lookup (observed in the first run of this script: 294 ms for an *indexed*
    lookup). Four documents per family is what a real patent family looks like.
    """
    families = (documents + FAMILY_SIZE - 1) // FAMILY_SIZE
    _family_ids[:] = [uuid.uuid4() for _ in range(families)]
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM patent_families WHERE family_key LIKE :k"), {"k": f"{FAMILY_KEY}%"}
        )
        conn.execute(
            text(
                """
                INSERT INTO patent_families (id, family_key, title, source_name,
                                             dataset_version, retrieved_at)
                VALUES (:id, :k, 'B-03 benchmark family (synthetic)', 'benchmark',
                        'synthetic:2026-09-16', now())
                """
            ),
            [
                {
                    "id": _family_ids[group],
                    "k": _family_key(group * FAMILY_SIZE),
                }
                for group in range(families)
            ],
        )
        batch = []
        for index in range(documents):
            batch.append(
                {
                    "id": uuid.uuid4(),
                    "fid": _family_ids[index // FAMILY_SIZE],
                    "pn": _stored_number(index),
                }
            )
            if len(batch) >= 5000:
                conn.execute(
                    text(
                        """
                        INSERT INTO patent_documents (id, family_id, publication_number,
                                                      source_name, dataset_version, retrieved_at)
                        VALUES (:id, :fid, :pn, 'benchmark', 'synthetic:2026-09-16', now())
                        """
                    ),
                    batch,
                )
                batch = []
        if batch:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:id, :fid, :pn, 'benchmark', 'synthetic:2026-09-16', now())
                    """
                ),
                batch,
            )


def _clear(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM patent_families WHERE family_key LIKE :k"), {"k": f"{FAMILY_KEY}%"}
        )


def _time(fn) -> float:
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


def _time_miss(fn) -> float:
    """Time a lookup that is *supposed* to answer nothing.

    A miss is a legitimate outcome here, not an error: the scan reads the whole table
    and finds no identifier, which is the most expensive path the tolerant rule can
    take. The exception is the answer, so it is consumed rather than propagated.
    """
    from spago_core.services import NotFoundError

    start = time.perf_counter()
    try:
        fn()
    except NotFoundError:
        pass
    return (time.perf_counter() - start) * 1000.0


def _summarise(samples: list[float]) -> dict:
    return {
        "runs": len(samples),
        "median_ms": round(statistics.median(samples), 2),
        "min_ms": round(min(samples), 2),
        "max_ms": round(max(samples), 2),
    }


def _scan_only_ms(engine, tokens: set[str]) -> dict:
    """The tolerant scan alone, split into its two phases.

    `find_patent`'s tolerant branch is `SELECT id, family_id, publication_number FROM
    patent_documents` plus a `patent_tokens` comparison in Python. Timing the phases
    separately says *which* one grows: the read is storage, the comparison is process
    time, and a corpus big enough to make this path hurt would have to move one of them
    (a normalized column or a SQL-side comparison) — so the artifact should name it.
    """
    from spago_core.domain.patent_numbers import patent_tokens

    with engine.connect() as conn:
        start = time.perf_counter()
        rows = conn.execute(
            text("SELECT id, family_id, publication_number FROM patent_documents")
        ).all()
        fetch_ms = (time.perf_counter() - start) * 1000.0
        start = time.perf_counter()
        matched = [row for row in rows if tokens & set(patent_tokens(row[2]))]
        match_ms = (time.perf_counter() - start) * 1000.0
    assert not matched, "the scan-only probe must not match: it is not a lookup"
    return {"fetch_ms": fetch_ms, "match_ms": match_ms}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--documents", type=int, default=50_000)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--database-url", default=None, help="defaults to $SPAGO_DATABASE_URL")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the synthetic family in place (for a manual EXPLAIN, say)",
    )
    args = parser.parse_args(argv)

    engine = make_engine(args.database_url or get_settings().database_url)
    stored_target = _stored_number(TARGET_INDEX)
    query = _tolerant_query(TARGET_INDEX)

    # The corpus as the operator's database already holds it, before anything synthetic:
    # the scan cost is a function of the corpus size, and both numbers are reported so a
    # reader can see which one produced the measurement.
    with engine.connect() as conn:
        corpus_documents = conn.execute(text("SELECT count(*) FROM patent_documents")).scalar_one()

    try:
        _seed(engine, args.documents)

        with engine.connect() as conn:
            seeded = conn.execute(text("SELECT count(*) FROM patent_documents")).scalar_one()

        exact = [
            _time(lambda: find_patent(engine, stored_target)) for _ in range(args.runs)
        ]
        tolerant = [_time(lambda: find_patent(engine, query)) for _ in range(args.runs)]
        miss = [_time_miss(lambda: find_patent(engine, MISS_QUERY)) for _ in range(args.runs)]
        from spago_core.domain.patent_numbers import patent_tokens

        scan_tokens = set(patent_tokens(MISS_QUERY))
        scan_only = [_scan_only_ms(engine, scan_tokens) for _ in range(args.runs)]
        found = find_patent(engine, query)
        record = {
            "rule": found.rule,
            "documents_seeded": args.documents,
            "families_seeded": len(_family_ids),
            "documents_in_corpus_with_seed": seeded,
            "documents_in_corpus_before": corpus_documents,
            "stored_target": stored_target,
            "tolerant_query": query,
            "miss_query": MISS_QUERY,
            "tolerant_matched": found.matched,
            "tolerant_exact": found.exact,
            "timings": {
                "exact": _summarise(exact),
                "tolerant": _summarise(tolerant),
                "miss": _summarise(miss),
                "scan_fetch": _summarise([s["fetch_ms"] for s in scan_only]),
                "scan_match": _summarise([s["match_ms"] for s in scan_only]),
            },
            # SQLAlchemy renders a URL with the password masked already.
            "database_url": str(engine.url),
        }
    finally:
        if not args.keep:
            _clear(engine)

    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"corpus {record['documents_in_corpus_with_seed']} documents (seeded {record['documents_seeded']})")
        print(f"exact      {record['timings']['exact']['median_ms']:8.2f} ms (median)")
        print(f"tolerant   {record['timings']['tolerant']['median_ms']:8.2f} ms (median)")
        print(f"miss       {record['timings']['miss']['median_ms']:8.2f} ms (median)")
        print(
            f"scan only  {record['timings']['scan_fetch']['median_ms'] + record['timings']['scan_match']['median_ms']:8.2f} ms"
            f" = fetch {record['timings']['scan_fetch']['median_ms']:.2f}"
            f" + match {record['timings']['scan_match']['median_ms']:.2f}"
        )
        print(f"matched    {record['tolerant_matched']} (exact={record['tolerant_exact']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
