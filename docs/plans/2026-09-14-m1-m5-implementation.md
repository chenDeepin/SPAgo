# M1–M5 Implementation Record

Date: 2026-09-14. Status: DONE (implemented and verified same day, following M0).
Parent plan: `2026-09-14-m0-foundation.md`. Contracts: root `PROMPT.md`, `docs/design/2026-09-14-ui-direction.md`.

Each milestone below is implemented, tested, and verified against the running
compose stack unless explicitly noted. M6 (PDF/OCSR) remains excluded per
PROMPT.md §14 ("not MVP scope").

## M1 — Patent Chemistry Viewer

- Migration `0002_projects`: `project_items` with partial unique indexes;
  family saves and compound saves are separate idempotent scopes.
- API: projects CRUD (`/api/v1/projects...`), save-scope (`POST /projects/{id}/items`,
  returns created vs already-present), export (`POST /api/v1/export`, csv|sdf,
  selection or family/document scope, ≤5000-row synchronous cap documented).
- Export keeps patent numbers, `DOC:LABEL` pairs, evidence record ids,
  provenance states, dataset version; SDF written by RDKit and re-parsed in tests.
- UI: checkbox column (bulk selection separate from row inspection),
  Save-to-project dialog (scope radio, project select or create, dataset note,
  saved / already-saved / retry states), Export menu (4 actions), structure
  detail drawer (large depiction + copyable identity).
- Verified in browser: selection → save → idempotent re-save ("Already saved —
  nothing was duplicated."), CSV download event, drawer screenshot.

## M2 — Structure Search

- Migration `0003_structure_search`: `molecule`-typed column `m` (Debian
  cartridge 2022.09 names the type `mol`), GIST index for substructure, GIN
  fingerprint index; seeder populates `m` on every compound upsert.
- Service: exact (isomeric InChIKey equality), substructure (cartridge `@>`
  with chirality-aware RDKit re-check when the query specifies stereo — the
  cartridge operator matches constitution only), similarity (explicit
  `tanimoto_sml >= threshold`; the `%` operator is fixed at 0.5 in this
  cartridge and would silently drop lower thresholds). Molecule filters
  (MW/HBD/HBA/LogP) combine with structure queries.
- API: `POST /families/{id}/structure-search` (422 with reason for
  invalid/empty queries, 404 unknown family).
- Chemistry regression tests (AGENTS §28): alternate-SMILES identity,
  stereoisomer distinction, substructure positive/negative, inverted-stereo
  non-match, similarity bands and threshold clamping, malformed queries.
- UI: Structure ▾ dialog — SMILES draft input, mode radios, fixed scope
  ("Current family"), static "Preserve where specified", similarity threshold
  slider, Run-search-only execution, results chip (mode · scope · query · N ·
  Remove). Verified in browser.
- **Documented deviation**: embedded Ketcher editor deferred. ketcher-react
  2.28 and 3.14 both crash at mount in the Vite production build
  (`require is not defined` in 2.x; `translateAbs` undefined in 3.x after
  CJS interop fixes). M2 ships SMILES paste input; the dialog keeps every
  interaction contract; Ketcher returns once packaging is resolved.

## M3 — Bioactivity / SAR

- Migration `0004_bioactivity`: `targets`, `assays`, `measurements` (typed,
  provenance-carrying, unique per compound+assay+type+source record) and
  `compounds.scaffold` (Murcko, computed by RDKit at seed).
- Fixture: `bioactivity/bioactivity_demo_fixture.parquet` (synthetic, 6
  measurements across 2 assays; same-compound/different-assay is kept
  separate by design), regenerated with checksum manifest.
- Adapters: `BioactivitySource` contract; fixture adapter; **ChEMBL adapter**
  (official web services, cached/rate-limited/timeout, contract-tested with
  sealed responses via httpx MockTransport; failures become envelope warnings);
  **BindingDB adapter** (reads user-provided TSV downloads; no crawling).
  Neither live adapter is wired into the demo seed — no network in tests.
- API: activity summaries embedded in family compounds (and per-compound
  endpoint). UI: Activity column ("none shown" ≠ inactive), Bioactivity section
  in the evidence panel with per-assay provenance and the no-ranking note,
  Scaffold ▾ SAR mode (sort + scaffold display, group breaks).
- Verified in browser: naproxen shows 2 measurements from different assays;
  summary/labels correct.

## M4 — Chrome Companion (thin context bridge)

- `apps/chrome-extension/`: MV3 manifest (side panel, activeTab, storage),
  content script restricted to espacenet.com/patents.google.com that reads
  **only the URL** and forwards a detected publication number; service worker
  relays to session storage; side panel deep-links `?q=<pubnum>` into SPAgo
  with a configurable base URL.
- `check.js` verifies manifest shape, JS syntax, and the detection contract
  (Google Patents path, Espacenet `pn=` query, path form, negatives) — all
  pass. **Not verified**: loading the extension in Chrome (no extension host
  in this environment); recorded as the M4 gap.

## M5 — Evidence-Grounded AI

- Migration `0005_ai_analyses`: persisted analyses with provider, kind,
  citations (jsonb), provenance state.
- `services/ai.py`: `SummaryProvider` protocol; default
  **offline-extractive** provider assembles summaries verbatim from stored
  records (family/doc/compound counts, scaffolds, per-assay measurements,
  ingestion issues) with evidence citations — output labeled
  `machine_extracted`; real LLM providers behind the same protocol must label
  `llm_inferred`. Query planner is deterministic identifier parsing only;
  everything else is reported unresolved (PROMPT.md §12).
- API: `POST /families/{id}/summary` (stable id: same data reuses the stored
  analysis), `POST /ai/plan`.
- UI: Evidence | AI tabs inside the inspector (no new permanent panel); AI tab
  shows provider + provenance chip, summary text, citation count, and the
  no-LLM-configured note. Verified in browser.

## Verification summary

- `rtk pytest`: **88 passed, 0 failed, 0 skipped** (chemistry correctness,
  adapters incl. sealed ChEMBL/BindingDB, DuckDB, migrations, seed idempotency,
  M1–M5 API/DB integration).
- Frontend: `tsc -b && vite build` clean; Ketcher removed from dependencies
  (deferred); main bundle ≈ 248 KB / 77 KB gzip.
- Full stack `docker compose up -d --build` healthy; migrations 1–5 applied at
  container start; live endpoint checks passed for every milestone.
- Browser sessions verified M1–M5 workflows with screenshots.
- Benchmarks re-measured post-M3/M5 (`benchmarks/m0-baseline.json`):
  patent lookup p50 1.95 ms, compounds page (with activity) p50 4.99 ms /
  9.1 KB, depiction 1.48 ms cold.

## Known limitations / gaps

- Ketcher embedding deferred (see M2 deviation above).
- Chrome extension not loaded in a real Chrome instance (no host here).
- No live ChEMBL/BindingDB network call was made from tests; adapters are
  contract-tested with sealed fixtures and env-gated live runs remain future work.
- Export beyond 5000 rows requires the persisted background-job mechanism
  (documented, not needed at fixture scale).
- M6 (PDF/OCSR) intentionally not started.
