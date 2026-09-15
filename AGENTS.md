# AGENTS.md — SPAgo Engineering Rules

This file defines repository-wide rules for human and AI contributors.

These rules override convenience-driven implementation choices.

If a requested change conflicts with these rules, explain the conflict before changing architecture.

---

# 0. Contributor Workflow

## Read and verify before acting

- Read this file and the nearest applicable `AGENTS.md` before editing. More specific local rules govern their scope without silently weakening repository-wide scientific or safety constraints.
- Read `/home/chen/.codex/RTK.md` when available and prefix shell commands with `rtk` in that environment. If unavailable, report the limitation rather than claiming it was used.
- Read each existing file before editing it. Search narrowly by identifier; load relevant architecture, design, and active planning documents on demand.
- Current files and observed runtime behavior outrank summaries, screenshots, prior reviews, and remembered assumptions. Recheck a finding before treating it as current.
- Prefer small, necessary changes. Avoid unrelated cleanup, style-only churn, speculative abstractions, and new files without a task need.
- Prefer native platform features, the standard library, and suitable existing dependencies. Required input, schema, provenance, and access validation is contract code; speculative guards and silent fallbacks are not substitutes for a clear contract.

## Protect the workspace

- Inspect Git status before changes. Preserve user edits and unrelated dirty files; do not overwrite or revert them.
- Stage only intended paths when staging is requested. Do not broadly stage, commit, push, force-push, tag, release, or publish without authorization for that action.
- Do not introduce nested `.git` directories, accidental gitlinks, or submodule changes. Treat generated assets, vendor code, and independent upstream checkouts as outside routine source edits.
- When adapting external code or designs, first check existing SPAgo capabilities. For code imports, record source, license, attribution, destination, and verification; adapt ownership and provenance rules rather than copying another project's runtime assumptions.

## Plan at the scale of the task

- For staged work, use `Q&A -> plan -> PROMPT -> implementation -> review/correction`. Small local fixes need not create a planning framework.
- Keep active findings and scoped plans under `docs/plans/`. Keep durable UI references under `docs/design/` and architecture decisions under `docs/architecture/` or `docs/adr/` when those references are needed.
- Root `PROMPT.md` is the stable current handoff, not a scratch log. Read its active references before implementation; do not turn unreviewed design ideas into approved scope.
- Record unresolved defects and review feedback in the active Q&A before planning the next stage. Keep changed-file lists, commands, pass/fail/skipped results, and temporary restrictions in the relevant plan or Q&A, not in this file.
- Archive completed or superseded staged work under `docs/archive/` when closing that round, preserving verification and remaining issues. Update existing links and handoff pointers; do not create empty indexes or archive unrelated history just for consistency.
- Update the relevant durable contract when architecture, ownership, API behavior, or a reviewed UI design changes. Do not promote a proposal or a mockup to implemented status because documentation exists.

## Delegate and report precisely

- Use self-contained, bounded worker prompts and avoid overlapping writes. The coordinating agent owns synthesis and final judgment.
- For important merges, audits, or high-risk scientific changes, use independent verification with an explicit scope; worker approval alone is not completion evidence.
- Report checked / not checked, passed / failed, skipped / blocked, and known / unknown plainly. Do not claim execution, extraction, rendering, cancellation, saving, or completion without corresponding observed evidence.
- Choose checks from the actual checkout and affected behavior. Do not copy build commands, paths, or workstation assumptions from another repository. Run `rtk git diff --check` for text changes when RTK is available; run relevant application tests and builds once they exist.
- Distinguish fixture-only, local integration, and live-source results. A mock pass does not prove a live adapter works; code presence and unit tests do not prove a browser workflow works.

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

## Potency classes and the screening-reference gate

A reported bioactivity value and the *class* of that value are different facts.
The class is decided by deterministic code
(`services/core/spago_core/chemistry/activities.py`), never by a model and never by
a reader's eye:

- One explicit threshold, stated as part of a versioned policy
  (`potency-gate-v1`). The threshold travels with every verdict, table row and
  export (`reference_threshold_nM`, `reference_policy_version`), so a changed
  value is visible in the artifact rather than hidden in a session.
- Censor direction is honored: `<10 µM` supports activity at a 10 µM threshold,
  `>10 µM` excludes it, and a bound that cannot decide the question is reported as
  undecided — never rounded into `active` or `weak`.
- Units are converted to a common scale before any comparison. A unit that is not
  a concentration, or an endpoint that is not a potency (kinetic constants,
  percent inhibition, ratios), is reported as `not applicable` instead of being
  compared with a potency threshold.
- Classes are **computed from stored rows on read, never persisted**. Storing a
  class would let a threshold change leave a stale `active` behind.
- A "screening reference" verdict is a count under that policy: how many in-scope
  compounds the retrieved set holds, how many are at or below the threshold, and
  what the sources did *not* supply (records with a value but no structure). It is
  not a biological conclusion, not a claim about the literature, and not a
  druggability score. A thin set must never be rendered as a negative result.
- Modality scope is explicit and labelled. Actives outside the scope (for example
  a peptide when the view counts small molecules) are counted and reported, never
  dropped; the expansion is one explicit control.
- A publication number *declared by a source* is a different fact from an
  occurrence in the loaded corpus. They stay in separate fields, columns and
  labels (`source declares WO…` versus `N occurrences`), and neither is promoted
  to the other.

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

