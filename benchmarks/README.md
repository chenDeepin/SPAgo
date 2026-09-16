# Benchmarks

Performance baselines for SPAgo (PROMPT.md §17: never claim optimization without
measurement; a milestone must retain its benchmark).

## Baseline

`m0-baseline.json` — measured 2026-09-14 against the full
`docker compose up -d --build` stack (PostgreSQL 15 + RDKit cartridge with M3
schema: scaffolds + measurements, app container, synthetic fixture dataset
`demo-fixture-v1`, 10 compounds / 12 mentions / 6 measurements).

| Measurement | p50 | p95 | errors |
| --- | --- | --- | --- |
| Patent lookup (API) | 1.95 ms | 2.63 ms | 0 |
| Family compounds page (default 100, incl. activity) | 4.99 ms | 5.99 ms | 0 |
| Depiction, cold generation (RDKit SVG) | 1.48 ms (single) | — | 0 |
| Depiction, warm (disk cache) | 1.15 ms | 1.37 ms | 0 |
| Evidence fetch | 1.32 ms | 1.74 ms | 0 |
| Bulk DuckDB counts (Parquet) | 4.50 ms | 4.86 ms | 0 |
| Document-scoped compounds | 4.49 ms | 5.56 ms | 0 |

Payload sizes: compounds page ≈ 9.1 KB (activity included), depiction SVG ≈ 7.9 KB,
evidence list ≈ 0.7 KB.

These numbers are from a tiny synthetic fixture. They exist so regressions become
measurable — they are **not** capacity claims for bulk datasets.

## Later measurements

- `paging-measurement-2026-09-14.md` — 150-row synthetic paging fixture (UI-03 round).
- `paging-beyond-cap-2026-09-15.md` — 601-row synthetic fixture on an isolated stack:
  offset paging beyond the 500-row response cap, paging payload/latency, depiction and
  scroll cost while 601 rows are loaded (UI-07/UI-08 round). A different fixture from the
  baseline above, so the payload figures are not directly comparable.
- `real-source-2026-09-15.md` — first real-data cases (SureChEMBL losartan/sildenafil
  families on an isolated stack): remote extraction timings and serving latency for
  patent lookup, paging, substructure search and family export on 961 real compounds.

- `review-2026-09-15.json` — post-review synthetic check, current local app and
  isolated DB with two families sharing 10 identities. Patent lookup p50/p95
  3.05/3.68 ms; family page 6.30/7.90 ms, 9,118-byte JSON; no benchmark errors.
  This has different data and runtime from M0 and the real-source run: it is
  not a controlled performance comparison or a production-scale claim. Current
  real-scale regression and memory measurements remain an acceptance gap.
- `online06-reference-2026-09-15.md` (raw: `...json`) — the ONLINE-06
  potency-reference read path (verdict, class-carrying candidate page, coverage
  matrix) on the live TSLP investigation stored in the local stack, plus the
  bounded ChEMBL document-lookup cost that an investigation now pays.
- `online00-chembl-projection-2026-09-16.md` (raw: `...json`) — what the ChEMBL
  activity field projection buys: about −42 % transferred bytes per page with **no**
  latency improvement (the projected pages were equal or slower). Produced by
  `services/core/benchmarks/chembl_projection.py`; it is an upstream transfer
  measurement, not application latency.
- `cohort-coverage-2026-09-16.md` (raw: `...json`) — the acceptance cohort
  (TSLP, CD40LG, IL-6 `P05231`, IL-6R `P08887`, EGFR) re-recorded on this build by
  `scripts/cohort_coverage.py` through the shipped read paths: per-source status,
  record counts, per-source `latency_ms` (0.7–50.9 s) and the potency verdict under
  `potency-gate-v1`. Supersedes `online00-coverage-2026-09-15.md` for the cohort; both
  are kept because the earlier one is the record the 2026-09-15 claims were made on.
- `cohort-coverage-2026-09-16-accept.md` (raw: `...-accept.json`) — the same cohort
  re-recorded on the **hosted-shape rehearsal stack** (`spago-accept`, seed `none`,
  auth required, real provider) for `docs/online-capability.md` §6 criterion 5. Same
  nine source rows and the same 10 µM threshold; the difference is the environment,
  and it is the matrix the 2026-09-16 rehearsal record cites.
