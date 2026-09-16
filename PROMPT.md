# SPAgo — Product Contract and Current Handoff

> **Current handoff — 2026-09-17, implementation round 4 (product change).**
> **B-43 delivered: one navigation step, one history entry.** Searching a publication
> from an open target view pushed the same state twice, so Back landed on a duplicate
> and needed a second press. Re-reproduced before the fix (history 2 → **4**, Back twice
> to reach the target view) and verified after (2 → **3**, one Back restores the scope),
> with B-39's per-entry filter state pinned in the same run (`?q=IL6&t=…&th=1` returns
> with `th=1` and its candidate table). `npm run test:e2e` 8 passed. Check:
> `apps/web/scripts/history-step-check.mjs`; record `docs/archive/2026-09-17-history-step.md`.
>
> **The register now holds no ungated engineering item.** Every remaining row is the
> operator's (B-31 hosted acceptance; B-21's claims-source decision; B-09's scientific
> review; B-11's provider choice; B-20's user base; B-16's admin-view decision) or gated
> on a measured need or a decision this checkout cannot produce alone (B-40 reviewed
> comparison task, B-05 dataset + ADR, B-07 bounded design, B-12 scaling need, B-22
> source decision, B-27 user ask, B-28 repeated-batch volume, B-41 pilot friction,
> B-45 no-network runner, B-47 model decision). `docs/plans/backlog.md` §1 states each
> gate per row. The next implementation round therefore starts from a register update —
> an item promoted by real evidence or an operator decision — not from the table as it
> stands.
>
> **Same day, rounds 1–3.** **B-44 delivered** (round 2): a real screen reader (Orca
> 42.0) was driven over both tables by `apps/web/scripts/at-pass.mjs`, with
> `apps/web/scripts/x11-focus.py` giving the driven window the session's activation —
> without it the reader announces nothing at all, a session fault the record names. It
> found that no data cell carried `role="cell"`, so a reader heard "table with 1 row 6
> columns" for a ten-row table; the fix makes it "table with 11 rows 6 columns" with
> real cells. **B-46 delivered** (round 3): each table is one tab stop, the arrow keys
> move the current row, and every row carries an `aria-label` so the reader announces
> `Candidate 2 of 157: WEBQKRLKWNIYKK-UHFFFAOYSA-N, weak IC50 13810 nM, measured
> binding, no patent mapping` (Tab stops inside the compound table 30 → 3, candidate
> table → 1). **B-08 closed with a negative result** (round 2): no documented BindingDB
> path supplies a source-declared assay description or variant context, so the
> capability page was corrected rather than the adapter; the release's `pH`/`Temp (C)`
> columns that no path maps are recorded as **B-47**.
>
> **Actual stage.** A locally implemented product with browser-verified workflow
> correctness, a full CI gate (every push runs the whole backend suite against the
> shipped PostgreSQL+RDKit image and the e2e smoke against the seeded compose stack),
> and a prepared scientific cross-read pack. **Hosted acceptance, the invited
> scientist and the independent human cross-read remain open and operator-gated (B-31,
> B-32's second half).** A local rehearsal, a green CI run or a pass on this desktop
> never closes them.
>
> **Limits that matter to the product loop:**
> - Cells are not focus targets: arrow keys move between rows, not within one, and
>   Orca's own Ctrl+Alt+arrow commands are untested here (it grabs them at the X level;
>   synthetic keys never reach the grab). A two-dimensional grid is not claimed.
> - Reader evidence is one reader, one browser, one platform, one viewport, and the pass
>   is manual and desktop-bound, not part of CI.
> - B-30's retraction needs a *complete* or *empty* ask; failed/partial asks and other
>   access paths are provably untouched, and 155 legacy rows with no recorded access
>   path are never retracted. Document-level corpus absence stays unclaimed.
> - The cohort pack is machine-prepared evidence, not an independent review; B-31's
>   gate needs the human cross-read the pack is shaped for.
> - One live model provider remains historically measured; a second one stays gated.
>   Claims text needs the operator's B-21 decision before any integration (B-22 stays P3).
> - The optional companion's physical toolbar click and side-panel chrome remain
>   unverified. Full cross-family SAR (B-40), PDF/OCSR/M6, Markush and general chat are
>   not delivered.
>
> **Next-stage order:** 1. B-31 retains the real hosted gate in
> `docs/online-capability.md` §6 — host/TLS, readiness, owner isolation, restore,
> provider smoke, source coverage, latency/cost, invited scientist and independent
> reader, with the build-identity recorder and the cohort pack as its tooling.
> Operator-only decisions stay explicit. 2. No ungated engineering item is queued: the
> next implementation round needs a register update (evidence that promotes one of the
> gated items, or the operator's decision), and §1 records why each open row waits.
>
> **Evidence map:** scope and hosted gate `docs/online-capability.md`; operations
> `docs/runbook.md` §H1–H10; per-item delivery records in `docs/plans/backlog.md` with
> their plans and benchmarks under `docs/archive/`; accessibility evidence
> `benchmarks/screen-reader-pass-2026-09-17.{md,txt}` and
> `benchmarks/table-keyboard-2026-09-17.{md,txt}`; the cohort pack
> `benchmarks/cohort-pack-2026-09-16.*`.
> Older rounds in `docs/archive/` are historical records, not the current work queue.
> The rest of this document is the standing product contract; aspirational capabilities
> are not implementation claims.

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
**State: source-backed bioactivity, modality/potency rules and scoped tables are
implemented; full cross-family SAR comparison is not delivered (backlog B-40).
Direct/indirect distinction and measured per-target coverage are in the capability
statement.**

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
**State: family/document/target summaries and validated plans are implemented offline
and against one historically measured live provider; citations navigate to the exact
record they name across the live panels and the analyses archive (B-37, 2026-09-16),
and stored analyses attach to projects (B-29). Full family comparison is not
delivered; the independent scientific cross-read (B-32's gated half) remains open.**

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
