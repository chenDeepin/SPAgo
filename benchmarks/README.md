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

## Reproduce

```bash
docker compose up -d --build
python services/core/benchmarks/run_benchmarks.py \
  --base-url http://localhost:8000 \
  --output benchmarks/results/m0-baseline.json
```

`benchmarks/results/` is gitignored; `m0-baseline.json` at this level is the
committed record for the milestone.
