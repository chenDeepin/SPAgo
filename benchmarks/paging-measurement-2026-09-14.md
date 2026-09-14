# Pagination & virtualization measurement — 2026-09-14

Round: UI review next round (UI-03 acceptance). Environment: same as
`m0-baseline.json` (docker compose stack, PostgreSQL 15 + RDKit cartridge,
synthetic paging fixture `paging-fixture-v1` with **150 compounds** in one
family, seeded temporarily into the dev database; removed afterwards by
`docker compose down -v`). The committed M0 baseline was **not** overwritten.

Raw numbers captured in the in-app browser at 1440×900 against
`http://localhost:8000` (session-fresh page, compose-served build of this
checkout):

## Server paging contract (UI-03)

| Request | Result |
| --- | --- |
| `GET /families/{id}/compounds?limit=100` | 89.7 KB, 100 items, `total: 150`, `limit: 100` |
| `GET /families/{id}/compounds?limit=500` | 135.3 KB, 150 items, `limit: 500` (hard cap) |
| `POST /families/{id}/structure-search` (substructure `C`, limit 100) | 89.8 KB, `total: 150`, 100 items |
| `?limit=99999` (both endpoints) | clamped to `limit: 500` server-side |
| Structure search offset=100 page | 50 items, disjoint keys from page 1 |

The UI footer shows the server total ("1–100 of 150"), and **Load more** fetches
the next server page (append; verified 150/150 in browser).

## Virtualization / lazy depiction / scroll

| Measurement | Value |
| --- | --- |
| DOM rows rendered at rest (150 loaded) | 13–14 (only visible + overscan) |
| Depiction requests before scroll (top of table) | 46 |
| Depiction requests after full step-scroll | 133 (< 150: rows never scrolled near are never fetched) |
| Full step-scroll duration (150 rows, 600 px steps, 60 ms waits) | ≈ 1.03 s |
| JS heap after scroll (`performance.memory.usedJSHeapSize`) | ≈ 163 MB |

Interpretation: payload per row ≈ 0.9 KB; depiction fetching stays tied to the
viewport during scrolling; DOM row count is bounded regardless of loaded rows.
These are fixture-scale regression markers, not capacity claims.

## UI-01/02/05 acceptance notes (same session)

- Closing the dialog while a search is in flight aborts the request; the
  previously applied filter chip is untouched (verified: stale 150-result
  response did not replace the `[Na+] · 1 result` chip).
- `[Na+]` passes the client boundary check and reaches RDKit; the server
  matches the sodium salicylate record (1 result).
- History: new queries push entries; `history.back()` restored
  `?q=DEMO-PATENT-A` (footer 1–10 of 10), `forward()` restored the paging
  family. Selection/scope changes replace the current entry.