- `online08-structure-editor-2026-09-16.md` — the embedded Ketcher editor: what the
  first open of the structure dialog transfers (20.3 MB raw / 4.95 MB gzip, the entry
  bundle 0.33 MB), time from the click to a usable editor (0.83–0.86 s on loopback),
  and the statement that the shipped container serves assets uncompressed. Comes from
  the app's own access log plus CDP timing, not from bundle listings.
- `online07-supplements-2026-09-15.md` (raw: `...json`) — the ONLINE-07 hand-added
  literature rows: the import write path (normalization + compound upsert + per-row
  outcome), the remark listing, and the verdict/candidate reads after an import.
  An import makes no upstream call, so this record has no external-latency table.
- `reference-declarations-2026-09-16.md` (raw: `...json`) — B-02: how far the
  source's own document reference reaches, measured live and read-only over the
  acceptance cohort through the shipped ChEMBL adapter (39 s for all five targets,
  2,696 kept records). Per target it reports the records returned, excluded and kept,
  and a disjoint tally of the kept records' reference outcomes. The honest headline:
  only IL-6 yields patent numbers (135 of its 166 kept records, the rest DOI-only),
  while 1,210 of EGFR's 2,397 cite a document the source does not return and
  CHEMBL203 stopped at the 2,000-activity bound. Nothing was written to the database,
  so these are retrieval-scoped facts, not corpus occurrences.
- `patent-source-declarations-2026-09-16.md` (raw: `...json`) — B-24: the patent-led
  read path, measured live on the local stack. Asking for `US10508115` resolves the
  source's document `CHEMBL5727449` (declared patent `US-10508115-B2`) and stores 134
  declared records for 73 compounds out of 402 seen (268 kinetic rows have no numeric
  value and are counted, not dropped); `US12345678` returns `empty` **with the match
  rule** in 5.9 s. The exports are checked in the same run (CSV 135 lines, SDF 134
  records, all parsed back). Row payloads are deliberately not committed; the counts,
  the CSV header and the export checks are.
- `patent-coverage-2026-09-16.md` (raw: `...json`) — B-26: the per-publication coverage
  audit, measured live on the local stack. A five-publication request answers in 4.4 ms
  p50 / 5.0 ms p95 (11.7 KB), the 50-publication bound in 5.5 ms p50 (81.1 KB), and the
  three exports carry the rule in a header and in the file. One live request shows the
  four states kept apart — `corpus` (WO-2020-123456-A), `declared` from a stored lookup
  *and* from target-led rows (US10508115: 73 compounds; US10919895: 29, target-led only),
  `asked_empty` (WO2020999999, a stored ChEMBL `empty`), and `not_queried` (US9999999,
  all three legs named). No source is called: every leg is a stored-row read.
- `tolerant-lookup-2026-09-16.md` (raw: `...json`) — B-03: the cost of answering a
  typed publication number by normalizing it and scanning the metadata table, on a
  synthetic 50 000-document corpus (12 500 families of four) added to the rehearsal
  database and removed again. Exact path 1.35 ms (unchanged), tolerant hit and miss
  both ≈ 155 ms, split as 84 ms read + 63 ms `patent_tokens` comparison. Produced by
  `scripts/tolerant_lookup_benchmark.py`. An earlier attempt that put all 50 000
  documents in one family measured the family overview instead of the lookup (294 ms
  for an indexed hit) and is recorded in the file as the reason the family size is
  stated.
- `per-source-rerun-2026-09-16.md` (raw: `...json`) — B-06: what a one-source re-run
  writes, in two shapes stated separately. Fixture-only (recorded payloads, real
  PostgreSQL): one retry spends **1** upstream request for that source and **0** for the
  other two, changes only that source's retrieval row (status/counts/latency/`retrieved_at`)
  and re-dates only its own candidate rows (2 when it answers, 0 when it fails), leaving
  measurements and the verdict unchanged; the HTTP contract marks the asked rows
  (`requested_in_run`) and refuses an empty ask 422. Live browser check on the local
  stack: IL6R's `bindingdb failed` and IL6's `pubchem partial` retried from the header
  with the other chips' stored outcomes — including their `retrieved_at` — identical
  afterwards. Upstream wall time is **not** measured (no source is called in the fixture
  run); hosted timings are not claimed.
