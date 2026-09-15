# SPAgo — Initial Engineering Prompt

> **Current handoff (2026-09-15; baseline `41ef768`, uncommitted ONLINE work in
> the working tree): online SPAgo with LLM enhancement — implemented, not yet
> hosted.**
> ONLINE-00…ONLINE-05 are implemented and locally verified: target-led open-database
> discovery (UniProt + ChEMBL + BindingDB + PubChem), scoped evidence-grounded
> summaries (family / document / target), validated natural-language plans,
> invitation-only hosted sessions with per-owner data, usage quotas and a hosted
> runbook. Read `docs/plans/2026-09-15-online-llm.md` §4 for the verification
> record, and `docs/plans/ui-round-verification/online-beta-acceptance-2026-09-15.md`
> for exactly what is verified versus still open.
>
> **ONLINE-06 (potency-reference verdict, ported from the author's `BindingDB_IO`
> process) is implemented and browser-verified** on the local stack: deterministic
> potency classes under a versioned policy, a screening-reference count per target
> with its stated threshold and modality scope, and source-declared patent/DOI/PMID
> per measurement. Records: `docs/plans/2026-09-15-bindingdb-io-port.md` §6
> (files, commands, browser evidence, defects fixed, gaps) and
> `benchmarks/online06-reference-2026-09-15.md`. The verdict is a **count under a
> stated policy, not a biological or legal conclusion**; on live data TSLP has no
> small-molecule active in these sources, and no live row carries a source-declared
> patent number yet (that rendering path is fixture-tested only).
>
> **ONLINE-07 (hand-added literature rows, same port) is implemented and
> browser-verified** on the local stack: `POST /targets/{id}/supplements` (bounded,
> per-row outcomes), a mandatory per-row note, the same RDKit normalization and
> InChIKey identity as a retrieved structure, `user_curated` provenance that nothing
> promotes, a `target_supplement_remarks` table for rows whose structure is not
> public, a remark count inside the reference verdict, and a candidate export that
> derives its provenance states instead of claiming `database_curated`. Record:
> `docs/plans/2026-09-15-bindingdb-io-port.md` §7 (files, commands, browser evidence,
> open items) and `benchmarks/online07-supplements-2026-09-15.md`. Two clearly
> labelled acceptance rows were stored in the local dev database by that pass
> (target `0cd78fd9-…`); there is no delete path for a hand-added row yet.
>
> **What is NOT done — do not mistake the implementation for acceptance:**
> no **hosted** deployment exists (ONLINE-04 acceptance is open) and no invited
> user has been through the workflow (ONLINE-05 is open). One live model provider
> has been smoke-tested from the dev stack: DeepSeek `deepseek-flash` reached for
> family, document and target scopes and through the browser AI panel, recorded in
> `docs/plans/2026-09-15-llm-live-smoke.md`; that is one provider, not a
> compatibility claim. ONLINE-01 has a repeatable evaluation baseline
> (`benchmarks/online01-llm-eval-2026-09-15.md`: 45 recorded requests over four
> runs, per-call compliance, refusal classes, token cost) and the per-source
> citation defect it found is fixed and re-measured — run 4 answered 18/18
> requests with the target scope clean and citing its three `source:` refs, and the
> new citation chip was checked in the browser
> (`docs/plans/2026-09-15-llm-eval-and-demo-open.md` §7.1). What remains unproven
> is the class *not* recurring for other targets and providers, and content
> correctness: schema validity is not scientific truth.
> Host, provider, budget and cohort remain operator decisions; this work does not
> authorize purchasing infrastructure, sending private datasets to a provider, or
> public deployment.
>
> **Start here for the next turn:**
> 1. Re-read `docs/online-capability.md` (the scope statement) and
>    `docs/runbook.md` §H1–H9 (the hosted deployment contract).
> 2. Carry the recorded live smoke into the hosted acceptance: same model id and
>    endpoint fingerprint, per-scope call, token usage, latency, failure rate,
>    cache behaviour. Quotas (`SPAGO_LLM_USER_TOKEN_LIMIT`
>    / `SPAGO_LLM_DEPLOYMENT_TOKEN_LIMIT`) must be set to real values first.
> 3. Run the acceptance script in the beta record, including a restore against
>    the real host and independent cross-reading of retrieved chemistry.
> 4. Carry the source/job defects listed in plan §4.6 into ONLINE-04.
> 5. If summary quality is measured again, extend the evaluation set before the
>    numbers: the runner has one demo family, one demo document and one live
>    target; a sparse target (`DEMO-TARGET-1`, no retrievals) and a second
>    provider would test the two claims the current record explicitly cannot
>    make. The runner and the record's method section are in
>    `benchmarks/online01-llm-eval-2026-09-15.md`.
>
> Current source coverage is genuinely thin for some acceptance targets (human
> TSLP has one small-molecule candidate in these sources; IL-6R has one and
> BindingDB does not answer for it). Report that honestly rather than promising
> inhibitor coverage. Model output stays inference; chemistry stays deterministic.
> Full-document extraction/M6 and general chat remain deferred.
>
> The previous local milestone is committed at `41ef768`. Historical review,
> verification and unresolved defects remain in
> `docs/plans/2026-09-15-product-readiness.md`; do not mistake its earlier
> uncommitted-state notes or local-first priorities for this stage's status.
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

