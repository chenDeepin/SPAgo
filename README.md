# SPAgo

**Small molecule patent analysis GO**

SPAgo connects patent search, chemical structures, bioactivity, SAR, claims, and source evidence in one browser-first workflow.

The project is designed for medicinal chemists, computational chemists, patent researchers, and drug-discovery teams who currently move repeatedly between patent websites, PDFs, chemistry tables, public databases, and general-purpose LLMs.

---

# Current status: M0–M5 local demo implementation, with open acceptance gaps

- one-command local startup: `docker compose up -d --build` → `http://localhost:8000`;
- **M0 Foundation**: FastAPI core + React workspace (search → family → compounds → evidence),
  PostgreSQL 15 + RDKit cartridge, versioned migrations, idempotent seeding, DuckDB-over-Parquet
  bulk layer, lazy cached RDKit depictions;
- **M1 Patent Chemistry Viewer**: save-to-project (idempotent), CSV/SDF export with patent ids,
  labels, evidence references and dataset version; structure detail drawer; bulk selection;
- **M2 Structure Search**: exact / substructure / similarity against cartridge-indexed chemistry,
  molecule filters, stereo-preserving matching, explicit run + removable results chip
  (embedded Ketcher editor is deferred — see the M1–M5 plan record);
- **M3 Bioactivity / SAR**: typed targets/assays/measurements with provenance, Murcko scaffold
  grouping, ChEMBL + BindingDB adapter contracts (sealed-fixture tested), activity column and
  evidence-panel bioactivity with "no ranking across assays" semantics;
- **M4 Chrome Companion**: thin MV3 context bridge (URL-only detection → side panel → `?q=` deep
  link); detection contract covered by `apps/chrome-extension/check.js`;
- **M5 Evidence-Grounded AI**: offline extractive provider with evidence citations and honest
  `machine_extracted` labeling; deterministic query planner; AI as an inspector tab;
- Prior implementation record reports 88 passing automated tests; benchmark baseline under `benchmarks/`. These results are not a fresh verification of every current workflow.

M6 (PDF/OCSR) is intentionally not started. Gaps (e.g. Ketcher embedding, Chrome-in-Chrome
verification, live ChEMBL calls) are recorded in `docs/archive/2026-09-14-m1-m5-implementation.md`.
The follow-up review and proposed acceptance work are in
[the UI review plan](docs/plans/2026-09-14-ui-review-next-round.md).

The dataset shipped with this repo is a **synthetic demo fixture** (`DEMO-*` identifiers).
It is not scientific data.

## Quick start (local)

```bash
docker compose up -d --build
# open http://localhost:8000 and search: DEMO-PATENT-A
```

For development without Docker rebuilds, see `services/core/README.md`
(backend hot reload against the compose `db` service, Vite dev server on :5173).

---

# Why SPAgo?

A typical medicinal-chemistry patent workflow is fragmented:

```text
Espacenet
   ↓
Patent PDF
   ↓
Find compounds manually
   ↓
Find assay tables manually
   ↓
Spreadsheet / DataWarrior
   ↓
BindingDB / ChEMBL
   ↓
LLM / notes
```

SPAgo aims to turn this into:

```text
Search
   ↓
Patent family
   ↓
Compounds
   ↓
Structure filtering
   ↓
Bioactivity / SAR
   ↓
Claims + evidence
   ↓
AI-assisted interpretation
```

The goal is not simply to search patents faster.

The goal is to make patent chemistry directly usable for drug-discovery decisions.

---

# Core Product Idea

SPAgo treats the following relationship as the fundamental unit:

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

This allows users to move between chemical structure, activity data, patent context, claims, and original evidence without rebuilding those relationships manually.

---

# How SPAgo Is Different

Existing platforms already solve important pieces of the problem.

SPAgo should reuse those capabilities rather than reproduce them.

Its differentiation is the workflow connecting them.

