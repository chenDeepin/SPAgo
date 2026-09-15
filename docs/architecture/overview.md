# SPAgo Architecture Overview

Status: **implemented shape with open product acceptance gaps**, checked at `f3da90c`
plus existing uncommitted repairs on 2026-09-15. Current release scope is in
[the product-readiness plan](../plans/2026-09-15-product-readiness.md); prior repair
verification remains in `docs/plans/2026-09-14-ui-review-next-round.md`. History: the M0-only framing
is preserved in `docs/archive/2026-09-14-m0-foundation.md`; decisions in
`docs/adr/`. Source constraints: root `AGENTS.md`, `PROMPT.md`.

## Shape

SPAgo is a modular monolith deployed as two containers:

```text
apps/web (React + TypeScript + Vite)          ← browser workspace
        ↓ HTTP /api/v1
services/core (FastAPI, Python)
    ├─ api/        HTTP routes (typed request/response models)
    ├─ services/   core reads · projects · export · bioactivity ·
    │              structure search · AI summaries
    ├─ adapters/   external-source contracts: patent fixtures,
    │              bioactivity fixture, ChEMBL (webservice),
    │              BindingDB (user-provided TSV), LLM Chat Completions
    ├─ chemistry/  RDKit engine (canonicalization, InChIKey,
    │              descriptors, Murcko scaffolds, depictions)
    ├─ queries/    DuckDB bulk analytical layer (Parquet)
    ├─ db/         engine + versioned SQL migrations
    └─ domain/     typed domain models + provenance states
        ↓
PostgreSQL 15 + RDKit cartridge        DuckDB over Parquet
(molecule column + GIST/GIN indexes;   (bulk analytical reads of the
 patents, compounds, mentions,          fixture; future bulk releases)
 evidence, targets/assays/measurements,
 projects, ai_analyses)
```

No Redis, queue, search engine, or additional database exists
(`AGENTS.md` §6). `apps/chrome-extension/` is a thin MV3 context bridge:
URL-only publication-number detection → side panel → `?q=` deep link.

## Implemented workload separation (PROMPT.md §11)

| Workload | Store | Current use |
| --- | --- | --- |
| A. Bulk analytical filtering | DuckDB + Parquet | fixture adapter input; `/api/v1/bulk/compound-counts`; benchmarks |
| B. Interactive chemistry | PostgreSQL + RDKit cartridge (`mol` column, GIST/GIN) | exact / substructure / similarity search, molecule filters |
| C. Project and evidence state | PostgreSQL | patents, mentions, evidence, measurements, projects, AI analyses |

## Current data paths

```text
data/fixtures (synthetic Parquet, demo-fixture-v1)
      ↓  adapters (DuckDB read; source envelope with provenance)
      ↓  chemistry/engine.py (RDKit canonical SMILES, InChIKey,
      ↓                        descriptors, Murcko scaffold)
      ↓  seed.py (idempotent upsert; dedupe by InChIKey; malformed
      ↓          structures → ingestion_issues, never compounds)
PostgreSQL  →  api routes (server-paged, cap 500)
apps/web     (search → family → compounds → evidence/structure search)
```

- Structure search: exact = isomeric InChIKey; substructure = cartridge `@>`
  plus a chirality-aware RDKit re-check when the query specifies stereo;
  similarity = explicit `tanimoto_sml >= threshold` (this cartridge's `%`
  operator is fixed at 0.5 and would silently drop lower thresholds). Morgan
  fingerprints do not distinguish stereoisomers — the UI states this per mode.
- Depictions: RDKit SVG per request with disk cache; only rendered rows fetch.
- Bioactivity: only typed measurements surface; cross-assay values are never
  ranked or combined into selectivity numbers.
- AI summaries: default is the offline extractive provider
  (`machine_extracted`). With `SPAGO_LLM_BASE_URL`/`SPAGO_LLM_API_KEY`/
  `SPAGO_LLM_MODEL` configured, the AI tab can call one OpenAI-compatible
  Chat Completions endpoint (`adapters/llm.py`): bounded fact input
  (SQL selects ≤50 measurements, ≤50 evidence excerpts and a capped scaffold list;
  excerpts are byte-bounded at 1 KiB that is measured on the *annotated* body), typed fact
  citations validated server-side, content-key caching (zero provider calls on cache hit),
  LLM output labeled `llm_inferred`. If the irreducible metadata alone exceeds the 32 KiB
  budget the request fails before any provider call. `GET /api/v1/ai/status` reports
  offline/configured/config_invalid without calling the provider. The planner
  parses publication-number identifiers only.
- LLM execution uses one shared synchronous HTTP client and process-local in-flight
  tracking (two calls, one worker). No automatic retry or provider fallback exists.
  The declared budget is attached to each outbound request (connect 5 s, read = total
  deadline 60 s) and the deadline is re-checked between response chunks; upstream
  throttling answers 429 with a validated `Retry-After`, distinct from other upstream
  failures (502). See
  [the LLM contract record](../plans/2026-09-14-llm-interface.md).
- URL state: `?q=&doc=&c=`; new searches push history entries, selection
  replaces; Back/Forward restore via popstate.

## Deliberate boundaries

- Export is synchronous up to 5000 rows (documented cap); larger scopes need
  the future persisted background-job mechanism.
- The embedded Ketcher editor is deferred (packaging incompatibility with the
  Vite production build, recorded in the UI review round); SMILES paste is the
  structure-search input.
- No PDF/OCSR (M6), no live ChEMBL/BindingDB calls in the demo seed, and no
  cross-family structure search (family-scoped by contract).
- Pagination: default 100, hard cap 500, enforced server-side on every list
  and search endpoint. This caps a response, not a result set. Both the ordinary
  list and the structure-result list page by server-side offset and append: each
  request asks for one page (100 rows), the next page continues from
  `offset + items.length`, and Load more stops on the last page. Loaded rows survive a
  paging failure, which is shown as a retryable error owned by the request it came from;
  changing family, document, query or structure filter discards stale pages and errors.
  Verified with a 601-compound synthetic fixture
  (`benchmarks/paging-beyond-cap-2026-09-15.md`); the 150-row historical check is kept
  as a separate, narrower record.
- Source acceptance remains fixture/local-mock only in the recorded runs;
  real patent-source coverage and real-model compatibility remain unverified.
- Real ChEMBL/BindingDB adapter classes currently have no production import caller;
  seed uses the activity fixture. A real source needs identity mapping, validated
  import/persistence and per-record source navigation, not just a live adapter call.
- Export only accepts family/document/explicit IDs; it does not express the active
  structure query, despite the UI's “Current results” label. The 5000-row limit is
  currently checked after SQL result materialization. Both need correction before
  real-data delivery (PROD-02).
- Project APIs persist records, but the Web App has no project-reopening flow;
  source-version validation and behavior after source updates remain acceptance
  gaps (PROD-03). There is no user ownership or project authorization model.
- Local deployment defaults publish PostgreSQL on all host interfaces even though
  the app binds to loopback. PROD-04 corrects this and adds verified backup/restore;
  shared hosting separately requires PROD-08. The first release target is single-user.

## Performance baseline

Tracked by `services/core/benchmarks/run_benchmarks.py`;
`benchmarks/m0-baseline.json` (fixture scale) and
`benchmarks/paging-measurement-2026-09-14.md` (150-compound paging /
virtualization round) are retained measurements — neither is overwritten by
later runs.
