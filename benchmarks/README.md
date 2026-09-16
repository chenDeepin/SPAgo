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