- `bindingdb-snapshot-2026-09-16.md` (raw: `...json`; the pre-fix run is kept as
  `bindingdb-snapshot-il6-2026-09-16-before-fix.json`) — B-23: one full pass over the
  operator's real 8.98 GB / 3,237,052-row BindingDB release answering IL6 in 113.2 s
  with no upstream call (153 kept records, 153 matched by UniProt accession, 0 by
  name; digest computed in the same pass — a separate `sha256sum` costs 20.56 s). The
  stored retrieval names the file (release, sha256, bytes, rows scanned, match mode)
  and every measurement says `bindingdb-snapshot:2609`; a live `--max-rows` dry-run
  shows a bound produces `partial`, exit 1 and **no** digest. Reconciliation against
  the stored REST rows: the endpoint's 9 compounds are a strict subset of the file's
  133, both paths' rows kept. The first pass exposed a defect the unit tests could not
  (the retrieval upsert never rewrote `query`/`source_version`/`dataset_version`/
  `checksum`, so the row still said `bindingdb-rest`) — fixed in the round and pinned
  by a regression test. Operator tooling on a workstation, not a hosted capability.
- `asset-compression-2026-09-16.md` — B-15: what the app itself now sends. The same
  container rebuilt with gzip in the process: the first open of the structure dialog
  transfers **5,234,921 B instead of 20,269,580 B** (3.87×; entry JS+CSS 392,253 →
  112,461 B), observed per asset with `curl` (`content-encoding: gzip`,
  `vary: Accept-Encoding`) and confirmed in the browser's own resource timing, with
  `identity` requests unchanged. The Indigo WASM is measured server-side only (the
  worker revalidated its cached copy in the browser run, and page-level timing does
  not see the worker's fetch). Level 6 over 9 (106 ms vs 234 ms for the dialog chunk),
  and `/healthz` stayed at 3.5–7.8 ms while three cold gzipped WASM transfers ran. The
  loopback editor-ready time is recorded as a **non-claim**.

## Reproduce

```bash
docker compose up -d --build
python services/core/benchmarks/run_benchmarks.py \
  --base-url http://localhost:8000 \
  --output benchmarks/results/m0-baseline.json
```

`benchmarks/results/` is gitignored; `m0-baseline.json` at this level is the
committed record for the milestone.

## Model evaluation (not an application latency benchmark)

`online01-llm-eval-2026-09-15.md` — live-endpoint summary baseline for ONLINE-01,
produced by `scripts/llm_summary_eval.py` through the shipped input builder and
retry policy. Raw runs: `...-run1.json` (3 requests per scope),
`...-run2.json` (3 per scope), `...-run3-after.json` (3 per scope, after the
citation-contract fix that the baseline itself identified), `...-run4.json`
(6 per scope, after the per-source ref fix: 18/18 answered). These numbers describe
model output acceptance, token cost and refusal classes; they are not comparable
with the application latencies above.

`online01-llm-eval-2026-09-16-sparse.md` (raw: `...-sparse.json`,
`...-sparse-before-fix.json`) — the sparse scope: a target with **no** source
retrievals. The before-fix run refused 0/2 (4 refusals) and exposed a citation gap
that affected the whole target scope (defect D9: the prompt requires citing
`reference:<id>`, which the validator did not allow); after the fix, 2/2 answered
with text that does not read the empty set as a negative result.

## Assistive-technology acceptance (not a latency benchmark)

`screen-reader-pass-2026-09-17.md` (raw stream:
`screen-reader-pass-2026-09-17-transcript.txt`) — the B-44 announcement pass: Orca
42.0 reading the two virtualized tables in Chrome 142 on a 1600×1000 X11 desktop,
with the reader's own utterances recorded per keyboard step. It records the defect
the pass found (a table announced as "1 row"), the fix (`role="cell"` on data-row
children) with a same-build before/after measured through the platform table
interface, the B-19 keyboard rules re-verified on the same build, and the limits —
including that Orca's own Ctrl+Alt+arrow table commands cannot be driven by
synthetic keys and stay untested.
