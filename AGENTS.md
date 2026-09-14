# AGENTS.md — SPAgo Engineering Rules

This file defines repository-wide rules for human and AI contributors.

These rules override convenience-driven implementation choices.

If a requested change conflicts with these rules, explain the conflict before changing architecture.

---

# 1. Mission

SPAgo (small molecule patent analysis GO) is a structure-native patent intelligence workspace for small-molecule drug discovery.

Its purpose is to connect:

```text
patents
patent families
chemical structures
compound examples
bioactivity
claims
evidence
medicinal-chemistry interpretation
```

into one reliable workflow.

Optimize for:

```text
scientific usefulness
simplicity
traceability
performance
compatibility
maintainability
```

Do not optimize for the number of features.

---

# 2. Primary Product Rule

Do not build a toolbox.

Build a workflow.

A new library, panel, data source, service, model, or module is justified only if it improves a defined user workflow.

Before introducing a component, answer:

```text
What user problem does this solve?
Why can the existing architecture not solve it?
What additional operational burden does it create?
Can it remain internal instead of becoming a user-facing concept?
```

If those questions do not have strong answers, do not add the component.

---

# 3. Preserve User Habits

SPAgo should augment existing workflows rather than replace them unnecessarily.

Users may continue using:

- Espacenet;
- Google Patents;
- patent-office websites;
- spreadsheets;
- DataWarrior;
- external chemistry applications.

SPAgo should make those workflows faster.

Do not intentionally trap users in SPAgo.

Always preserve:

- source links;
- patent numbers;
- export capability;
- SMILES/InChIKey;
- CSV/SDF where relevant;
- evidence references.

---

# 4. Web App Is the Product

The standalone Web App is the canonical product.

The Chrome extension is optional.

Never put essential business logic exclusively in the Chrome extension.

The extension may:

- identify a patent;
- receive page context;
- open the side panel;
- communicate with SPAgo.

The extension must not own:

- scientific datasets;
- chemistry indices;
- PDF extraction;
- LLM orchestration;
- project state;
- core search logic.

---

# 5. No Espacenet Automation

Do not implement:

- automatic Espacenet navigation;
- automated result pagination;
- simulated user clicks;
- CAPTCHA solving;
- robot-detection bypass;
- scraping designed to evade access controls.

Prefer:

- EPO OPS;
- official APIs;
- bulk datasets;
- user-initiated source-page access.

---

# 6. Modular Monolith First

Default architecture:

```text
React frontend
        ↓
FastAPI core
        ↓
PostgreSQL + RDKit
        +
DuckDB / Parquet
```

Do not introduce a new infrastructure service merely because it is common in large systems.

The following require a written architecture decision and benchmark evidence before introduction:

- Redis;
- Elasticsearch/OpenSearch;
- Kafka;
- RabbitMQ;
- Celery;
- Kubernetes;
- separate vector database;
- graph database;
- additional transactional database;
- distributed object store;
- independent microservices.

Prefer code-level modules with stable interfaces.

---

# 7. Storage Responsibilities

Use storage systems according to workload.

## PostgreSQL

Use for:

- projects;
- users;
- annotations;
- normalized compounds;
- evidence;
- source records;
- cached metadata;
- activity records;
- persisted analyses.

## PostgreSQL + RDKit

Use for:

- chemical identity;
- structure indexing;
- exact search;
- substructure search;
- similarity search;
- chemistry descriptors required for interaction.

## DuckDB + Parquet

Use for:

- SureChEMBL bulk datasets;
- analytical filtering;
- aggregations;
- dataset exploration;
- bulk-data joins where materialization is unnecessary.

Do not duplicate the complete bulk dataset into PostgreSQL by default.

---

# 8. External Source Isolation

External APIs and datasets must be accessed through adapters.

UI components must never depend directly on a SureChEMBL, OPS, BindingDB, ChEMBL, or PubChem schema.

Required pattern:

```text
external source
      ↓
adapter
      ↓
normalized domain model
      ↓
service/query layer
      ↓
API
      ↓
UI
```

Every adapter must expose:

- source name;
- source version if available;
- retrieval timestamp;
- normalized identifiers;
- errors;
- rate-limit state where relevant.

External schema changes should require adapter changes, not application-wide changes.

---

# 9. Evidence Is a First-Class Entity

Never treat evidence as plain text attached to an LLM response.

Evidence must have a typed record.

Whenever possible record:

