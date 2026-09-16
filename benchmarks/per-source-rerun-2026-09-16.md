# B-06: per-source re-run (fixture measurement + live browser check)

Measured 2026-09-16. Two shapes, labelled separately because they prove different things:

- **Fixture-only write set** — recorded upstream payloads through the real adapters and the
  real service, against a real PostgreSQL (scratch database `spago_test`). No source is
  called, so upstream wall time is *not* measured; what is measured is the write set, the
  upstream request count the adapters were asked for, and the HTTP contract of a subset run.
  Raw record: `per-source-rerun-2026-09-16.json` (script: `/tmp/b06_bench.py`, not committed).
- **Live browser check** — the shipped UI on the local stack (docker compose, database
  `spago`), clicking the retry control against real upstream sources.

## Why this was measured

The claim B-06 makes is a *negative* one: a retry of one source must not touch the others.
That is exactly the kind of claim a screen cannot show, so the fixture run diffs the database
before and after each retry, and the live run re-reads the same rows through the API.

## Results — fixture-only: what a subset run writes

One target (`TSLP`), three sources. All three are asked first, then `bindingdb` alone.

| Run | Wall | Upstream requests the adapters were asked for | Retrieval rows changed | Candidate rows re-dated | Measurements |
| --- | --- | --- | --- | --- | --- |
| Full run (all three) | 86.5 ms | chembl 3 · bindingdb 1 · pubchem 1 | 3 written (first run) | 5 (all, first run) | 5 |
| Retry `bindingdb`, which fails | 3.7 ms | **chembl 0 · bindingdb 1 · pubchem 0** | **bindingdb only** | bindingdb 0 · chembl 0 | 5 → 5 |
| Retry `bindingdb`, which answers | 13.2 ms | **chembl 0 · bindingdb 1 · pubchem 0** | **bindingdb only** | bindingdb 2 (its own) · chembl 0 | 5 → 5 |

The retry's changed fields are `status`, `records_seen`, `records_kept`, `latency_ms`,
`retrieved_at` — on the one row the retry produced. `chembl` and `pubchem` report
`changed_fields: []` on both retries: their status, counts, latency, checksum and
`retrieved_at` are byte-identical before and after.

> Correction, 2026-09-16 (B-23 round). The retry *also* rewrites the asked row's
> `query`, `pages_fetched`, `dataset_version`, `source_version` and `checksum`. That
> was not true when this record was written: the upsert never updated those columns,
> so a source re-asked through a *different access path* kept the first run's ask and
> identity (a local BindingDB snapshot after a REST call still read
> `bindingdb-rest` / `bindingdb:2026-09-15` with a REST-only `query`). The B-23
> acceptance run found it; `discovery._persist_retrieval` now updates them, and
> `test_a_snapshot_run_after_a_rest_run_relabels_the_retrieval` pins it. The fixture
> table above is unaffected for the *unasked* sources, which this record is about;
> for an asked source, "only that source's row changes" is still the claim, now with
> the whole row.

The failing retry leaves the stored rows in place (5 candidate rows before and after) and
retracts nothing — a failed ask establishes no absence (`AGENTS.md` §11); the successful
retry re-dates only its own two rows and still stores 5, not 7. The verdict counts 3
compounds before and after the failing retry, because it is computed on read from every
stored row, not from the run that just happened.

## Results — HTTP contract

`POST /api/v1/targets/discover {"sources": ["bindingdb"]}` → 200, 58.7 ms, 4.8 KB:

| Row | Status | `requested_in_run` |
| --- | --- | --- |
| `chembl` | `complete` (stored) | `false` |
| `bindingdb` | `failed` (this run) | `true` |
| `pubchem` | `complete` (stored) | `false` |

The coverage read (`GET /api/v1/targets/{id}/coverage`) reports the same three statuses with
`requested_in_run: null` — it describes no run. `{"sources": []}` is refused 422:
`Name at least one source; a run that asks nothing would only re-date the target.`

## Results — live browser check (local stack, real upstream)

Two surfaces, chosen for the two retryable statuses:

| Target | Retryable chip | Click result | The others |
| --- | --- | --- | --- |
| IL6R | `bindingdb failed` | stayed `failed` (`9/16/2026, 6:36:42 PM · 1 page · 0 records seen · 1.5 s`) | `chembl complete · 1 kept`, `pubchem complete` — chips unchanged |
| IL6 | `pubchem partial` | still `partial` (`0 kept of 48 seen`) — the 25-assay budget still bounds it | `chembl complete · 166 kept · 246 not qualifying`, `bindingdb complete · 9 kept` |

The run note names the asked set on both surfaces — *"Asked pubchem only: partial · 0 kept of
48 seen · 0 candidate row(s) stored by this run. chembl, bindingdb not asked again — their
stored outcomes are unchanged."* — and the cost line states what the retry spends from *that
source's own last run*, not an estimate: *"pubchem — last run 9/16/2026, 6:37:54 PM · 0 pages
· 48 records seen · 1.0 s."* Healthy chips (`complete`) offered no retry control at all; only
one retry button existed on each surface.

Database re-read after the IL6 click (`source_retrievals`):

| Source | Status | `retrieved_at` |
| --- | --- | --- |
| `bindingdb` | `complete` | `2026-09-16 07:07:15.686334+00` *(untouched)* |
| `chembl` | `complete` | `2026-09-16 07:07:13.829584+00` *(untouched)* |
| `pubchem` | `partial` | `2026-09-16 10:37:54.994166+00` *(this retry)* |

`target_candidates` stayed at 166 chembl + 9 bindingdb rows with their original retrieval
times, and `measurements` was 3666 before and after. Settled screenshots
(`/tmp/b06-il6r-before-retry.png`, `/tmp/b06-il6-after-partial-retry.png`) were the reference
for the text above; they are not committed.

## What this does and does not prove

- Proves: on this checkout, a subset run rewrites only the retrieval row it produced and only
  that source's candidate rows; unasked sources keep their stored outcome, counts and
  retrieval times; the API marks the asked rows (`requested_in_run`) and refuses an empty
  ask; the UI offers the control only for `failed`/`partial` and displays that source's own
  last-run cost.
- Does not prove: upstream wall time (the fixture adapters answer from recorded payloads) or
  hosted-deployment timings. The live check's outcomes (`failed`, `partial`) are the upstream
  states that were reachable at that moment, not a claim about the sources' content.
- Out of scope by decision (D5): retracting rows a *complete* refresh no longer returns —
  recorded as B-30 in `docs/plans/backlog.md`, with the reasoning.
