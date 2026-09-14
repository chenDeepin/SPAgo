# SPAgo Architecture Overview

Status: current for Milestone 0. Source constraints: root `AGENTS.md`, `PROMPT.md`.

## Shape

SPAgo is a modular monolith deployed as two containers:

```text
apps/web (React + TypeScript + Vite)          ← browser workspace
        ↓ HTTP /api/v1
services/core (FastAPI, Python)
    ├─ api/        HTTP routes (typed request/response models)
    ├─ services    read/query orchestration over PG
    ├─ adapters/   external-source contracts + implementations
    ├─ chemistry/  RDKit engine (deterministic chemistry)
    ├─ queries/    DuckDB bulk analytical layer (Parquet)
    ├─ db/         engine + versioned SQL migrations
    └─ domain/     typed domain models + provenance states
        ↓                        ↓
PostgreSQL 15 + RDKit cartridge      DuckDB over Parquet
(workload B+C: interactive            (workload A: bulk analytical
 chemistry state, projects,            filtering of external bulk
 evidence, normalized compounds)       datasets; no duplication into PG)
```

No Redis, queue, search engine, or additional database is present or justified at M0
(see `AGENTS.md` §6 and `docs/adr/0001-m0-foundation-data-path.md`).

## Workload separation (PROMPT.md §11)

| Workload | Store | M0 use |
| --- | --- | --- |
| A. Bulk analytical patent filtering | DuckDB + Parquet | fixture adapter input; `/api/v1/bulk/compound-counts`; benchmarks |
| B. Interactive chemical search | PostgreSQL + RDKit cartridge | M0: normalized compound rows only (Python RDKit); cartridge indexing lands with M2 structure search |
| C. Project and evidence state | PostgreSQL | patents, families, mentions, evidence, datasets (projects table exists; save UI is M1) |

## Data path at M0

```text
data/fixtures (synthetic Parquet, versioned demo-fixture-v1)
      ↓  adapters/surechembl_fixture.py  (DuckDB read; envelope with source + retrieval metadata)
      ↓  chemistry/engine.py             (RDKit parse → canonical SMILES, InChIKey, descriptors)
      ↓  seed.py                         (idempotent upsert into PostgreSQL; dedupe by InChIKey;
      ↓                                   malformed structures recorded as warnings, never as compounds)
      ↓  api routes                       (server-paged reads; lazy depictions with disk cache)
apps/web                                  (search → family → compounds → evidence)
```

Interactive serving reads PostgreSQL only. The Parquet/DuckDB path is the bulk/analytics
lane and the future SureChEMBL ingestion route.

## Domain model (M0 subset)

`PatentFamily`, `PatentDocument`, `Compound`, `CompoundMention`, `EvidenceRecord`,
`DatasetInfo`, `SourceEnvelope`. `Compound` is the normalized chemical entity
(identity keyed by InChIKey); `CompoundMention` is a patent-local occurrence
(label + document). They are separate tables and separate API objects.

Provenance states: `source_fact`, `database_curated`, `machine_extracted`,
`llm_inferred`, `user_curated`. Nothing may upgrade a state silently.

## External-source isolation (AGENTS.md §8)

Adapters return normalized domain models plus a `SourceEnvelope`
(source name, source version, dataset version, retrieved-at, warnings).
UI and services never see native Parquet/external schemas. Adding OPS/ChEMBL/BindingDB
later means adding adapters, not touching the UI domain model.

## Deliberate M0 boundaries

- Projects table exists but no save/export UI (M1).
- No Ketcher, no structure search (M2). Substructure/similarity will require
  the RDKit cartridge index — the first milestone that needs it.
- No bioactivity (M3), no extension (M4), no LLM (M5), no PDF/OCSR (M6).
- Pagination: default 100 rows, hard cap 500, enforced server-side.
- Depictions: generated on request per compound, cached on disk
  (`data/cache/depictions/`, gitignored), only fetched for rendered rows.

## Performance baseline

Tracked by `services/core/benchmarks/run_benchmarks.py` against the synthetic
fixture; committed baseline lives in `benchmarks/` (`m0-baseline.json`).
Fixture-based numbers are not representative of bulk-dataset scale; they exist
so regressions become measurable from day one.