```text
patent
section
page
paragraph
table
figure
example
compound label
source URL/identifier
extraction method
confidence
```

Scientific statements displayed as facts should be traceable to evidence.

---

# 10. Provenance States

Every important scientific datum should carry provenance.

Use explicit states such as:

```text
SOURCE_FACT
DATABASE_CURATED
MACHINE_EXTRACTED
LLM_INFERRED
USER_CURATED
```

Do not silently upgrade:

```text
LLM_INFERRED
```

to:

```text
SOURCE_FACT
```

Human correction must remain distinguishable from imported source data.

---

# 11. Chemistry Must Be Deterministic

Use cheminformatics code for chemistry.

Use RDKit or another explicitly approved deterministic chemistry engine for:

- canonicalization;
- parsing;
- fingerprints;
- similarity;
- substructure;
- scaffold extraction;
- molecular descriptors;
- identity comparisons.

Do not use LLM output to decide molecular equivalence.

Preserve stereochemistry unless a workflow explicitly requests stereo-insensitive comparison.

Record normalization decisions.

---

# 12. LLM Boundary

LLMs may:

- interpret language;
- build query plans;
- summarize patents;
- compare families;
- interpret SAR;
- explain claims;
- identify uncertainty;
- synthesize evidence.

LLMs must not silently invent:

- structures;
- activity values;
- patent numbers;
- claim scope;
- assay conditions;
- target assignments.

Answers containing factual scientific conclusions must expose evidence or clearly state that the result is an inference.

---

# 13. Large Data Is Server-Side

Never send an entire large search result into the browser.

Default API page size:

```text
100
```

Ordinary maximum:

```text
500
```

Use:

- server-side filtering;
- server-side sorting;
- cursor pagination where appropriate;
- query cancellation;
- caching;
- virtualized rendering.

Do not use client-side filtering as the primary mechanism for large datasets.

---

# 14. Molecule Rendering Rules

Chemical structures are expensive UI objects.

Rules:

- render only visible or near-visible structures;
- use lazy loading;
- cache generated depictions;
- avoid recalculating unchanged 2D coordinates;
- do not render thousands of SVG molecules simultaneously;
- use placeholders during scrolling rather than blocking the UI.

Structure-editor code and structure-grid depiction code should remain separate.

Ketcher is an editor, not the rendering engine for every result row.

---

# 15. Query Rules

Every expensive query must support cancellation or obsolescence.

Text search should use debounce where appropriate.

Structure search must not execute on every drawing event.

Explicit user action should normally trigger substructure or similarity search.

Do not perform uncontrolled parallel requests to external APIs.

---

# 16. External API Rules

All external requests require:

- timeout;
- retry policy where safe;
- cache strategy;
- clear error handling;
- rate limiting;
- source identification.

Do not make OPS calls from individual rendered table rows.

Aggregate and cache queries.

If a source is unavailable, the rest of the application should continue functioning where possible.

---

# 17. Progressive Disclosure

Avoid UI clutter.

The default interface should emphasize:

```text
Search
Results
Evidence
AI
```

Advanced capabilities belong behind:

- drawers;
- dialogs;
- expandable filters;
- contextual menus;
- optional modes.

Do not permanently display every available control.

A new feature does not automatically deserve a new panel.

---

# 18. No Duplicate Controls

Before adding a button or action:

1. search for existing actions;
2. check contextual menus;
3. check keyboard/command actions;
4. reuse existing state transitions.

Do not create multiple buttons that perform the same conceptual action under slightly different names.

---

# 19. URL and State

Important search and view state should be reproducible.

Where appropriate encode:

- patent query;
- filters;
- selected family;
- selected compound;
- active project;

in navigable application state.

Do not encode sensitive or enormous state in URLs.

---

# 20. Performance Is a Feature

Every milestone must retain a benchmark.

Track at minimum:

```text
startup
patent lookup
metadata filtering
substructure search
similarity search
table response time
response payload size
molecule depiction
memory consumption
large-table scrolling
external API calls
```

Never claim optimization without measurement.

Performance regressions must be documented.

---

# 21. Performance Safety Limits

Unless there is a documented reason:

- do not return more than 500 ordinary result rows per API response;
- do not render non-visible structure cards;
- do not load a complete bulk dataset into process memory;
- do not synchronously extract large PDFs during an interactive HTTP request;
- do not call an external patent service once per table row;
- do not recompute unchanged chemical fingerprints;
- do not send raw complete patent PDFs to an LLM when selected evidence is sufficient.