## 1. Evidence-linked chemistry

A compound or activity value should link back to where it came from:

```text
WO-XXXXXXXX
→ Example 153
→ Table 12
→ Compound 153
→ CDK4 IC50 = 2.1 nM
```

Evidence is a first-class object, not an afterthought.

## 2. Cross-patent chemical normalization

Patent-local names such as:

```text
Compound 15
Example 32
Intermediate 7
```

are connected to normalized chemical identities while preserving their original patent context.

## 3. Structure-native patent exploration

Users can combine chemical and patent filters.

Examples:

```text
target = CDK4
publication year >= 2023
assignee = selected companies
substructure = selected scaffold
CDK4 IC50 < 20 nM
CDK4/CDK6 selectivity > 10
```

## 4. Cross-patent SAR

SPAgo is intended to eventually answer questions such as:

```text
Which scaffold families dominate this target?

What substitutions are associated with improved potency?

Which modifications appear related to selectivity?

Which family first disclosed this chemical space?

Which compounds are supported by quantitative assays?

Which molecules occur in claims versus examples only?
```

## 5. Evidence-grounded AI

LLMs assist with:

- query interpretation;
- patent summaries;
- SAR interpretation;
- claim explanation;
- family comparison;
- evidence synthesis.

LLMs do not replace deterministic chemistry or source data.

---

# Product Philosophy

SPAgo follows five principles.

### One product, not many tools

The user sees one coherent workspace.

External libraries and data sources remain implementation details.

### Preserve existing habits

SPAgo can be used as a standalone Web App.

An optional Chrome extension can complement Espacenet or other patent websites without replacing the user's normal browsing workflow.

### Progressive disclosure

Common workflows stay simple.

Advanced filters and analysis appear only when requested.

### Deterministic chemistry

Structure identity, substructure search, fingerprints, similarity, and descriptors are handled by chemistry software rather than LLM inference.

### Evidence before interpretation

Scientific conclusions should remain traceable to source evidence.

---

# User Experience

The initial application should expose only four major concepts:

```text
Search
Results / Molecules
Evidence
AI
```

A possible desktop layout:

```text
┌──────────────────────────────────────────────────────────┐
│ Search | Structure | Target | Assignee | Date | Filters │
├──────────────┬──────────────────────────┬────────────────┤
│ Patent       │ Molecule / SAR Table     │ AI             │
│ Families     │                          │                │
│              │ Structure | Data | ...   │                │
├──────────────┴──────────────────────────┴────────────────┤
│ Evidence / Patent Source                                │
└──────────────────────────────────────────────────────────┘
```

Advanced capabilities should not create permanent UI clutter.

---

# Browser Integration

SPAgo is Web-first.

The complete product works without a browser extension.

An optional Chrome Manifest V3 extension can provide:

```text
current patent page
      ↓
detect publication number
      ↓
SPAgo side panel
      ↓
open full workspace if needed
```

The extension remains intentionally thin.

It does not scrape Espacenet automatically and does not attempt to bypass robot detection or CAPTCHAs.

---

# Architecture

SPAgo starts as a modular monolith.

```text
┌─────────────────────────────┐
│ Browser                     │
│                             │
│ React / TypeScript          │
│ Ketcher                     │
│ virtualized chemical table  │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│ SPAgo Core             │
│                             │
│ FastAPI                     │
│ query services              │
│ chemistry services          │
│ source adapters             │
│ evidence services           │
│ LLM orchestration           │
└───────────┬─────────┬───────┘
            │         │
            ▼         ▼
   PostgreSQL       DuckDB
   + RDKit             │
            │           ▼
            │    SureChEMBL Parquet
            │
            ▼
     Project / chemistry
     / evidence state
```

External sources are accessed through adapters:

```text
SureChEMBL
EPO OPS
BindingDB
ChEMBL
```

Additional sources may be added later without changing the UI's domain model.

---

# Why Two Data Layers?