Build a modular monolith.

Do not introduce microservices unless measured production requirements justify them.

Initial deployment should contain only:

```text
spago-app
    frontend
    API
    source adapters
    chemistry services
    query layer
    LLM/evidence layer

postgres-rdkit
    project data
    normalized chemistry
    searchable structures
    annotations
    evidence
```

SureChEMBL bulk Parquet data should remain an external read-only analytical dataset where practical and be queried through DuckDB.

Do not import the entire SureChEMBL collection into the transactional database merely for convenience.

Only materialize/index data when required by interactive structure search, project persistence, caching, or measured performance needs.

Do not add Redis, Kafka, RabbitMQ, Elasticsearch, Kubernetes, Celery, MinIO, or another database in the MVP unless a benchmark proves that the current architecture cannot satisfy the requirement.

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

Assume that searches can eventually involve hundreds of thousands or millions of compounds.

The browser must never be treated as the database.

Rules:

- server-side filtering;
- server-side sorting;
- server-side pagination or cursor-based retrieval;
- virtualized visible rows;
- lazy molecule depiction;
- lazy evidence loading;
- cancellable searches;
- debounced structure/text queries;
- cached depictions;
- cached normalized structures;
- background processing for expensive document extraction.

Default result page:

```text
50–100 rows
```

Hard maximum for ordinary row API responses:

```text
500 rows
```

Do not return entire patent chemistry datasets as giant JSON arrays.

Do not render thousands of molecule SVGs simultaneously.

Only render structures entering or near the viewport.

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

## Milestone 0 — Foundation and Benchmarks

Deliver:

- monorepo;
- frontend shell;
- backend shell;
- PostgreSQL + RDKit Docker image;
- normalized domain model;
- source adapter interfaces;
- evidence model;
- DuckDB SureChEMBL proof of concept;
- benchmark harness;
- small reproducible test dataset.

Exit criteria:

- one-command local startup;
- health checks pass;
- browser opens successfully;
- test patent can be loaded;
- sample compounds appear;
- benchmark command produces a baseline report.

---

## Milestone 1 — Patent Chemistry Viewer

Deliver:

- patent-number search;
- patent-family detail;
- compound table;
- 2D structures;
- evidence fields;
- structure detail drawer;
- save-to-project.

Exit criteria:

- user can inspect a patent without downloading the PDF for the common workflow;
- user can move from compound to source evidence;
- large result table remains responsive.

---

## Milestone 2 — Structure Search

Deliver:

- Ketcher query input;
- exact search;
- substructure search;
- similarity search;
- molecular filters;
- indexed chemistry storage.

Exit criteria:

- structure query can be combined with patent metadata filters;
- chemical search occurs server-side;
- no large client-side dataset is required.

