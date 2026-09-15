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
