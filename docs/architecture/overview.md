# SPAgo Architecture Overview

Status: **current contract** (matches the implemented M0–M5 code; consolidated
during the 2026-09-14 UI review round as tracked in
`docs/plans/2026-09-14-ui-review-next-round.md`). History: the M0-only framing
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
    │              BindingDB (user-provided TSV)
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
  (≤50 items/kind, ≤32 KiB), typed fact citations validated server-side,
  content-key caching (zero provider calls on cache hit), LLM output labeled
  `llm_inferred`. `GET /api/v1/ai/status` reports
  offline/configured/config_invalid without calling the provider. The planner
  parses publication-number identifiers only.
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
  and search endpoint.

## Performance baseline

Tracked by `services/core/benchmarks/run_benchmarks.py`;
`benchmarks/m0-baseline.json` (fixture scale) and
`benchmarks/paging-measurement-2026-09-14.md` (150-compound paging /
virtualization round) are retained measurements — neither is overwritten by
later runs.
