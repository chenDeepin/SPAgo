# M0 Foundation — Implementation Plan

Date: 2026-09-14. Status: DONE (implemented and verified same day). Scope: Milestone 0 from root `PROMPT.md` §14/§20, with the UI contract from `docs/design/2026-09-14-ui-direction.md` (M0/M1 CORE band).

This plan is the active handoff for the first staged build. It does not replace `PROMPT.md`.

## Verification record (2026-09-14)

Environment: Python 3.10.12 (local venv), Node 22.22.0 (nvm), Docker 29 + Compose 2.40, no local PostgreSQL (Docker only). Shell commands run through `rtk`.

- `pytest`: **41 passed, 0 failed, 0 skipped** (`tests/test_chemistry.py`, `test_adapters.py`, `test_bulk.py`, `test_integration_pg.py` — the latter against a scratch database in the compose `db` container; PostgreSQL+RDKit were reachable, so no tests were skipped).
- Frontend: `tsc -b && vite build` clean (strict mode), bundle ≈ 226 KB / 71 KB gzip.
- Full stack: `docker compose up -d --build` → `db` healthy, `app` healthy; `/healthz` reports database up, chemistry ok, rdkit_cartridge installed, dataset demo-fixture-v1, 1 recorded ingestion issue.
- Seed inside the container: 1 family / 3 documents / 10 compounds / 12 mentions / 12 evidence / 1 issue (malformed SMILES recorded, never shown as a compound).
- API checks on the compose stack: patent lookup, family overview, paged compounds (limit cap at 500), document scope, depiction SVG (cached), evidence, bulk DuckDB counts, 404 JSON, frontend served from the same origin.
- Browser verification (in-app browser against `http://localhost:8000`, viewport 1440×900 and 1024×800, compose stack, session-fresh pages):
  - initial empty state with demo hint; demo dataset badge in top bar;
  - search by button and by Enter → family sidebar (per-document counts 5/4/3) + table of 10 deduped compounds with RDKit depictions;
  - aspirin row shows both occurrences ("Example 01 · DEMO-PATENT-A", "Compound 12 · DEMO-PATENT-B") — labels never merge identities;
  - row click → evidence inspector: occurrence switcher, Machine-extracted provenance chip, field list with honest "Not provided", excerpt card, no fake source link;
  - reload with `?q=…&c=…` restores family, selection, and evidence panel;
  - document scope via sidebar updates table and URL (`&doc=…`, 4 compounds for DEMO-PATENT-A);
  - unknown number → inline not-found error, input kept for retry;
  - empty input → inline validation message (verified with real keyboard input; Playwright `fill("")` on a controlled input was the earlier false negative);
  - Escape closes the inspector and returns focus to the selected row;
  - ≤1024px: evidence panel becomes a fixed overlay (table keeps its space); screenshots captured for the workspace and the overlay state.
  - Issues found and fixed during browser verification: lazy depiction images hidden with `display:none` never loaded (replaced with opacity-swap layout-box approach); explicit Enter submit handler added; focus-return queried before clearing selection; overlay CSS was defined but never applied (now a media query).
- Benchmarks: `services/core/benchmarks/run_benchmarks.py` against the compose stack; committed baseline `benchmarks/m0-baseline.json` (patent lookup p50 2.17 ms, compounds page p50 6.67 ms, depiction cold 3.39 ms / warm p50 1.57 ms, payloads ≤ 8 KB; see `benchmarks/README.md`).

Not verified / known gaps:

- No end-to-end browser test automation exists yet (manual in-app browser session only).
- `rtk git diff --check` run at closing; no PostgreSQL migration downgrade path (forward-only by design).
- Depiction cache grows unbounded in `spago-depiction-cache` volume at M0 scale; eviction is future work.
- The `data/fixtures` Parquet files are generated (committed); regenerate with `data/fixtures/scripts/build_fixtures.py` if the generator changes.

---

## Goal

One-command local startup (`docker compose up -d --build`) of a working vertical slice:

```text
patent publication number → patent family + documents → compound list (server-paged)
→ lazy RDKit depictions → evidence panel with provenance → benchmark baseline
```

M0 boundary (per design doc scope table):

- No save-to-project UI (M1), no CSV/SDF export (M1), no structure search editor (M2),
  no bioactivity (M3), no extension (M4), no AI (M5), no PDF/OCSR (M6).
- The UI must not show operable controls for features that do not exist yet.

## Deliverables

