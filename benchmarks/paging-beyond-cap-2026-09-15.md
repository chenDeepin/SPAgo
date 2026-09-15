# Paging measurement: ordinary results beyond the 500-row cap (2026-09-15)

Scope: the UI-07/UI-08 repair round (`docs/plans/2026-09-14-ui-review-next-round.md`).
Captured against an **isolated** verification stack, not the developer stack.

## Environment

| Item | Value |
| --- | --- |
| Checkout | `f3da90c` + the working-tree changes of this round (backend, frontend, tests, mock tooling) |
| Images | `spago-app:m0` built from that checkout (`8b48aed6b8e8`, built 2026-09-15 ~01:28 +08:00); `spago-db:pg15-rdkit` |
| Containers | `spago-verify-app` (`127.0.0.1:8055`), `spago-verify-db`; isolated network `spago-verify-net` |
| Dataset | synthetic fixture `paging-501-fixture-v1`, family `CAP-FAMILY-1`, 601 unique compounds (ester pairs from two chain-length axes), 1 document, 601 evidence records, 0 measurements |
| Demo dataset | `demo-fixture-v1` (10 compounds) seeded alongside, unchanged by this round |
| Browser | ZCode in-app browser, viewports 1440×900, 1024×800, 760×800 |

The earlier baseline for 150-row paging is `benchmarks/paging-measurement-2026-09-14.md`;
it is kept unchanged. Values here are **not** directly comparable: the payload differs
because this fixture carries no activity rows.

## API response cost (server-side, 5 samples per page)

| Request | Payload | Best | Mean |
| --- | --- | --- | --- |
| `/compounds?limit=100&offset=0` | 67.7 KiB | 13.2 ms | 19.1 ms |
| `/compounds?limit=100&offset=500` | 68.1 KiB | 13.5 ms | 14.2 ms |
| `/compounds?limit=100&offset=600` (final 1-row page) | 0.8 KiB | 5.9 ms | 6.9 ms |
| `/compounds?limit=500&offset=0` (hard cap) | 341.0 KiB | 40.9 ms | 45.3 ms |
| cached molecule depiction (SVG, one compound) | 8.7 KiB | — | 1.4 ms |

Ordering stability and page disjointness across the 7 pages are asserted in
`services/core/tests/test_paging_beyond_cap.py` (not inferred from timings).

## Browser cost (1440×900, 601 rows loaded via 7 offset requests)

| Observation | Value |
| --- | --- |
| Requests issued for the family table | 7 (`offset=0,100,200,300,400,500,600`, each `limit=100`) |
| First screen depiction requests | 13 |
| DOM rows while 601 rows are loaded | 13 (virtualized; unchanged by page count) |
| Scrolling the full 601-row range | ≈1.25 s, 238 depiction requests total (depictions load as rows enter the viewport) |
| `performance.memory.usedJSHeapSize` after the scroll pass | 11.5 MB (Chrome-reported; different instrumentation from the historical 163 MB figure — not comparable) |
| Frontend bundle | 254.99 kB (78.81 kB gzip), was ≈249 kB (77 kB gzip) before this round |

## What this measurement does not cover

- No real SureChEMBL/OPS data: the fixture is synthetic and labeled as such in the UI header.
- No multi-worker or hosted deployment; no concurrent-user load.
- No latency budget claimed for row 501+ beyond the samples above.
- Depiction cold-generation cost and cache eviction were not re-measured this round.
