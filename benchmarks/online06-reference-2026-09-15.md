# ONLINE-06 potency-reference verdict — cost record, 2026-09-15

What this measures: the serving cost of the new potency-reference read path
(`GET /targets/{id}/reference`, its use in `POST /targets/discover` and in the
coverage matrix), the candidate/measurement pages that carry the new class column,
and the upstream cost the ChEMBL document lookup adds to an investigation.

Raw numbers: `online06-reference-2026-09-15.json` (script-generated).

## How this was produced

Local stack from the current checkout:

```bash
docker compose up -d --build app          # app on 127.0.0.1:8000, PG15 + RDKit
```

Data: the live ONLINE-00 TSLP investigation stored in the same database —
target `0cd78fd9-082b-5afb-b554-80835ecc3b35` (`TSLP`, UniProt `Q969D9`),
69 candidate compounds, 120 measurement rows (111 ChEMBL, 3 BindingDB, 6 synthetic
demo fixture), 1 compound in the default small-molecule scope.

Method: inline Python (stdlib `urllib`), 3 warm-up requests per endpoint then 20
measured requests; p50/p95 over those 20. Payload size is the last measured response
body. No concurrent load, no tuning.

## Serving cost

| Read path | payload | p50 | p95 |
| --- | --- | --- | --- |
| `GET /targets/{id}/reference` (deployment policy) | 1,064 B | 4.51 ms | 5.27 ms |
| `GET /targets/{id}/reference?activity_threshold_nm=1000` | 1,061 B | 4.42 ms | 5.10 ms |
| `GET /targets/{id}/reference?include_all_modalities=true` | 3,091 B | 4.54 ms | 5.48 ms |
| `GET /targets/{id}/candidates` (default scope, 1 row) | 1,173 B | 4.76 ms | 5.54 ms |
| `GET /targets/{id}/candidates?include_all_modalities=true` (69 rows) | 57,221 B | 8.40 ms | 9.95 ms |
| `GET /targets/{id}/candidates?activity_threshold_nm=1000` (1 row) | 1,171 B | 5.03 ms | 5.81 ms |
| `GET /targets/{id}/measurements?limit=200&compound_id=…` | 1,338 B | 2.86 ms | 3.09 ms |
| `GET /targets/coverage/matrix` (3 stored targets) | 3,165 B | 5.21 ms | 5.91 ms |

Reading of these numbers:

- **The verdict is one bounded aggregate read.** ~4.5 ms p50 including the HTTP round
  trip, under the deployment policy and under an explicit threshold override alike.
  A threshold change is therefore interactive, and no class can be stale afterwards
  because the recomputation reads the stored rows again (AGENTS.md §10) — the class is
  never persisted, so no migration or backfill exists for the policy.
- **The all-modalities candidate page is the heaviest new read**: 69 rows → 57.2 KB
  (≈ 830 B/row, structure depictions excluded). At the 500-row ordinary maximum
  (AGENTS.md §13) that extrapolates to ≈ 400 KB, which is why the default page size
  stays 100 and the modality scope toggle is an explicit user action, not a default.
- These are the same order of magnitude as the M0 fixture baseline (single-digit ms
  reads), on a target whose stored rows are 10× the fixture.

## Upstream cost added by the ChEMBL document lookup

`POST /targets/discover` for the same stored target, two consecutive live runs:

| run | wall | ChEMBL | BindingDB | PubChem |
| --- | --- | --- | --- | --- |
| 1 | 4,331 ms | 2,446 ms | 779 ms | 939 ms |
| 2 | 5,077 ms | 2,703 ms | 821 ms | 1,392 ms |

The new upstream request is one bounded ChEMBL document batch (≤50 ids per request,
≤8 requests per investigation). Timed directly for TSLP's 3 distinct documents
(`document.json?document_chembl_id__in=…`, 593 B): **0.76 s and 1.17 s**.

- ONLINE-00's record for the same target lists ChEMBL at 754 ms. Re-timing the
  identical activity page (`activity.json?target_chembl_id=CHEMBL3712931…`, 103 KB)
  today gives 2.39 s and 3.02 s, so the visible difference is source/network
  variance on the dominant activity fetch, **not** the document lookup. This is not a
  controlled before/after comparison and is not presented as one.
- The document cost is bounded by the batch constants, not by the number of
  activities: 114 activities and 3 documents cost one extra request. A target whose
  activities cite many distinct documents pays up to 8 batched requests, and the
  adapter reports how many lookups it skipped when the bound is reached.

## What is not covered

- No memory, concurrency or sustained-load measurement; single-user local stack.
- **The source-declared patent path was not exercised on live data.** All 111 live
  TSLP ChEMBL documents are journal articles, so the stored rows carry DOI/PMID and
  no patent number, and the browser pass could not show "source declares WO…". That
  rendering path is covered by `tests/test_online06_reference.py` and
  `tests/test_patent_numbers.py`, not by this record.
- Export and report generation were not re-timed this round.
- Fixture-scale and live-scale figures above are not capacity claims.