1. **Architecture docs** — `docs/architecture/overview.md`, `docs/adr/0001-m0-foundation-data-path.md`.
2. **Repo infra** — `.gitignore`, `.env.example`, `.dockerignore`, `docker-compose.yml`, DB image (PostgreSQL 15 + RDKit cartridge from Debian bookworm), app image (multi-stage: Node build of web → Python runtime).
3. **Synthetic fixture** — `data/fixtures/` with deterministic generator script (`build_fixtures.py`), SureChEMBL-like Parquet + patent metadata Parquet, provenance README. All identifiers synthetic (`DEMO-PATENT-A/B/C`, family `DEMO-FAMILY-1`).
4. **Backend** `services/core` (FastAPI, Python ≥3.10):
   - `domain/` typed models incl. provenance states (`source_fact`, `database_curated`, `machine_extracted`, `llm_inferred`, `user_curated`).
   - `adapters/` contract (`PatentSource` / `ChemicalPatentSource` + source envelope: name, version, dataset version, retrieved-at, warnings) + fixture adapter reading Parquet via DuckDB.
   - `chemistry/` RDKit engine: parse, canonicalize, InChIKey, descriptors, stereo detection, validation issues, SVG depiction.
   - `queries/` DuckDB-over-Parquet bulk layer (workload A) kept separate from PG state (workload C).
   - `db/` SQLAlchemy engine + plain-SQL versioned migration runner (`migrations/*.sql`, tracked in `schema_migrations`).
   - `seed.py` idempotent CLI: adapter → RDKit normalization → PG upsert (dedupe by InChIKey; multiple mentions preserved; malformed SMILES recorded as warnings, not compounds).
   - `api/` routes: `/healthz`, `/api/v1/patents/{pn}`, `/api/v1/families/{id}`, `/api/v1/families/{id}/compounds` (default page 100, hard cap 500, server-side), `/api/v1/compounds/{id}`, `/api/v1/compounds/{id}/depiction` (lazy SVG + disk cache), `/api/v1/compounds/{id}/evidence`, `/api/v1/bulk/compound-counts` (DuckDB proof), `/api/v1/datasets/info`.
5. **Frontend** `apps/web` (React + TS + Vite + TanStack Query/Table/Virtual, no UI framework, design tokens from UI direction doc): search row with cancel + stale-response protection, family sidebar with document scope, virtualized compound table with lazy depictions, evidence inspector (right, 380px; overlay < 1024px), all statuses from the design doc state table, URL state (`?q=&doc=&c=`), keyboard support. No fake save/export buttons.
6. **Tests** `services/core/tests`: chemistry correctness (real RDKit), adapter contract, DuckDB bulk, migrations + seed + API integration (Postgres-gated, skip with reason when unavailable).
7. **Benchmarks** `services/core/benchmarks/run_benchmarks.py`: patent lookup, compounds query, depiction cold/warm, DuckDB bulk, payload sizes → JSON + committed baseline summary.
8. **Docs** — README status section, PROMPT.md handoff pointer, implemented-vs-stubbed record (this plan updated to DONE with results).

## Architecture decisions (short form; detail in ADR-0001)

- Modular monolith; two containers (`db`, `app`) — no Redis/Kafka/Celery/etc.
- DB image built from `debian:bookworm-slim` + Debian `postgresql-15` + `postgresql-15-rdkit` (distro-consistent cartridge; no trusted third-party PG+RDKit image exists).
- Migration runner: plain SQL files + small Python runner, not Alembic (transparent, zero-dep; revisit if migration complexity grows).
- Fixture data path: Parquet → adapter (DuckDB) → RDKit normalization → PostgreSQL. Interactive serving is PG-only; DuckDB layer exercised by `/api/v1/bulk/compound-counts`, tests, and benchmarks.
- Depictions generated server-side by RDKit (design doc: structures must come from backend RDKit, never drawn client-side).
- Provenance: fixture records are `machine_extracted` with `extraction_method="surechembl_simplified_fixture"`, `dataset_version="demo-fixture-v1"`; synthetic nature labeled in UI ("Demo dataset" badge + footer note).

## Verification plan

- `rtk pytest` (unit + chemistry + adapter + DuckDB; PG-gated integration).
- Frontend `tsc` + `vite build` with Node 22.
- Full stack via `docker compose up -d --build`; then `curl /healthz`, patent/compounds/evidence/depiction endpoints.
- Browser check of the search → family → compounds → evidence workflow (screenshot evidence), per AGENTS.md §36.
- Benchmarks produce a baseline report.
- `rtk git diff --check`.

## Constraints / risks

- Node 12 is the system default; use nvm Node 22 for the web build (recorded here for reproducibility).
- No local psql; PG verification happens in Docker only — recorded as such in reports.
- First `docker compose build` is heavy (RDKit wheel ~100 MB); acceptable for M0.