Patent search can involve very large datasets.

Trying to load everything into one application database creates unnecessary storage, update, and maintenance costs.

SPAgo therefore separates workloads.

## Bulk analytical layer

SureChEMBL bulk data remain in Parquet where practical.

DuckDB performs:

- filtering;
- projection;
- joins;
- aggregation;
- initial candidate selection.

## Interactive chemistry layer

PostgreSQL + RDKit handles:

- exact structures;
- substructure search;
- similarity;
- fingerprints;
- normalized project chemistry.

## Application layer

PostgreSQL stores:

- projects;
- annotations;
- evidence;
- source records;
- saved compounds;
- activity data;
- analyses.

---

# Large Dataset Strategy

The browser never receives the entire result set.

SPAgo uses:

```text
server-side filtering
server-side sorting
pagination / cursors
virtualized rendering
lazy molecule depiction
cached structures
lazy evidence retrieval
```

The table should remain responsive even when the underlying query represents very large result spaces.

Default API pages should remain small.

Molecule depictions should be generated or loaded only when they are needed.

---

# Core Domain Model

Initial domain objects:

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

Important:

```text
Compound
```

is a normalized chemical entity.

```text
CompoundMention
```

is a specific occurrence in a patent.

These concepts must remain separate.

---

# Evidence Model

Every important scientific record should preserve provenance.

Example:

```text
Evidence
├── patent document
├── section
├── page
├── paragraph
├── table / figure
├── example
├── patent-local compound ID
├── raw source excerpt
├── source identifier
├── extraction method
└── confidence
```

Possible provenance states:

```text
SOURCE_FACT
DATABASE_CURATED
MACHINE_EXTRACTED
LLM_INFERRED
USER_CURATED
```

---

# Data Sources

## SureChEMBL

Primary broad source for patent-associated chemical structures.

Use bulk datasets as the main scalable access path.

## EPO OPS

Patent bibliographic, family, legal-status, text, and document enrichment.

Access through official APIs.

## BindingDB

Curated compound-target activity enrichment.

Useful as a high-quality activity source, but not assumed to provide complete current patent coverage.

## ChEMBL

Compound, target, assay, activity, and external chemistry enrichment.

---

# Chemistry Layer

RDKit is the canonical backend chemistry engine.

Responsibilities include:

```text
structure parsing
normalization
canonicalization
fingerprints
substructure
similarity
scaffolds
descriptors
2D depictions
```

Ketcher is used for interactive structure drawing.

Ketcher should not become a mandatory external application; it is embedded in the Web App.

---

# LLM Layer

LLMs should operate above deterministic data systems.

A typical request:

```text
"Find recent selective CDK4 inhibitor patents and compare
the chemical changes associated with CDK4/CDK6 selectivity."
```

may be translated into:

```text
natural language
      ↓
query plan
      ↓
patent metadata search
      +
structure filtering
      +
activity retrieval
      +
family grouping
      ↓
evidence set
      ↓
LLM interpretation
```

The LLM interprets results.

It does not invent the underlying scientific facts.

---

# Installation

The preferred user experience is hosted:

```text
Open SPAgo
→ use it
```

For local deployment, the target is:

```bash
git clone <repository>
cd spago
docker compose up -d --build
```

Then open the local Web App.

Users should not need to manually install or configure:

```text
Python
Node.js
PostgreSQL
RDKit
DuckDB
Java
DataWarrior
```

---

# Repository Layout

Initial target structure:

