# Third-Party Notices

SPAgo source code is licensed under the Apache License, Version 2.0
(see `LICENSE` and `NOTICE`).

This document lists **included or required** third-party components and
related terms so redistributors and adopters can review them. License
metadata below is taken from upstream package metadata / project pages
as of the SPAgo M0–M5 local demo checkout (2026-09-15). Always confirm
against the versions pinned in your build.

This file is **informational**. It does not modify the Apache-2.0 terms
for SPAgo’s own code. Dataset and API **Terms of Use** are separate from
software licenses.

---

## 1. Direct Python runtime dependencies

Declared in `services/core/pyproject.toml`.

| Component | Typical license | Role in SPAgo |
| --- | --- | --- |
| FastAPI | MIT | HTTP API framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| Pydantic | MIT | Request/settings models |
| pydantic-settings | MIT | Environment configuration |
| SQLAlchemy | MIT | Database access |
| psycopg (psycopg[binary]) | LGPL-3.0 | PostgreSQL driver |
| DuckDB | MIT | Analytical queries over Parquet |
| PyArrow | Apache-2.0 | Parquet I/O |
| RDKit | BSD-3-Clause | Chemistry engine / depictions |
| httpx | BSD-3-Clause | Outbound HTTP client |

**Dev-only (optional):** pytest — MIT.

### Note on psycopg (LGPL-3.0)

SPAgo uses psycopg as a dynamically linked library dependency. If you
modify and redistribute psycopg itself, follow LGPL-3.0. Shipping an
unmodified PyPI binary wheel alongside SPAgo is the normal case; keep
upstream license texts with any redistributed binaries.

---

## 2. Direct frontend dependencies

Declared in `apps/web/package.json`.

| Component | Typical license | Role in SPAgo |
| --- | --- | --- |
| React | MIT | UI |
| React DOM | MIT | UI rendering |
| @tanstack/react-query | MIT | Server-state queries |
| @tanstack/react-table | MIT | Result tables |
| @tanstack/react-virtual | MIT | Virtualized lists |
| events | MIT | EventEmitter polyfill |

**Build / types (dev):** Vite (MIT), `@vitejs/plugin-react` (MIT),
TypeScript (Apache-2.0), `@types/react` / `@types/react-dom` (MIT).

### Transitive frontend notes

A full `npm` install may pull additional MIT/ISC/Apache-2.0 packages.
Notable non-MIT transitive example observed in this tree:

| Component | License | Note |
| --- | --- | --- |
| caniuse-lite | CC-BY-4.0 | Browser compatibility data (build toolchain) |

Regenerate a current inventory when releasing:

```bash
cd apps/web && npx license-checker --summary
```

---

## 3. Container and OS base images

Used by `docker/app/Dockerfile` and `docker/db/Dockerfile`.

| Component | License family | Role |
| --- | --- | --- |
| `python:3.12-slim` | PSF + Debian package mix | App runtime base |
| `node:22-bookworm-slim` | Node.js + Debian package mix | Frontend build stage |
| `debian:bookworm-slim` | Debian DFSG package mix | Database image base |
| PostgreSQL 15 | PostgreSQL License | Transactional store |
| postgresql-15-rdkit | PostgreSQL License + RDKit BSD-3-Clause | Chemistry cartridge |
| DuckDB `httpfs` extension | MIT | Required by the SureChEMBL extractor for HTTPS Parquet range reads; installed on first use from the official DuckDB extension repository, matching the runtime DuckDB version/platform |

Base images contain many OS packages; their individual licenses remain
those of Debian/upstream. SPAgo does not re-license those packages.

The extractor reuses the installed `httpfs` binary or installs the signed core
extension from `https://extensions.duckdb.org`. Its upstream license is
[DuckDB httpfs MIT license](https://github.com/duckdb/duckdb-httpfs/blob/main/LICENSE).
Redistributors who cache or bundle this binary must preserve its upstream
copyright and license text, together with notices required by its included
third-party components; the extension's software license does not grant
rights to the patent datasets it reads.

---

## 4. Repository components under the same Apache-2.0 grant

Unless a subdirectory states otherwise, the following first-party
materials are covered by the root Apache-2.0 license:

- `services/core` (FastAPI backend)
- `apps/web` (React workspace)
- `apps/chrome-extension` (MV3 companion bridge)
- `migrations`, `scripts`, `docs` (except where quoting third-party text)
- Synthetic demo fixtures under `data/fixtures` (see below)

---

## 5. Synthetic demo fixtures

`data/fixtures` ships a **synthetic** demo dataset
(`surechembl_simplified_fixture` / `demo-fixture-v1`).

- It is labeled synthetic and is **not scientific data**.
- It is provided with the repository for software verification under
  Apache-2.0 as part of SPAgo.
- Names resembling external products (for example “SureChEMBL” in adapter
  or fixture identifiers) do **not** mean the fixture is real SureChEMBL
  content.

---

## 6. External data sources and APIs (Terms of Use — not SPAgo code)

SPAgo adapters may call or read the following. Their **terms, rate
limits, attribution, and redistribution rules** are controlled by each
provider. Using SPAgo software does not grant rights to those datasets.

| Source | Relationship to SPAgo |
| --- | --- |
| SureChEMBL | **Bundled adapter** (`spago_core/adapters/surechembl_bulk.py`): reads user-extracted packages of the official bulk Parquet release (EMBL-EBI FTP, https://ftp.ebi.ac.uk/pub/databases/chembl/SureChEMBL/bulk_data/). Bulk data and its LICENCE are CC BY 4.0 — attribution must be preserved for redistributed extracts; extraction tool: `scripts/extract_surechembl.py`. |
| EPO OPS | Bibliographic / family / text enrichment API |
| ChEMBL | Bioactivity enrichment (adapter contract) |
| BindingDB | User-provided TSV enrichment (adapter contract) |
| PubChem | Possible structure/enrichment reference |
| LLM providers | Optional Chat Completions endpoints via user config |

Always review the current official Terms of Use before production use or
redistribution of retrieved content.

---

## 7. Deferred / not currently bundled

| Component | Status |
| --- | --- |
| Ketcher (structure editor) | Deferred; re-check license before adding |

---

## 8. Regenerating dependency license reports

Python (from an environment with SPAgo deps installed):

```bash
pip install pip-licenses
pip-licenses --from=mixed
```

JavaScript:

```bash
cd apps/web && npx license-checker --production --csv
```

Update this file when direct dependencies change.