---

## Milestone 3 — Bioactivity and SAR

Deliver:

- BindingDB adapter;
- ChEMBL adapter;
- activity normalization;
- target mapping;
- SAR-oriented table modes;
- scaffold grouping.

Exit criteria:

- user can compare related compounds across patents and activity sources;
- every external measurement retains provenance.

---

## Milestone 4 — Chrome Companion

Deliver:

- Manifest V3 extension;
- side panel;
- current-patent detection;
- handoff to existing SPAgo session.

Exit criteria:

- installation is optional;
- SPAgo works identically without the extension;
- no Espacenet automation or CAPTCHA bypass exists.

---

## Milestone 5 — Evidence-Grounded AI

Deliver:

- query planner;
- patent summary;
- SAR summary;
- family comparison;
- evidence citations;
- confidence states.

Exit criteria:

- factual AI answers expose evidence;
- unsupported conclusions are visibly marked as inference.

---

## Milestone 6 — Document Extraction Fallback

Only after the previous milestones are stable.

Potential components:

- patent PDF extraction;
- table extraction;
- OCSR;
- compound-label association;
- human review queue.

This is not MVP scope.

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

Every important data path requires tests.

At minimum:

```text
unit
adapter contract
chemistry correctness
API
database integration
frontend interaction
end-to-end
performance regression
```

Create a small set of sealed patent fixtures.

They should cover:

- one patent with many compounds;
- one family with multiple jurisdictions;
- duplicate chemical structures;
- stereochemical differences;
- compounds with bioactivity;
- compounds without bioactivity;
- incomplete external-source data.

Never use only mocked chemistry in acceptance tests.

---

# 17. Performance Regression Rules

Build benchmark scripts before large feature development.

Track:

- patent lookup latency;
- table query latency;
- structure search latency;
- molecule depiction latency;
- memory use;
- response size;
- number of database queries;
- initial page load;
- scroll responsiveness.

A feature that creates major performance regression is not complete even if functionally correct.

Do not optimize blindly.

Measure first, record the baseline, then optimize.

---

# 18. Compatibility Rules

The application should avoid unnecessary platform coupling.

Requirements:

- recent Chrome first;
- Chromium-compatible browsers when practical;
- frontend does not depend on extension-only APIs;
- extension communicates through stable HTTP/application contracts;
- source adapters isolate external API/schema changes;
- database migrations are versioned;
- dataset versions are recorded;
- exported projects use documented schemas.

Chrome integration must remain replaceable by another browser integration later.

---

# 19. What Not to Build Yet

Explicitly out of scope for the first product:

- full patent-office replacement;
- legal opinion engine;
- autonomous IP freedom-to-operate conclusion;
- generalized scientific IDE;
- ELN/LIMS;
- synthesis planning;
- docking/MD/FEP;
- wet-lab orchestration;
- full Markush search engine;
- large-scale proprietary web crawler;
- automated CAPTCHA solving;
- autonomous Espacenet browser scraping;
- full DataWarrior clone;
- PDF OCSR as the primary data path.

---

# 20. First Engineering Task

Do not start with the Chrome extension.

Start with Milestone 0 and the first vertical slice.

Perform these steps:

1. Inspect the repository.
2. Create or update the architecture documentation.
3. Define the domain model.
4. Define adapter contracts.
5. Create Docker-based development environment.
6. Create a minimal React application.
7. Create a minimal FastAPI application.
8. Create PostgreSQL + RDKit storage.
9. Add a small SureChEMBL Parquet fixture.
10. Query it through DuckDB.
11. Render one patent and its compound list.
12. Generate molecule depictions lazily.
13. Add evidence links.
14. Add benchmark scripts.
15. Add automated tests.
16. Document exactly what is implemented and what remains stubbed.

Stop before expanding scope.

Do not implement speculative infrastructure.

At the end, report:

```text
Implemented
Architecture decisions
Tests
Benchmarks
Known limitations
Next vertical slice
```

The first release should feel small, coherent, and reliable rather than broad.