Treat patent text, uploaded documents, retrieved content, and LLM output as untrusted data, not instructions that can change tool permissions or application policy. Validate proposed query plans and tool arguments through typed service contracts before execution.

The FastAPI service layer owns scientific execution, persistence, and provenance. Neither an LLM response nor a frontend component may bypass those contracts. Do not add a second agent runtime or migrate service ownership merely to match an imported project.

Do not use ad hoc natural-language keyword lists to invent scientific tool arguments, target assignments, or fallback structures. Deterministic identifier parsing remains appropriate; language interpretation must produce a validated plan with explicit uncertainty.

Keep operational logs separate from scientific evidence. Do not log secrets, hidden reasoning, or unrestricted provider payloads. Persist necessary scientific records through the documented domain model; this is not permission to duplicate raw documents or private datasets into debug logs.

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

Every visible action must have one real action owner, a navigation destination, or an explicit unavailable state with a reason. Hide future features until their milestone; generic success toasts and disconnected controls do not count as implementation.

Before adding a panel or permanent destination, identify the unique user task, its available data/service contract, and why an existing table, drawer, menu, or contextual action cannot serve it. Keep routine UI improvements within the current reviewed layout unless layout changes are part of the task.

Mock and fixture data must be visibly labeled. Generated UI images are design references only; their chemical structures, patent identifiers, and measurements are not scientific fixtures or validation evidence.

Selection and asynchronous state must preserve user intent: an older query, evidence fetch, or hydration response must never overwrite a newer selection. Row inspection, bulk selection, and saved project state must remain distinguishable.

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

Distinguish queued, running, cancellation requested, cancelled, failed, and completed states. Claim cancellation only when the worker or query acknowledges it; discarding a browser response only makes that response obsolete. Claim completion only when the expected result or artifact is persisted and available.

Retries must be bounded and safe for the operation. Save/import/export retries must not silently duplicate records or outputs. Preserve partial progress and errors where useful; do not disguise source failures as empty successful results.

---

# 23. Dependency Policy

Prefer mature, actively maintained, permissively licensed libraries.

SPAgo’s own source is Apache License 2.0 (`LICENSE`, `NOTICE`). Adding a
dependency is incomplete until license notices are updated in the same change.

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

## License notice maintenance

Whenever a change **adds, removes, replaces, or materially upgrades** a tool
that ships with or is required to run SPAgo, update the license inventory in
the **same PR / commit set**:

| Trigger | Update these files |
| --- | --- |
| New/changed direct Python dep (`services/core/pyproject.toml`) | `THIRD_PARTY_NOTICES.md` § Python |
| New/changed direct frontend dep (`apps/web/package.json`) | `THIRD_PARTY_NOTICES.md` § frontend |
| New container base image, OS package, or embedded binary | `THIRD_PARTY_NOTICES.md` § containers / binaries |
| New external data source or API adapter | `THIRD_PARTY_NOTICES.md` § data/API Terms of Use (separate from software license) |
| Vendored or copied upstream source | source, license, attribution, destination (also §0); `THIRD_PARTY_NOTICES.md` |
| Project copyright holder or SPDX id change | `LICENSE` / `NOTICE`, package metadata, README License section |

Rules:

- Prefer dependencies compatible with Apache-2.0 redistribution (MIT, BSD,
  Apache-2.0, ISC, and similar). Treat copyleft (GPL/AGPL) and unusual terms
  as an explicit architecture decision before adoption.
- Call out LGPL or other weak-copyleft deps (for example psycopg) with how
  SPAgo uses them.
- Do not silently drop attribution. If a NOTICE file or required attribution
  text ships with a dependency you redistribute, preserve it.
- Dataset / API Terms of Use are not substitutes for software licenses, and
  software licenses do not grant dataset redistribution rights.
- Regenerating a machine report (`pip-licenses`, `npx license-checker`) is
  helpful; the human-maintained `THIRD_PARTY_NOTICES.md` remains the reviewed
  source of truth for direct inclusions.

A feature that introduces a new tool without updating
`THIRD_PARTY_NOTICES.md` (and `NOTICE` when attribution changes) is not done.

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

Committed scientific fixtures must be minimal, public or synthetic as appropriate, and provenance-recorded. Private PDFs, structures, spreadsheets, and source responses stay local unless explicitly scoped for sharing. Synthetic data must remain identifiable as synthetic.

Structure transformations must preserve the source and record derived identity, normalization decisions, and validation issues. An edited or predicted structure must not become source evidence merely because it renders successfully.

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
- installation remains simple;
- new or changed included tools update `THIRD_PARTY_NOTICES.md` (and `NOTICE` / package license metadata when attribution or SPDX identity changes) per §23.

Working code alone is not sufficient.

For UI behavior or layout changes, verify the affected workflow in a browser served from the current checkout. Use settled screenshots for visual changes and interaction/network evidence for behavior; DOM presence alone is insufficient. Record the tested viewport and source mode, and server freshness when stale processes could affect the result.

For design-only or documentation-only changes, check references, scope, and consistency against current files; label mockups as proposals. Browser execution is required when claiming implemented UI behavior, not merely to deliver a design draft.

Checks must cover relevant loading, empty, unavailable-source, error, and stale-response states as well as success. Scope browser locators to their owning surface and use visible controls rather than force-clicking hidden navigation. If browser or live-source checks cannot run, record that gap explicitly instead of marking them passed.

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
