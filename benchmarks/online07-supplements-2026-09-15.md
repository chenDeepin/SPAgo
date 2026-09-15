# ONLINE-07 hand-added literature rows — cost record, 2026-09-15

What this measures: the serving cost of the one write path where a person supplies
scientific content directly (`POST /targets/{id}/supplements`), the read that lists
structure-less rows (`GET /targets/{id}/supplements/remarks`), and the effect a
supplement has on the reads that already existed (the potency verdict and the
candidate page).

Raw numbers: `online07-supplements-2026-09-15.json` (script-generated).

## How this was produced

Local stack from the current checkout:

```bash
docker compose up -d --build app          # app on 127.0.0.1:8000, PG15 + RDKit
```

Data: the live ONLINE-00 TSLP investigation in the same database — target
`0cd78fd9-082b-5afb-b554-80835ecc3b35` (`TSLP`, UniProt `Q969D9`) — plus the two rows
added by the ONLINE-07 acceptance pass: one compound row (merged with a structure
already in the corpus) and one structure-less remark.

Method: one inline Python process (stdlib `urllib`), 3 warm-up requests per endpoint
then 20 measured requests; p50/p95 over those 20. Payload size is the last measured
body. No concurrent load, no tuning. An import performs **no upstream call**, so there
is no external-latency component to separate here.

The two request bodies, exactly as sent (the compound row is the one already stored by
the browser pass; the remark row is the structure-less one):

```json
{"rows": [{"name": "ACCEPTANCE-ROW-1 (not a literature claim)",
           "note": "ONLINE-07 acceptance row: …",
           "smiles": "CC(C)Cc1ccc(C(C)C(=O)O)cc1",
           "activity_type": "IC50", "value": 250, "unit": "nM", "relation": "="}]}
{"rows": [{"name": "ACCEPTANCE-ROW-1 (not a literature claim)", "…": "as above"},
          {"name": "ACCEPTANCE-ROW-2 (structure not published)",
           "note": "ONLINE-07 acceptance row: …",
           "activity_type": "IC50", "value": 3, "unit": "nM", "relation": "="}]}
```

Endpoints timed, in order: `POST /api/v1/targets/{id}/supplements` (both bodies),
`GET /api/v1/targets/{id}/supplements/remarks`,
`GET /api/v1/targets/{id}/reference`, `GET /api/v1/targets/{id}/candidates`.

**Deviation from the runner convention:** `benchmarks/README.md` expects raw JSON to be
produced by a committed runner. This record's JSON was printed by that inline script
and committed as printed; no `online07` runner script exists, so reproducing it means
re-running the loop above rather than invoking a tool. Stated because the numbers
should be re-derivable, not taken on trust.

## Serving cost

| Call | payload | p50 | p95 |
| --- | --- | --- | --- |
| `POST /targets/{id}/supplements` (re-post of 1 stored row → update path) | 510 B | 7.21 ms | 19.09 ms |
| `POST /targets/{id}/supplements` (1 compound row + 1 structure-less remark) | 840 B | 7.73 ms | 8.96 ms |
| `GET /targets/{id}/supplements/remarks` (1 remark) | 457 B | 1.83 ms | 2.42 ms |
| `GET /targets/{id}/reference` (after the import: 1 remark, 1 user compound) | 2,299 B | 4.97 ms | 5.43 ms |
| `GET /targets/{id}/candidates` (default scope, 2 rows) | 1,876 B | 5.22 ms | 6.58 ms |

Reading of these numbers:

- **An import is interactive.** ~7.5 ms p50 for a two-row batch including RDKit
  normalization, modality classification and the compound upsert; the chemical work is
  not the cost driver at this size. The 19 ms p95 on the update path is a single slow
  sample on a stack that also serves the browser, not a shape change (the other 18
  samples were 6.8–8.7 ms).
- **The verdict cost is unchanged by a supplement.** 4.97 ms p50 vs 4.51 ms before the
  import in the ONLINE-06 record: the added remark costs one indexed count, and the
  added compound enters the same classified-row read as any other. The payload grew
  because the target now has a matching compound to report, not because the read is
  heavier.
- **A supplement is not a bulk-ingestion path.** The batch bound (200 rows) is a
  contract limit, not a throughput target, and nothing here competes with the
  bulk-dataset ingestion that AGENTS.md §22 keeps out of interactive requests.

## What these numbers do and do not say

They say: on this stack, with this stored state, an import answers in single-digit
milliseconds and does not make the reads around it heavier.

They do not say: anything about memory, concurrency or sustained load; anything about
the largest accepted batch (200 rows, not timed); anything about a bulk-ingestion
throughput (a supplement is not that path); or anything about export cost (the export
was inspected by content, not timed). They are single-user local-stack figures, not
capacity claims.

Two further scope notes: no live-source retrieval is involved in this path (stated
above so a reader does not look for an upstream table), and export after a supplement
was inspected by content (`provenance_states` = `machine_extracted|user_curated`), not
timed.
