# Real-source measurements: SureChEMBL losartan/sildenafil cases (2026-09-15)

Scope: product-readiness PROD-01/PROD-05 (first real-data cases). Captured on
the isolated verification stack (containers `spago-verify-app`/`spago-verify-db`,
image built from this round's checkout), NOT the developer stack.

## Extraction (source → package)

| Step | Observation |
| --- | --- |
| Release | SureChEMBL bulk `2026-09-08` (EMBL-EBI FTP, CC BY 4.0), remote Parquet via HTTP range reads |
| Resolve `US-5153197-A` → family 27367728 (narrow column scan) | ~65–70 s |
| Family documents copy (4 patents) | ~30–60 s |
| Mapping rows by pruned `patent_id` (3,973 rows) | ~5 s |
| Compounds batched fetch (976 ids, batches of 100) | ~2–3 min |
| Whole losartan package | 4 docs / 3,973 map rows / 976 compounds |
| Whole sildenafil package (`US-5250534-A`, family 27265149) | 3 docs / 608 map rows / 196 compounds |

Operational note: one unbatched compounds query (subquery or a single huge IN
list) degraded to streaming the ~4 GB file and was abandoned; the batched
literal-IN approach is the implemented path (`scripts/extract_surechembl.py`),
with `--compounds` as an optional pre-downloaded local override.

## Serving (real data in PostgreSQL, 5 samples each)

| Operation | Best | p50 | Payload |
| --- | --- | --- | --- |
| Patent lookup `US-5153197-A` | 1.9 ms | 2.1 ms | 2.3 KiB |
| Compounds page 100 (of 961) | 17.0 ms | 17.4 ms | 141.1 KiB |
| Compounds page 500 (hard cap) | 55.9 ms | 58.7 ms | 716.1 KiB |
| Benzene substructure search (limit 100) | 86.4 ms | 93.4 ms | 144.3 KiB |
| Family export, 961 rows CSV | 244.8 ms | 247.6 ms | 745.9 KiB |

Import job (losartan, includes RDKit normalization of 976 structures): one
transaction, seconds-scale; idempotent re-import updates in place
(`tests/test_real_source_import.py` asserts row stability).

## Not measured

- Concurrent users, multi-worker serving, cold-start after cache loss.
- Larger real families (thousands of documents) — extraction time is dominated
  by the remote index scans and will grow; batching is per-100 ids.
- The demo-fixture numbers in `m0-baseline.json` and the 601-row synthetic
  paging record remain the regression baselines for those datasets.
