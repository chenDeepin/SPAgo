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

The ONLINE-00–05 work (target-led open-database investigation, scoped summaries,
validated plans, hosted sessions, usage accounting) added **no new dependency**:
it uses the libraries already listed below, PostgreSQL, and the standard library.
`THIRD_PARTY_NOTICES.md` was still updated in the same change, because that work
added new *data sources and API adapters* (§6).

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
| ketcher-react | Apache-2.0 | Embedded structure editor component (structure-search dialog) |
| ketcher-standalone | Apache-2.0 | Indigo WASM service provider for the editor |
| ketcher-core | Apache-2.0 | Ketcher's shared model/serializer package |

**Ketcher version pinning is load-bearing.** `ketcher-react` and
`ketcher-standalone` declare their `ketcher-core` dependency as `"*"`, which
resolves to whatever the registry's latest tag was when the lockfile was written —
not to the matching release. With `ketcher-core` at 3.14.0 and the other two at
3.18.0, the production build fails (`"StereoLabelStyleType" is not exported by
ketcher-core`). All three are therefore pinned to the same version in
`apps/web/package.json`. Ketcher ships its own Apache-2.0 `LICENSE`; the Indigo
engine it embeds is also Apache-2.0 (EPAM). Upgrading Ketcher means re-checking
this pin, the `dist/binaryWasm` entry's missing `types` condition (declared in
`apps/web/src/upstream-types.d.ts`), and the bundle sizes recorded in
`benchmarks/online08-structure-editor-2026-09-16.md`.

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

### Adaptations from the author's own projects

The ONLINE-06 activity-classification and publication-number logic was adapted
from the same author's separate local project `BindingDB_IO` (reviewed
2026-09-15; that project is not redistributed here and was not modified):

| SPAgo file | Adapted from | What was taken |
| --- | --- | --- |
| `services/core/spago_core/chemistry/activities.py` | `bindingdb_io/activity.py` | The classification semantics: censored values (`<`, `>`, `~`), one explicit threshold, a deterministic reason string per branch. Unit handling, the endpoint allowlist and the `not_applicable` class are new here. |
| `services/core/spago_core/domain/patent_numbers.py` | `bindingdb_io/patents.py` | Lenient extraction of publication numbers from *source-declared* text (country code plus a six-digit floor, kind code dropped). |
| `services/core/spago_core/services/reference.py` | `bindingdb_io/activity.py` (`evaluate_gate`) | The screening-reference idea: a set with no compound at or below the threshold is reported as unusable, with the count that makes it so. Rewritten against SPAgo's stored measurements and its own modality scope. |
| `services/core/spago_core/services/supplements.py`, `migrations/0014_user_supplements.sql` | `bindingdb_io/web_supplement.py` (`load_web_supplement_file`, `normalize_web_records`) | The supplement *contract*: a hand-added row is per-target, keeps its as-reported value and its document reference, and a row whose structure is not public stays visible instead of being dropped. The storage, the mandatory note, the structure identity path and the remark table are new here (the source project substitutes a default note and writes a spreadsheet row). |

Both projects are the author's own work under the same Apache-2.0 grant, so no
third-party license obligation is triggered. They are listed because provenance
matters (AGENTS.md §0/§23), and so a reviewer can find the origin of these rules
rather than treat them as SPAgo inventions.

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

| Source | Relationship to SPAgo | Adapter (if bundled) |
| --- | --- | --- |
| SureChEMBL | Reads user-extracted packages of the official bulk Parquet release (EMBL-EBI FTP, https://ftp.ebi.ac.uk/pub/databases/chembl/SureChEMBL/bulk_data/). Bulk data and its LICENCE are CC BY 4.0 — attribution must be preserved for redistributed extracts; extraction tool: `scripts/extract_surechembl.py`. | `adapters/surechembl_bulk.py`, `adapters/surechembl_fixture.py` |
| UniProt | Target identity resolution (accessions, gene names, species, components) through the UniProt REST API, https://rest.uniprot.org/uniprotkb. UniProt is distributed under CC BY 4.0 (https://www.uniprot.org/help/license); no target metadata is used to support a potency or inhibitor claim. | `adapters/uniprot.py` |
| ChEMBL | Primary open target→molecule→assay→activity source, through the official web services (https://www.ebi.ac.uk/chembl/api/data). Data © EMBL-EBI under CC BY-SA 3.0 (https://chembl.gitbook.io/chembl-interface-documentation/about); records are stored with source ids and retrieval timestamps, and derived exports keep attribution. The patent-led path (§ B-24) asks `document.json?patent_id__icontains=` for a publication and reads its activities by `document_chembl_id__in`; what ChEMBL *declares* for a publication is stored in that path's own tables and is never written as a corpus occurrence. | `adapters/chembl_activity.py` (M3 mapped path), `adapters/chembl_discovery.py` (ONLINE-00 discovery, patent-led declared compounds) |
| BindingDB | Complementary protein–ligand affinities. The REST path (`https://bindingdb.org/rest/getLigandsByUniprot`) is used for bounded target retrieval; a locally supplied TSV import remains supported. BindingDB data is distributed under CC BY-SA 3.0 / CC BY 4.0 terms stated at https://www.bindingdb.org/rwd/bind/index.jsp — review before redistribution. | `adapters/bindingdb_rest.py`, `adapters/bindingdb_activity.py` |
| PubChem | Compound identity confirmation and bounded BioAssay context through PUG REST (https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest). NCBI asks that usage stay within published request-rate guidance; BioAssay records are labelled as screening context, never as measurements. | `adapters/pubchem.py` |
| EPO OPS | Bibliographic / family / text enrichment API (planned; requires operator credentials) | — |
| LLM providers | Optional Chat Completions endpoints configured by the operator. Prompt input is bounded, stored facts only; responses are labelled `llm_inferred`. Operator keys are never returned or accepted from a client. | `adapters/llm.py` |

Rules for every source above:

- Requests are bounded (timeout, page/record limits, rate limiting), and cached
  in-process with a short TTL. There is no crawling and no access-control evasion.
- A retrieval is recorded with its query, counts, outcome, source version and
  timestamp in `source_retrievals`; `failed`, `empty` and `not_queried` stay
  distinct, and a failure is never presented as an empty result.
- **Software licenses do not grant dataset redistribution rights.** Review the
  current official Terms of Use before production use, and before redistributing
  any retrieved content. SPAgo does not mirror these datasets into its database
  beyond the bounded records an investigation itself retrieves.

---

## 7. Deferred / not currently bundled

| Component | Status |
| --- | --- |
| OIDC / SSO auth provider | Not adopted. Authentication is implemented in-house over PostgreSQL sessions (ADR-0002); adding an external identity provider is a decision for the operator, and no auth library is bundled today. |
| Passkey/WebAuthn library | Not adopted for the same reason. |
| Any new queue, vector store, search engine or cache | Not adopted; ADR/measurement required first (AGENTS.md §6). |

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
