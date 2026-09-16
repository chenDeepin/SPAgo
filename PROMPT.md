# SPAgo — Initial Engineering Prompt

> **Current handoff (2026-09-16; baseline `194e953`, the ONLINE-00…07 work plus the
> defect and backlog rounds).**
>
> **Implemented and locally verified:** target-led open-database discovery
> (UniProt + ChEMBL + BindingDB + PubChem, ONLINE-00), scoped evidence-grounded
> summaries for family / document / target with an offline provider (ONLINE-01),
> validated natural-language plans (ONLINE-02), invitation-only hosted sessions with
> per-owner data and usage quotas (ONLINE-03), a deterministic potency class and
> screening-reference verdict under a stated policy (ONLINE-06), and hand-added
> literature rows with `user_curated` provenance (ONLINE-07).
> Records: `docs/plans/2026-09-15-online-llm.md` §4 (ONLINE-00…05),
> `docs/plans/2026-09-15-bindingdb-io-port.md` §6–§7 (ONLINE-06/07),
> `benchmarks/` for every measurement, and `docs/online-capability.md` §6 for the
> gate that hosted acceptance must pass (checklist plus the invited-user script).
>
> **Closed in the 2026-09-16 rounds** (details: `docs/archive/2026-09-16-defect-round.md`
> and `docs/archive/2026-09-16-backlog-round.md` §5):
> - Investigation scope is per-target (`target_relations`), and rows are corrected or
>   **withdrawn**, never deleted — a source refresh retracts what it no longer returns,
>   and an interrupted import is marked `interrupted` instead of sitting in `running`.
> - The ChEMBL `only=` projection is **measured**: −42 % bytes, **no** latency gain
>   (`benchmarks/online00-chembl-projection-2026-09-16.md`). The page count, not the page
>   size, is the upstream latency lever. `target_construct` was removed — no adapter
>   could populate it.
> - The citation defect that refused target summaries is fixed and re-measured on a
>   **sparse** target (`benchmarks/online01-llm-eval-2026-09-16-sparse.md`: 0/2 before,
>   2/2 after).
> - The acceptance cohort is re-recorded on this build
>   (`benchmarks/cohort-coverage-2026-09-16.md`): CD40LG **qualifies** (10 in-scope
>   compounds, 6 ≤ 10 µM) and IL-6R stays thin with a BindingDB **source failure**.
>   IL-6 / IL-6R resolve ambiguously by symbol and need `P05231` / `P08887`.
> - The embedded **Ketcher editor** ships in the structure dialog; its cost is measured
>   (`benchmarks/online08-structure-editor-2026-09-16.md`: 20.3 MB raw / 4.95 MB gzip on
>   first open, 0.83–0.86 s to a usable editor on loopback, container serves assets
>   uncompressed). A `changeEvent` no-op that kept drawings out of the SMILES box was
>   found in the browser and fixed.
> - The **MV3 companion** was loaded unpacked in a real browser and its handoff verified
>   from the extension's own `storage.session` (`apps/chrome-extension/verify-in-chrome.js`);
>   behind it: branded Chrome 137+ refuses `--load-extension`, so an unbranded
>   Chromium / Chrome for Testing build is required. The B-18 round (2026-09-16) added
>   the panel-behavior flag to that script's verified set — `openPanelOnActionClick` is
>   read back from the running worker, not assumed. The physical toolbar click and
>   side-panel surface chrome are **not** covered (no browser-chrome user gesture can be
>   synthesized here). Latency/cost targets are the operator's to fill in:
>   `docs/runbook.md` §H9.
>
> **Delivered after that baseline (2026-09-16 backlog rounds, each with its plan file,
> tests and browser evidence; back to commit history for the exact set):**
> - **B-13** gate support kit: `scripts/restore_check.sh` + the §H2 ingress-duty table.
> - **B-01** corpus scale-up: `scripts/corpus_batch.py`, `spago_core.corpus_status`,
>   `GET /api/v1/corpus` and the top-bar corpus dialog.
> - **B-10** analyses read back: `GET /api/v1/analyses`, `/analyses/{id}`,
>   `/analyses/{id}/export` and the **Analyses** dialog — no provider call to reopen.
> - **B-02** reference coverage: a disjoint per-retrieval tally of how each kept record's
>   document reference resolved (`source_retrievals.reference_counts`,
>   `docs/plans/2026-09-16-source-declared-linkage.md`), rendered in the target header.
> - **B-24** patent-led declared sets: `POST/GET /api/v1/patents/{number}/source-compounds`
>   (+ CSV/SDF export) and the patent view's declared-compound panel, on a publication the
>   corpus does not hold.
> - **B-03** tolerant publication entry: one versioned shape rule
>   (`publication-number-tolerant-v1`) mirrored in the client, exact-first lookup, an
>   ambiguity reported as 409 with candidates named.
> - **B-25** supplement bundles: `POST /targets/{id}/supplements/bundle`, the import
>   report and `POST …/supplement-imports/{id}/confirm` — an agent's rows are a
>   **proposal** (stored, readable, counted as `unreviewed_supplements`, outside the
>   candidates/verdict/exports) until a person confirms the import in a recorded act.
> - **B-26** per-publication coverage audit: `GET /api/v1/patents/coverage` answers
>   what is stored for a publication and from which leg, keeping "never asked" apart
>   from "the source knows nothing".
> - **B-06** per-source re-run: `POST /api/v1/targets/{id}/discover` takes one source —
>   a failed source is retried without spending another source's rate limit or
>   re-dating its rows — and the header shows which rows this run asked for.
> - **B-23** operator snapshot path: `scripts/bindingdb_snapshot.py` answers a target
>   from the whole local BindingDB release with the file's release and digest stored
>   next to every row (operator-only; not a hosted capability).
> - **B-15** served-asset compression: the app compresses its own responses (gzip,
>   level 6), so a `docker compose up` install sends the editor's first open as 5.2 MB
>   instead of 20.3 MB without a proxy (`benchmarks/asset-compression-2026-09-16.md`).
>
> **Two facts to keep straight.** The reference verdict is a **count under a stated
> policy — not a biological or legal conclusion**: on live data TSLP has no
> small-molecule active in these sources. Source-declared patent linkage **is** now
> measured live (B-02: 135 of IL6's 166 kept records carry a source-declared patent;
> TSLP's are DOI-only; EGFR has 1,210 records citing a document ChEMBL does not return).
> A hand-added row is
> `user_curated` and cannot be deleted; a corrected row is re-submitted, which replaces
> the earlier one; taking a row back is a recorded retraction with a reason.
>
> **NOT done — do not mistake implementation for acceptance.** No **hosted** deployment
> exists (ONLINE-04 acceptance is open) and no invited user has been through the
> workflow (ONLINE-05 is open). One live model provider was smoke-tested (DeepSeek
> `deepseek-flash`) — one provider, not a compatibility claim
> (`docs/archive/2026-09-15-llm-live-smoke.md`). Summary evaluation covers one demo
> family, one demo document, one live target and one empty-scope target; a **second
> provider** is still untested. Content correctness remains unproven: a valid schema and
> a valid citation are not scientific truth. Host, provider, budget and cohort remain
> operator decisions; this work does not authorize purchasing infrastructure, sending
> private datasets to a provider, or public deployment.
>
> **Start here for the next turn:**
> 1. Re-read `docs/online-capability.md` (the scope statement) and `docs/runbook.md`
>    §H1–H10 (the hosted deployment contract, §H9 the budget worksheet).
> 2. Run the acceptance script in `docs/online-capability.md` §6 on a
>    real host and close that section's gates: TLS ingress and secret injection, a
>    restore rehearsal on that host, one real invited user, independent cross-reading
>    of retrieved chemistry, and latency/cost targets for the chosen host and model
>    filled into §H9. Set `SPAGO_LLM_USER_TOKEN_LIMIT` /
>    `SPAGO_LLM_DEPLOYMENT_TOKEN_LIMIT` to real values first.
> 3. Only operator-decision items remain in the capability gate (§6); the engineering
>    half is closed. If summary quality is measured again, add a **second provider**
>    before quoting numbers. Runner and method:
>    `benchmarks/online01-llm-eval-2026-09-15.md`.
> 4. Engineering work that is *not* approved scope is collected, with its priority
>    order, in `docs/plans/backlog.md`. That register is a proposal list, not a queue:
>    an item there is not started, promised or authorized until it is deliberately
>    picked and planned as its own round. Its current head is **B-04** (import refresh
>    completeness and interrupted-import resume, P2); the register's update log records
>    every move and why.
>
> Current source coverage is genuinely thin for some acceptance targets (human TSLP has
> one small-molecule candidate in these sources; IL-6R has one, and BindingDB does not
> answer for it). Report that honestly rather than promising inhibitor coverage. Model
> output stays inference; chemistry stays deterministic. Full-document extraction/M6 and
> general chat remain deferred.
>
> Current source coverage is genuinely thin for some acceptance targets (human TSLP has
> one small-molecule candidate in these sources; IL-6R has one, and BindingDB does not
> answer for it). Report that honestly rather than promising inhibitor coverage. Model
> output stays inference; chemistry stays deterministic. Full-document extraction/M6 and
> general chat remain deferred.
>
> History: the local milestone line is committed up to `194e953`, and today's two
> closing rounds are archived in `docs/archive/2026-09-16-defect-round.md` and
> `docs/archive/2026-09-16-backlog-round.md`. Earlier rounds (the local-first review
> with its 217-test result, the UI review, the docs consolidation) are archived
> under `docs/archive/` — do not mistake their uncommitted-state notes or
> local-first priorities for this stage's status.
>
> The rest of this document remains the standing engineering contract.

You are building **SPAgo** (small molecule patent analysis GO), a patent-native medicinal chemistry workspace for small-molecule drug discovery.

Read `AGENTS.md` and `README.md` before changing code. Treat them as project-level constraints.

Do not attempt to build the entire vision in one iteration.

The project must evolve through narrow, testable vertical slices, starting from a minimal but real workflow.

---

# 1. Core Product Decision

SPAgo is **not**:

- a replacement for Espacenet;
- another generic patent search engine;
- a full DataWarrior clone;
- a collection of unrelated chemistry tools;
- an LLM wrapper around patent PDFs;
- a browser automation system that scrapes Espacenet;
- a giant microservice platform.

SPAgo is:

> A structure-native medicinal-chemistry workspace that connects patents, patent families, compounds, biological measurements, claims, and exact supporting evidence in one continuous workflow.

The primary product loop is:

```text
Search
  ↓
Patent families
  ↓
Compounds
  ↓
Structure filtering
  ↓
Bioactivity / SAR
  ↓
Claims and evidence
  ↓
LLM-assisted interpretation
  ↓
Saved project / decision
```

The most important product object is not a PDF.

It is the connected relationship:

```text
PatentFamily
    ↕
PatentDocument
    ↕
Compound
    ↕
CompoundMention / Example
    ↕
Assay / Measurement
    ↕
Claim
    ↕
Evidence
```

---

# 2. Product Differentiation

Do not compete with SureChEMBL merely by reproducing structure search.

Do not compete with Espacenet merely by reproducing bibliographic search.

Do not compete with DataWarrior merely by reproducing a molecular table.

SPAgo must differentiate through five capabilities.

## 2.1 Evidence-linked chemistry

Every extracted or curated scientific statement should be traceable back to evidence.

Example:

```text
Compound 153
CDK4 IC50 = 2.1 nM

Evidence:
Patent: WO-XXXXXXXX
Section: Example 153
Page: 183
Table: 12
Row: Compound 153
Column: CDK4 IC50
Source type: patent_table
Confidence: curated / extracted / inferred
```

A user should be able to move from a compound or activity value to its original patent evidence with one action.

## 2.2 Cross-patent chemical normalization

Normalize compounds across patent documents and patent families.

Support:

- canonical SMILES;
- InChIKey;
- salt/parent relationships where possible;
- stereochemistry preservation;
- exact identity;
- scaffold identity;
- structural similarity;
- patent-local compound IDs.

Do not treat `Compound 15` in two patents as the same entity merely because the labels match.

## 2.3 Structure-native retrieval

Users must be able to combine:

- text query;
- target;
- assignee;
- date;
- patent family;
- CPC/IPC;
- exact structure;
- substructure;
- similarity;
- bioactivity thresholds.

Structure must be a first-class search primitive rather than an image attached to a search result.

## 2.4 Cross-patent SAR workspace

The application should eventually allow medicinal chemists to answer:

- Which scaffold families dominate this target?
- Which substituent changes correlate with potency?
- Which modifications affect selectivity?
- Which patent family introduced a scaffold first?
- Which compounds are emphasized in examples versus claims?
- Which chemical space appears crowded?
- Which measurements are actually supported by original patent evidence?

## 2.5 Workflow continuity

SPAgo should reduce tool switching.

The user should not need to repeatedly perform:

```text
Espacenet
→ download PDF
→ manually locate structures
→ manually create spreadsheet
→ DataWarrior
→ BindingDB
→ ChEMBL
→ separate LLM
→ manual notes
```

The common path should remain inside SPAgo while preserving links back to original sources.

---

# 3. UX Principle: Preserve Existing User Habits

Do not force users into a new workflow unnecessarily.

SPAgo has two entry modes.

## Mode A — Standalone Web App

The complete application works in a normal modern browser.

No browser extension is required.

## Mode B — Optional Chrome Companion

A small Manifest V3 Chrome extension may:

- detect the current patent publication number;
- capture the current URL;
- open the SPAgo side panel;
- send the patent identifier to the SPAgo Web App.

The extension must remain thin.

It must not contain:

- the patent database;
- chemistry search indices;
- RDKit backend logic;
- PDF extraction pipelines;
- LLM orchestration;
- large caches.

The extension is a context bridge, not the product.

SPAgo must remain fully usable without it.

---

# 4. Architecture Principle: Modular Monolith First

Build a modular monolith; do not introduce microservices unless measured production
requirements justify them. The initial deployment is one `spago-app` (frontend, API,
source adapters, chemistry services, query layer, LLM/evidence layer) plus
`postgres-rdkit` (project data, normalized chemistry, searchable structures,
annotations, evidence, measurements).

SureChEMBL bulk Parquet stays an external read-only analytical dataset queried through
DuckDB. Do not import the entire collection into the transactional database for
convenience; materialize or index data only when interactive structure search, project
persistence, caching or measured performance requires it. Redis, Kafka, RabbitMQ,
Elasticsearch, Kubernetes, Celery, MinIO and additional databases all require a written
architecture decision and benchmark evidence first (AGENTS.md §6, §7).

---

# 5. Initial Technology Direction

Preferred stack:

```text
Frontend
- React
- TypeScript
- Vite
- TanStack Query
- TanStack Table
- TanStack Virtual
- Ketcher
- lightweight molecule SVG renderer

Backend
- Python
- FastAPI
- Pydantic
- RDKit
- DuckDB
- Polars/PyArrow only where useful

Primary database
- PostgreSQL
- RDKit PostgreSQL cartridge

Bulk patent chemistry
- SureChEMBL Parquet
- DuckDB query layer

Patent metadata / family enrichment
- EPO OPS adapter

Bioactivity enrichment
- BindingDB adapter
- ChEMBL adapter

Optional later enrichment
- PubChem

Chrome integration
- Manifest V3
- Chrome Side Panel
```

Dependencies are implementation details.

Do not expose these components as separate products or separate user-facing modules.

---

# 6. Data Source Strategy

Create stable internal adapter interfaces.

External sources must never leak their native schemas directly into UI code.

Use an internal normalized model.

Example adapters:

```text
PatentSource
ChemicalPatentSource
BioactivitySource
PatentFamilySource
DocumentSource
```

Initial sources:

```text
SureChEMBL
EPO OPS
BindingDB
ChEMBL
```

Rules:

1. SureChEMBL is the primary broad patent-chemistry source.
2. EPO OPS is used for authoritative bibliographic/family/full-text enrichment where appropriate.
3. BindingDB is a curated bioactivity enrichment source, not the sole patent discovery source.
4. ChEMBL is an external compound/target/activity enrichment source.
5. Never automate Espacenet UI to obtain data that should be requested through official APIs or bulk datasets.
6. Cache external responses.
7. Apply source-specific rate limiting.
8. Record source and retrieval timestamp.

---

# 7. Domain Model

Start with explicit typed entities.

At minimum:

```text
Project

PatentFamily
PatentDocument

Compound
CompoundIdentity
CompoundMention
CompoundExample

Target

Assay
Measurement

Claim

Evidence

SourceRecord

UserAnnotation

LLMAnalysis
```

Important distinction:

```text
Compound
```

is a normalized chemical entity.

```text
CompoundMention
```

is an occurrence in a patent.

```text
CompoundExample
```

represents an experimental/example context.

These must not be collapsed into one table.

---

# 8. Evidence Model

Evidence is mandatory.

Use a structure similar to:

```text
Evidence {
    id
    patent_document_id
    source_type
    source_locator
    page
    section
    table
    figure
    paragraph
    compound_local_id
    raw_excerpt
    source_url
    extraction_method
    confidence
    created_at
}
```

Source types may include:

```text
title
abstract
claim
description
example
table
figure
mol_attachment
external_database
```

LLM-generated conclusions should reference one or more Evidence records whenever factual claims are made.

---

# 9. LLM Role

LLMs are reasoning and orchestration components.

They are not the primary chemistry engine and not the scientific source of truth.

LLM responsibilities:

- natural-language query interpretation;
- query planning;
- patent summary;
- mechanism/target/indication extraction;
- SAR interpretation;
- claim explanation;
- family comparison;
- evidence-grounded synthesis;
- uncertainty explanation.

Deterministic systems should handle:

- molecular identity;
- structure normalization;
- substructure matching;
- fingerprint similarity;
- descriptor calculation;
- patent-family identifiers;
- database joins;
- numeric activity filtering.

Never ask an LLM to replace RDKit for chemistry matching.

Never silently convert an LLM inference into curated fact.

Use explicit states:

```text
source_fact
database_curated
machine_extracted
llm_inferred
user_curated
```

---

# 10. Large-Data Rules

Assume searches can eventually involve hundreds of thousands or millions of compounds,
and never treat the browser as the database.

Server-side filtering, sorting and pagination; virtualized visible rows; lazy molecule
depiction and lazy evidence loading; cancellable and debounced queries; cached
depictions and normalized structures; background processing for expensive document
extraction. Default result page 50–100 rows, hard maximum 500 for ordinary row
responses; never return an entire patent-chemistry dataset as one JSON array, and never
render thousands of molecule SVGs at once — only structures entering or near the
viewport.

These limits are normative in AGENTS.md §13 and §21.

---

# 11. Query Architecture

Separate three workloads.

## A. Bulk analytical patent filtering

Use DuckDB over SureChEMBL Parquet.

Examples:

- date;
- assignee;
- CPC;
- patent family;
- patent-field occurrence;
- biomedical annotation;
- simple aggregations.

## B. Interactive chemical search

Use RDKit-backed indexed chemistry storage.

Examples:

- exact structure;
- substructure;
- similarity;
- scaffold;
- molecular descriptors.

## C. Project and evidence state

Use PostgreSQL.

Examples:

- saved patent families;
- user annotations;
- normalized compounds;
- evidence;
- analyses;
- project decisions.

Do not force all three workloads into the same storage model.

---

# 12. UI Model

Avoid dashboard proliferation.

The core UI should initially expose only four conceptual surfaces:

```text
1. Search
2. Results / Molecules
3. Evidence
4. AI
```

A possible desktop layout:

```text
┌─────────────────────────────────────────────────────┐
│ Search / structure / filters                        │
├──────────────┬──────────────────────────┬───────────┤
│ Patent       │ Molecules / SAR          │ AI        │
│ Families     │                          │           │
│              │ virtualized table        │           │
│              │ + structure cards        │           │
├──────────────┴──────────────────────────┴───────────┤
│ Evidence / source document                          │
└─────────────────────────────────────────────────────┘
```

Do not create separate permanent panels for every source.

Do not show infrastructure concepts to the user.

Use progressive disclosure.

Advanced filters should remain collapsed until requested.

---

# 13. MVP Vertical Slice

Implement one complete workflow before expanding scope.

## User story

A medicinal chemist enters a patent number.

SPAgo:

1. resolves the patent;
2. displays family and bibliographic information;
3. obtains known extracted compounds;
4. displays compounds as a virtualized structure table;
5. allows exact/substructure/similarity filtering;
6. displays source field/evidence information;
7. enriches available compounds with known activity data;
8. allows the user to save selected compounds and the patent family into a project;
9. generates an evidence-grounded summary.

This is the first complete vertical slice.

Do not begin with general target landscape search.

Do not begin with PDF OCSR.

Do not begin with Markush interpretation.

Prove this workflow first.

---

# 14. Milestones

Deliverables and exit criteria are kept as the acceptance target for each slice; state
is what has actually been verified. Records are in `docs/archive/`.

## Milestone 0 — Foundation and Benchmarks

Deliver: monorepo, frontend and backend shells, PostgreSQL + RDKit image, normalized
domain model, adapter interfaces, evidence model, DuckDB SureChEMBL proof of concept,
benchmark harness, small reproducible test dataset.
Exit: one-command local startup, health checks pass, browser opens, a test patent loads,
sample compounds appear, the benchmark command produces a baseline report.
**State: implemented** (`docs/archive/2026-09-14-m0-foundation.md`).

## Milestone 1 — Patent Chemistry Viewer

Deliver: patent-number search, family detail, compound table, 2D structures, evidence
fields, structure detail drawer, save-to-project.
Exit: a user can inspect a patent without downloading the PDF for the common path, move
from compound to source evidence, and keep a large table responsive.
**State: implemented**, including the embedded Ketcher editor (deferred in the UI
review round, embedded 2026-09-16; cost and behaviour measured in
`benchmarks/online08-structure-editor-2026-09-16.md`).

## Milestone 2 — Structure Search

Deliver: exact, substructure and similarity search with molecular filters on
cartridge-indexed chemistry.
Exit: structure queries combine with patent metadata filters, run server-side, and need
no large client-side dataset.
**State: implemented**, with the editor's own drawing surface as the structure input
(the dialog's SMILES box stays the query, and nothing runs until the explicit action).

## Milestone 3 — Bioactivity and SAR

Deliver: BindingDB and ChEMBL adapters, activity normalization, target mapping,
SAR-oriented table modes, scaffold grouping.
Exit: a user can compare related compounds across patents and activity sources, and every
external measurement retains provenance.
**State: implemented for open sources; direct/indirect distinction and per-target
coverage live in the online capability statement.**

## Milestone 4 — Chrome Companion

Deliver: Manifest V3 extension, side panel, current-patent detection, handoff to an
existing SPAgo session.
Exit: installation is optional, SPAgo works identically without it, no Espacenet
automation or CAPTCHA bypass exists.
**State: thin bridge implemented and verified in a real browser** —
`apps/chrome-extension/verify-in-chrome.js` loads the unpacked extension in an
unbranded Chromium, opens a page under the content-script match pattern, reads the
handoff back out of the worker's `chrome.storage.session` and the rendered side-panel
page, and reads `chrome.sidePanel.getPanelBehavior()` back from the running worker so
the `openPanelOnActionClick` flag the toolbar click relies on is verified as set (B-18,
2026-09-16). The physical toolbar click and the side-panel surface chrome are not
covered by that script — no browser-chrome user gesture can be synthesized in this
checkout — and are not claimed.

## Milestone 5 — Evidence-Grounded AI

Deliver: query planner, patent summary, SAR summary, family comparison, evidence
citations, confidence states.
Exit: factual AI answers expose evidence, and unsupported conclusions are visibly marked
as inference.
**State: implemented offline and against one live provider; entailment evaluation
open.**

## Milestone 6 — Document Extraction Fallback

Patent PDF extraction, table extraction, OCSR, compound-label association, human review
queue — only after the previous milestones are stable, and only when measured coverage
gaps justify it. **Not MVP scope and not started.**

---

# 15. Installation Goal

Two supported usage modes.

## Hosted

```text
Open URL
→ sign in if needed
→ use SPAgo
```

No local chemistry software required.

## Local

Target:

```bash
git clone <repo>
cd spago
docker compose up -d --build
```

Then open:

```text
http://localhost:PORT
```

The user should not need to install:

- Python;
- Node;
- PostgreSQL;
- RDKit;
- DuckDB;
- DataWarrior;
- Java.

These remain internal dependencies inside the packaged application.

---

# 16. Testing Requirements

Every important data path requires tests, at minimum: unit, adapter contract, chemistry
correctness, API, database integration, frontend interaction, end-to-end and performance
regression (AGENTS.md §27).

Sealed patent fixtures must cover one patent with many compounds, one family with
multiple jurisdictions, duplicate chemical structures, stereochemical differences,
compounds with and without bioactivity, and incomplete external-source data. Never use
only mocked chemistry in acceptance tests. Chemistry and source regression classes are
fixed in AGENTS.md §28 and §29.

---

# 17. Performance Regression Rules

Build benchmark scripts before large feature development, and track patent lookup, table
query and structure search latency, molecule depiction, memory use, response size,
database query count, initial page load and scroll responsiveness. A feature with a
major performance regression is not complete even if it is functionally correct; measure
first, record the baseline, then optimize. The milestone benchmark obligation and the
safety limits are AGENTS.md §20 and §21.

---

# 18. Compatibility Rules

Avoid unnecessary platform coupling: recent Chrome first and Chromium-compatible
browsers where practical; the frontend does not depend on extension-only APIs; the
extension communicates through stable HTTP/application contracts; source adapters
isolate external API/schema changes; database migrations are versioned; dataset versions
are recorded; exported projects use documented schemas. Chrome integration must remain
replaceable by another browser integration later.

---

# 19. What Not to Build Yet

Out of scope for the first product: full patent-office replacement; legal opinion engine;
autonomous freedom-to-operate conclusions; generalized scientific IDE; ELN/LIMS;
synthesis planning; docking/MD/FEP; wet-lab orchestration; full Markush search engine;
large-scale proprietary web crawler; automated CAPTCHA solving; autonomous Espacenet
scraping; full DataWarrior clone; PDF OCSR as the primary data path. Classification of
new scope follows AGENTS.md §37.

---

# 20. First Engineering Task

Historical: M0 and the first vertical slice were built from this instruction list (inspect
the repository, write the architecture documentation, define the domain model and adapter
contracts, Docker development environment, minimal React and FastAPI applications,
PostgreSQL + RDKit storage, a small SureChEMBL Parquet fixture queried through DuckDB,
one patent with its compound list, lazy depictions, evidence links, benchmarks, tests,
and an explicit statement of what stayed stubbed).

It is kept only as the shape of a good first slice. The current entry point is the
handoff block at the top of this file, and the gate the next work has to satisfy is
`docs/online-capability.md` §6 (checklist + invited-user script).

The first release should feel small, coherent, and reliable rather than broad.