---

# 22. Background Work

Expensive tasks should use persisted job state.

Examples:

- PDF processing;
- OCSR;
- large imports;
- dataset refresh;
- large evidence extraction;
- report generation.

The first implementation may use a simple database-backed job mechanism.

Do not introduce a distributed queue until necessary.

---

# 23. Dependency Policy

Prefer mature, actively maintained, permissively licensed libraries.

Before adding a major dependency, document:

```text
purpose
license
maintenance status
bundle/runtime cost
alternatives considered
```

Avoid overlapping dependencies that solve the same problem.

One primary library per responsibility is preferred.

---

# 24. Installation Rule

A scientist must not need to manually install a cheminformatics stack.

Supported goal:

```text
docker compose up -d --build
```

or hosted deployment.

Do not require end users to separately configure:

- RDKit;
- PostgreSQL;
- Python;
- Node;
- Java;
- DuckDB.

Developer setup may be more flexible, but the supported user path must remain simple.

---

# 25. Dataset Versioning

External bulk data must be versioned.

Record:

```text
source
release date
download/checksum
schema version
ingestion/index version
```

A saved analysis should be able to state which dataset release it used.

---

# 26. Database Migrations

All schema changes require migrations.

Never rely on manual database modification.

Migrations must remain forward-testable from the last supported release.

Destructive migrations require explicit review.

---

# 27. Test Pyramid

Required test categories:

```text
unit
chemistry correctness
adapter contract
database integration
API integration
frontend interaction
end-to-end
performance regression
```

Maintain sealed fixtures for known patent cases.

Scientific correctness tests are as important as software tests.

---

# 28. Chemistry Regression Fixtures

Keep fixed tests for:

- identical molecule;
- different salts;
- stereoisomers;
- tautomers where relevant;
- substructure positive;
- substructure negative;
- high-similarity pair;
- low-similarity pair;
- malformed structure;
- patent-local compound labels.

Never change expected chemistry behavior simply to make a failing test pass.

---

# 29. Source Regression Fixtures

Maintain patent fixtures covering:

- multiple documents in one family;
- multiple compounds;
- duplicate structures;
- claims versus description;
- image-derived compound occurrence;
- known activity values;
- missing activity;
- incomplete metadata.

---

# 30. No Premature OCSR

PDF chemistry extraction is a fallback capability.

Do not make OCSR part of the critical search path while high-quality structured data are already available.

Add OCSR only when:

- missing coverage is measured;
- representative failures are collected;
- evaluation fixtures exist.

---

# 31. Markush Scope

Do not describe SPAgo as a complete Markush search engine until it has been independently validated for that task.

Simple R-group handling and Markush-aware extraction may be developed later.

Avoid misleading product claims.

---

# 32. Legal Boundary

SPAgo may assist with:

- patent organization;
- claims navigation;
- evidence extraction;
- chemistry comparison;
- landscape exploration.

It must not present LLM output as legal advice or definitive freedom-to-operate conclusions.

---

# 33. Documentation Before Architecture Expansion

Any major architecture change requires an ADR or equivalent documented decision.

Explain:

```text
problem
existing limitation
measured evidence
proposed change
alternatives
migration cost
rollback
```

Do not silently rewrite architecture during feature implementation.

---

# 34. Repository Hygiene

Keep generated data, caches, downloaded bulk datasets, database files, PDFs, model files, and secrets out of Git unless explicitly intended as fixtures.

Use small deterministic fixtures for tests.

---

# 35. Secrets

Never commit:

- API credentials;
- OPS secrets;
- tokens;
- private keys.

Use environment variables and documented example configuration.

---

# 36. Definition of Done

A feature is complete only when:

- the user workflow works;
- tests exist;
- provenance is preserved;
- error states are handled;
- performance has not materially regressed;
- documentation is updated;
- duplicate UI has not been introduced;
- installation remains simple.

Working code alone is not sufficient.

---

# 37. Scope Control

Before every substantial implementation, classify it:

```text
CORE
NEXT
LATER
REJECT
```

CORE means necessary for the current vertical slice.

NEXT means already justified for the following milestone.

LATER means useful but premature.

REJECT means contrary to product principles.

Prefer moving ideas to `LATER` over adding them prematurely.

---

# 38. Final Rule

When choosing between:

```text
more features
```

and:

```text
a simpler, faster, more coherent workflow
```

choose the second.

SPAgo wins by connecting scientific information correctly, not by displaying the largest number of tools.