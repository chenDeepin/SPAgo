# B-06 — Per-source re-run for target investigations

Round opened 2026-09-16. Class **NEXT · P1 · S–M** (owner request group). Register entry:
`docs/plans/backlog.md` §B-06. Base path this builds on: ONLINE-00 / ONLINE-06 / ONLINE-07,
migration 0015.

## What a user can do afterwards that they cannot do now

After a retrieval in which one source failed (or stopped at a bound), the user retries **that
source alone** from the target header, sees what the retry will spend before clicking, and gets
back a matrix in which the other sources' stored outcomes are exactly what they were — instead
of "Refresh sources", which asks all three again, re-spends the healthy sources' rate limits and
re-dates their rows.

## The problem, in the current checkout

1. `TargetDiscoveryService.investigate` (`spago_core/services/discovery.py:152`) builds one
   `SourceRetrieval` per source **including the ones it did not ask** — `not_queried`,
   "Not requested." (`:197`, `:214`, `:224`) — and then persists all of them
   (`:228-234`). The retrieval id is `uuid5(…, f"retrieval:{target.id}:{source_name}")`
   (`:940`), one row per (target, source), so a subset run **overwrites the other sources'
   stored outcome** with `not_queried` while their rows (candidates, measurements) stay in the
   database. The status machine then says "nobody asked ChEMBL" next to ChEMBL's own records.
2. `DiscoverRequest.sources` already accepts a subset and the route already validates it
   (`api/routes.py:1991`), but the response has no way to say which sources this run actually
   asked, and the UI always sends all three
   (`App.tsx:390`: `sources: ["chembl", "bindingdb", "pubchem"]`).
3. The only control is one button, "Refresh sources"
   (`components/TargetHeader.tsx:213`) / "Query open sources" (`:218`).
4. The recovery case is the live one: B-26 gave every source outcome a surface, `failed`
   included, and the only recovery from a `failed` source is the all-source refresh.

## Decisions

- **D1 — A stored outcome belongs to (target, source); a run rewrites only what it asked.**
  A subset run persists the sources it asked, plus a `not_queried` placeholder for a source
  that has **no stored row yet** (so "never asked" stays visible in the matrix, which is what
  the first full run records today). It never overwrites an outcome it did not produce.
- **D2 — One matrix, marked.** `DiscoveryReport.retrievals` stays one row per external source.
  Rows for sources this run did not ask are read back with `list_source_retrievals` and carry
  their stored status and counts, so a client never sees "not queried" beside a completed
  source. The API marks each row `requested_in_run` (`null` on the coverage read, where no run
  is being described).
- **D3 — The cost is a stored fact, not a prediction.** The retry control shows the last run's
  own numbers for that source (`pages_fetched`, `records_seen`, `latency_ms`), labelled as the
  last run. Nothing is estimated.
- **D4 — One owner for the action.** The per-source retry appears only where the all-source
  refresh is the wrong tool: a chip whose stored status is `failed` or `partial`. Healthy
  chips keep the existing "Refresh sources"; `not_queried` and `empty` have nothing to recover.
- **D5 — Refresh retraction is not built here.** Migration 0015's "a source refresh could not
  retract a mapping the new release no longer contains" is honoured in the sense that a re-run
  never retracts anything (a `failed`/`partial` ask establishes no absence) and never resurrects
  a retracted row wrongly (`_persist_candidates` clears `retracted_at` only for rows it actually
  receives). Deciding when absence *is* established for a source refresh — and how it interacts
  with compound-level candidacy in `investigation_measurements` — is its own item; it is recorded
  in the register as **B-30** with that reasoning rather than smuggled into this round.
- **D6 — Stored analyses are snapshots.** A retry does not rewrite a stored summary/analysis;
  the user re-runs the summary explicitly. The verdict is computed on read and therefore does
  reflect the new rows, which is the point of the retry.

## Steps

1. `services/discovery.py` — asked-only persistence, stored read-back for the rest.
2. `api/routes.py` — `requested_in_run` on `RetrievalResponse`; set it in `discover_target`.
3. `tests/test_b06_per_source_rerun.py` — service + API regression tests (what a subset run
   must not touch).
4. `components/TargetHeader.tsx`, `App.tsx`, `api/types.ts`, `styles.css` — the retry control,
   the cost line, the run's own report line, and the failure/empty states it must keep honest.
5. Docs — `docs/online-capability.md` (the recovery path), `docs/runbook.md` (operator call),
   `README.md` if the feature list needs it, backlog re-sort (+ B-30).
6. Measurements — `benchmarks/per-source-rerun-2026-09-16.{md,json}`: what a subset run changes
   in the database, from a fixture-driven run against PostgreSQL, plus the browser check on the
   local stack (which is subject to real upstream reachability and says so).

## Result

**Delivered 2026-09-16.** A subset run is now the recovery path for one source, and the
sources it did not ask are provably untouched.

- **Service** (`services/discovery.py`) — `investigate(..., sources=[...])` persists the
  retrieval rows it produced plus a `not_queried` placeholder only for a source that has no
  stored row yet; every other source is read back from `source_retrievals` with its stored
  status, counts, latency and `retrieved_at`. `DiscoveryReport.requested_sources` names what
  the run asked. Candidate persistence is unchanged and still per source.
- **API** (`api/routes.py`) — `RetrievalResponse.requested_in_run` (`true` for the asked
  rows, `false` for read-back rows, `null` on the coverage read); `{"sources": []}` → 422
  `Name at least one source; a run that asks nothing would only re-date the target.`
- **UI** (`TargetHeader.tsx`, `App.tsx`, `api/types.ts`, `styles.css`) — a `Retry <source>`
  control on `failed`/`partial` chips only, disabled while a retry is in flight (and the
  all-source refresh is disabled with it), a cost line taken from that source's own last run
  (`pages_fetched`, `records_seen`, `latency_ms`, `retrieved_at`), and a run note naming the
  asked set and saying the others were not asked again.
- **Tests** — `tests/test_b06_per_source_rerun.py`: 11 tests, service and API, all green
  (unasked rows not re-written, report read-back, candidate re-dating scoped to the retried
  source, failed retry retracts nothing, successful retry duplicates nothing, verdict over
  every source, `requested_in_run` in both reads, both 422 refusals). Whole tree:
  `--collect-only` reads 727 (716 before this round's 11), and the full run exits 0 in 204 s.
  The round also corrected the arithmetic the B-26 record carried ("suite 677 → 741" → 716):
  that number was an ad-hoc count, not a collection, and B-26's plan now says so.
- **Measurements** — `benchmarks/per-source-rerun-2026-09-16.{md,json}`: one retry = 1
  upstream request for that source and **0** for the other two; only that source's retrieval
  row changes; its own candidate rows re-date (2 when it answers, 0 when it fails); the
  other sources' rows keep their own retrieval time; measurements and verdict unchanged.
- **Live check** — local stack, real upstream: IL6R (`bindingdb failed`) and IL6
  (`pubchem partial`) both retried from the header; the other chips' stored outcomes
  (including their `retrieved_at`) were byte-identical afterwards.
- **Not built, on purpose (D5)** — retracting rows a *complete* refresh no longer returns:
  recorded as B-30.

