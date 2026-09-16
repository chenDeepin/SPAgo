# B-26: patent coverage audit (live)

Measured 2026-09-16 on the local development stack (docker compose, database `spago`,
app image rebuilt from this checkout) through the shipped HTTP path
`POST /api/v1/patents/coverage` and its three exports. Raw record:
`patent-coverage-2026-09-16.json`. Build identity from `/healthz`:
`api_version 0.1.0`, `dataset_version demo-fixture-v1`, `rdkit_cartridge installed`.

The audit **calls no source**: every leg is a read of stored rows, which is why it needs
no user action and costs no rate limit (unlike the B-24 lookup it summarizes, measured at
16.0 s in `patent-source-declarations-2026-09-16.md`).

## Why this was measured

Four paths can now contribute chemistry to one publication — the imported corpus, a
per-publication source lookup (B-24), target-led source rows (B-02) and hand-added rows
(B-25) — and nothing put them side by side. The failure this causes is scientific: a reader
concludes "this patent has no compounds" from a compound table that only ever showed the
imported corpus. The audit exists to answer *what is stored, from which leg, and what
nobody has asked*, without letting `not_queried` read as `empty`.

## Results

### Latency and payload (stored rows only, no external call)

| Request | Runs | p50 | p95 | min | max | Response |
| --- | --- | --- | --- | --- | --- | --- |
| 5 publications | 20 | 4.4 ms | 5.0 ms | 3.5 ms | 40.9 ms | 11.7 KB |
| 50 publications (the bound) | 10 | 5.5 ms | 6.4 ms | 4.5 ms | 6.7 ms | 81.1 KB |

The 40.9 ms maximum is the first request after the container restart (connection and
query-plan warm-up), not a steady-state cost: the 50-publication batch, run after it,
never exceeded 6.7 ms. Both batch sizes are bounded by the request, not by the corpus —
the reads are grouped per batch (corpus metadata, mentions, lookups, target-led rows,
supplement rows), never per row.

### Exports

| Format | Time | Bytes | `x-spago-coverage-rule` | `Content-Disposition` |
| --- | --- | --- | --- | --- |
| Markdown | 5.6 ms | 3,895 | `patent-coverage-v1` | `spago-coverage-5-publications.markdown` |
| CSV | 4.0 ms | 10,398 | `patent-coverage-v1` | `spago-coverage-5-publications.csv` |
| JSON | 4.0 ms | 11,723 | `patent-coverage-v1` | `spago-coverage-5-publications.json` |

The rule and the publication count travel as headers *and* inside the file
(`# Patent coverage audit (patent-coverage-v1)`, the generated line, `## Rule`), so a
file that is copied out of the browser still states what produced it.

### What the live database actually answered

One request over five numbers, each chosen to exercise a different state
(`benchmarks/patent-coverage-2026-09-16.json` → `stored_state_read`):

| Publication | Headline | corpus | declared | supplement | never asked |
| --- | --- | --- | --- | --- | --- |
| `WO-2020-123456-A` | `corpus` | `has_records` (1 row, 1 compound) | `not_queried` | `not_queried` | declared, supplement |
| `US10508115` | `declared` | `not_queried` | `has_records` (191 rows, 73 compounds: 134 from the stored lookup + 57 target-led) | `not_queried` | corpus, supplement |
| `US10919895` | `declared` | `not_queried` | `has_records` (29 rows, 29 compounds, **target-led only**) | `not_queried` | corpus, supplement |
| `WO2020999999` | `empty` | `not_queried` | `asked_empty` | `not_queried` | corpus, supplement |
| `US9999999` | `not_queried` | `not_queried` | `not_queried` | `not_queried` | corpus, declared, supplement |

Totals: `publications 5 · holds_records 3 · not_fully_asked 5 · failed_legs 0 ·
ambiguous 0`. The three distinctions the item turns on are visible in one response:

- `US10508115` is a number the *corpus does not hold* and a reader would previously have
  seen as a dead end; the audit reports a stored declared set of 73 compounds under two
  different legs (a per-publication lookup and target-led rows for the same number), and
  keeps those two answers separate inside the leg rather than summing them into one.
- `WO2020999999` was **asked** and answered nothing (a stored ChEMBL lookup with
  `status = empty`) — `asked_empty`, which is a fact about the source under
  `chembl-document-patent-body-v1`, not a verdict about the patent.
- `US9999999` was **never asked** about anything — `not_queried`, with all three legs
  named in `unqueried`. This is the row that must never be rendered as "no compounds",
  and the one the surface's summary line counts separately.

### The refusals the surface depends on (all 422, none silent)

| Asked | Answer |
| --- | --- |
| `[]` | `A coverage audit needs at least one publication number.` |
| `["DEMO-PATENT-A"]` | `None of the requested values carries a publication number, so there is nothing to audit.` |
| `["TSLP", "thirteen elephants"]` | as above — free text never becomes an identifier |
| 51 numbers | `51 publications were asked about; one audit covers at most 50 (AGENTS.md §13). Split the list.` |

The last two are why the frontend filters its publication list with the mirrored
client-side shape rule before asking: a synthetic fixture whose ids are deliberately not
publication-number-shaped (`DEMO-PATENT-A`) produces no audit at all, rather than a
refusal banner where a coverage line would be.

## What this does and does not prove

- Proves: on this checkout and this database, the audit answers in single-digit
  milliseconds, stays bounded at 50 publications, distinguishes stored records from
  never-asked legs, and exports a self-describing file. The operator path
  (`scripts/patent_coverage.py`) was run against the same database directly and printed
  the same statuses and counts.
- Does not prove: anything about a patent's true content. The corpus leg can only report
  documents SPAgo imported (the true sibling set needs a bibliographic source, B-22), no
  licensed bulk snapshot is configured in this build (B-23), and `not_queried` is not an
  absent verdict. Hosted-deployment acceptance is a separate gate
  (`docs/online-capability.md` §6) and is not claimed here.