```text
spago/
├── AGENTS.md
├── README.md
├── docker-compose.yml
├── .env.example
│
├── apps/
│   ├── web/
│   └── chrome-extension/
│
├── services/
│   └── core/
│
├── packages/
│   ├── domain/
│   ├── api-client/
│   ├── ui/
│   └── chemistry-types/
│
├── backend/
│   ├── api/
│   ├── chemistry/
│   ├── evidence/
│   ├── queries/
│   ├── projects/
│   ├── llm/
│   └── adapters/
│       ├── surechembl/
│       ├── epo_ops/
│       ├── bindingdb/
│       └── chembl/
│
├── data/
│   ├── fixtures/
│   └── README.md
│
├── migrations/
│
├── benchmarks/
│
├── tests/
│   ├── chemistry/
│   ├── adapters/
│   ├── integration/
│   ├── e2e/
│   └── performance/
│
└── docs/
    ├── architecture/
    ├── adr/
    ├── data-model/
    └── roadmap/
```

Do not interpret this structure as permission to create empty packages.

Create packages only when implementation requires them.

---

# Development Roadmap

## Milestone 0 — Foundation

Build:

- application skeleton;
- Docker development environment;
- PostgreSQL + RDKit;
- domain model;
- source adapter contracts;
- evidence model;
- SureChEMBL Parquet fixture;
- DuckDB query proof;
- benchmark harness.

Success means the architecture is measurable and reproducible.

---

## Milestone 1 — Patent Chemistry Viewer

Build:

- patent-number search;
- family summary;
- molecule table;
- 2D depictions;
- evidence panel;
- project save.

Success means a medicinal chemist can inspect patent chemistry without manually browsing the PDF for the common path.

---

## Milestone 2 — Structure Search

Build:

- Ketcher;
- exact structure search;
- substructure search;
- similarity search;
- molecular filters.

Success means chemical structure and patent metadata can be queried together.

---

## Milestone 3 — Bioactivity / SAR

Build:

- BindingDB;
- ChEMBL;
- normalized activity data;
- scaffold grouping;
- SAR table.

Success means users can compare compounds scientifically rather than only browse structures.

---

## Milestone 4 — Chrome Companion

Build:

- Manifest V3 extension;
- side panel;
- patent-page context detection.

Success means users can continue their existing Espacenet workflow while opening SPAgo alongside it.

---

## Milestone 5 — Evidence-Grounded AI

Build:

- natural-language query planner;
- patent summaries;
- cross-family comparison;
- SAR interpretation;
- evidence citations.

Success means AI accelerates reasoning without hiding the supporting data.

---

## Milestone 6 — PDF Chemistry Fallback

Potential future work:

- PDF layout extraction;
- table extraction;
- OCSR;
- image-compound association;
- confidence scoring;
- manual review.

This should be added only after measuring gaps in structured-source coverage.

---

# MVP User Journey

The first complete user journey is deliberately narrow.

```text
Open SPAgo

→ Enter patent publication number

→ View patent family

→ View extracted compounds

→ Inspect 2D structures

→ Draw a scaffold

→ Run substructure filter

→ Select compound

→ Inspect source evidence

→ View available bioactivity

→ Save selected compound/family to project

→ Ask AI for an evidence-grounded summary
```

If this workflow is not excellent, do not broaden the product.

---

# Non-Goals for v1

SPAgo v1 is not intended to be:

- a patent-office replacement;
- an autonomous legal-advice system;
- a complete Markush platform;
- a generalized AIDD IDE;
- a docking platform;
- an MD/FEP platform;
- a synthesis planner;
- an ELN;
- a LIMS;
- a web crawler designed to defeat access restrictions;
- a full DataWarrior replacement.

---

# Engineering Principle

The product should become more powerful without becoming harder to use.

New functionality should generally appear as:

```text
better data
better relationships
better evidence
better queries
better context
```

rather than:

```text
more panels
more buttons
more services
more installation steps
more user-facing tools
```

---

# North-Star Workflow

SPAgo should eventually make the following interaction natural:

> Find small-molecule patents relevant to a drug target, cluster the compounds by chemical scaffold, identify quantitative potency and selectivity data, compare related patent families, show where every important value originated, and explain the resulting medicinal-chemistry landscape.

All while keeping the original patent evidence one click away.

That is the product.
