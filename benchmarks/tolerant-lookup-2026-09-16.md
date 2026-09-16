# Tolerant publication lookup — cost of the scan (B-03)

Measured 2026-09-16 on the local rehearsal stack (dockerized PostgreSQL with the RDKit
cartridge, `api_version` 0.1.0) with

```
services/core/.venv/bin/python scripts/tolerant_lookup_benchmark.py \
    --documents 50000 --runs 9 --json > benchmarks/tolerant-lookup-2026-09-16.json
```

The measurement exists because B-03 answers a typed number by normalizing it and
comparing it with the corpus, and chose that over a maintained normalized column. A scan
is only defensible while it is cheap, so the decision's cost is recorded here rather than
asserted (`AGENTS.md` §20).

## Setup

A synthetic corpus of **50 000 documents in 12 500 families** (four documents per family,
four countries cycling) was added to the operator's rehearsal database — 50 004 documents
in total, the demo corpus being 4 — and removed again when the run finished. Family size
is not cosmetic: `find_patent` ends in `get_family_overview`, so an earlier attempt that
put all 50 000 documents in *one* family measured the overview (294 ms for an **indexed**
lookup) instead of the lookup. That first, discarded run is why this file states the
family size.

Three end-to-end calls through `services.find_patent`, nine runs each:

| Path | What it is | Median | Min | Max |
| --- | --- | --- | --- | --- |
| `exact` | the stored identifier verbatim — the common case, unchanged by B-03 | **1.35 ms** | 1.05 | 2.15 |
| `tolerant` | `us 2012/100137` for a stored `US-2012-100137-A1`: exact miss, then the scan, then a hit | **154.83 ms** | 147.79 | 173.10 |
| `miss` | `WO-2099-999999-A1`: shape-valid, not in the corpus — the scan's worst case | **154.95 ms** | 146.30 | 176.32 |

The scan split into its two phases (same statement the service runs, timed on its own):

| Phase | Median |
| --- | --- |
| read `id, family_id, publication_number` from `patent_documents` | 84.11 ms |
| `patent_tokens` comparison in Python over the returned rows | 62.88 ms |

## What this says

- **The exact path did not become slower.** 1.35 ms is the indexed lookup it always was;
  the tolerant comparison runs *only* after it misses, so the common case pays nothing
  for this capability.
- **A tolerant hit costs about 155 ms on a 50 000-document corpus** — roughly half of it
  the read and half the in-process normalization. That is acceptable for an interactive
  lookup with a visible answer, and it is why the alternative (a second normalized column
  maintained by every import path) was rejected: it would buy back ~60 ms of process time
  at the price of a second writer of the rule that can go stale silently.
- **A miss costs the same as a hit** (155 ms), because the scan is a full read either
  way. There is no cheap negative answer; the honest one is the cost.
- **The cost scales linearly with the corpus, and this is the number that will change.**
  At 500 000 documents this path would be ~1.5 s, which is the point at which the
  decision recorded in the plan (`docs/plans/2026-09-16-tolerant-publication-lookup.md`
  §3) has to be revisited — a normalized column, a corpus-size guard that refuses to
  scan above a bound, or a SQL-side comparison. It is not a problem at today's corpus
  size and it should not be "fixed" before then (§37).

This is a measurement, not a target: nothing here is a latency budget, and no performance
claim beyond these numbers is being made.

---

Scope: one workstation, one database, one process, warm cache. The number to carry
forward is the *ratio* — exact ≈ 1 ms against tolerant ≈ 155 ms at 50 000 documents —
and the split between read and comparison, which says what to optimize first.
