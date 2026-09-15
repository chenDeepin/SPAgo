# SPAgo Core (services/core)

FastAPI backend for SPAgo — Milestone 0 foundation.

Licensed under Apache-2.0 with the rest of the repository (see root `LICENSE`,
`NOTICE`, and `THIRD_PARTY_NOTICES.md`).

## Layout

- `spago_core/domain/` — typed domain models + provenance states
- `spago_core/adapters/` — external-source contracts; fixture adapter (DuckDB + Parquet)
- `spago_core/chemistry/` — RDKit engine (canonicalization, InChIKey, depictions)
- `spago_core/queries/` — DuckDB bulk analytical layer over Parquet
- `spago_core/db/` — engine + plain-SQL migration runner
- `spago_core/seed.py` — idempotent fixture ingestion (`python -m spago_core.seed`)
- `spago_core/api/` — HTTP routes (`/healthz`, `/api/v1/...`)
- `tests/` — pytest suites (chemistry, adapter, bulk, PG-gated integration)
- `benchmarks/` — `run_benchmarks.py` baseline harness

## Local development

```bash
python3 -m virtualenv .venv            # any venv works; requires Python >= 3.10
.venv/bin/pip install -e '.[dev]'
export SPAGO_DATABASE_URL=postgresql+psycopg://spago:spago@localhost:5432/spago
python -m spago_core.seed
uvicorn spago_core.main:app --reload --port 8000
```

PostgreSQL (with the RDKit cartridge) is expected to come from
`docker compose up db` unless you run your own instance.
