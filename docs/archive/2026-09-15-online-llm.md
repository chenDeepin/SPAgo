# Online SPAgo with LLM enhancement — next implementation plan

> Archived 2026-09-17 — ONLINE-00…05 implemented (§4 is the record). The hosted gate remains open as **B-31/B-32** and `docs/online-capability.md` §6.

Date: 2026-09-15. Baseline: `41ef768`; working tree was clean before this planning update.
Status: **implemented** (ONLINE-00…05; §4 is the verification record). Hosted acceptance stays open as register items B-31/B-32 and in `docs/online-capability.md` §6. User direction: focus the next version on online use with LLM enhancement, connected to open databases for small-molecule inhibitor investigation of TSLP, CD40L, IL-6/IL-6R and further user-selected targets.

## 1. Q&A and product decision

- **What does online mean here?** Planning assumption: a hosted browser application, initially invitation-only. Scientists open a URL, sign in, search, inspect evidence, generate an analysis, and save/reopen their own projects without installing the chemistry stack. Hosting vendor, domain and budget are not yet selected.
- **What exists?** React/FastAPI/PostgreSQL+RDKit, versioned source-package ingestion, exact/substructure/similarity search, scoped export, saved projects, and an optional Chat Completions adapter for bounded family summaries. The previous review and its 217-test result are historical evidence in [the readiness record](../archive/2026-09-15-product-readiness.md); this planning turn does not rerun those tests.
- **What does not exist?** LLM natural-language search, live-provider acceptance, hosted authentication/project authorization, and a verified online release. The current planner parses publication identifiers only. Current summaries use stored family facts, not complete patent text; configuring a model does not add search interpretation or document retrieval.
- **What is the intended first workflow?** Sign in → enter a target, publication number or natural-language request → resolve target/species and inspect the scope → retrieve open-database candidates and activity evidence → inspect chemistry, assay context and supported patent links → generate a cited analysis → save/reopen a private investigation → export.
- **What data can be searched?** The loaded patent corpus plus bounded, explicit retrieval from supported open databases through adapters. ONLINE-00 adds target-led discovery and real activity; retrieval is not limited to compounds already present in a patent family. Each source reports coverage, retrieval time/version and complete/partial/failed status. No claim of exhaustive or web-wide patent search, or of inhibitor availability for every requested target.
- **Which old gates remain?** Source refresh/retraction, interrupted-job recovery, scientific cross-reading and external-user acceptance remain required. PROD-07 (live LLM) and PROD-08 (hosted access control) become CORE for this release. PROD-06 (real activity) now becomes CORE through ONLINE-00 because target-led small-molecule investigation is an explicit requirement.

## 2. Scope and implementation order

First establish target identity and real open-data evidence, then deliver a verified LLM-assisted workflow in a controlled development environment; hosted users are admitted only after the access-control and deployment gates pass. Each stage ends with review/correction recorded here before expanding scope.

| Stage | Priority | Outcome | Dependencies / gate |
| --- | --- | --- | --- |
| ONLINE-00 | CORE / P1 | Target-led open-database discovery with real compound/assay evidence | Target resolution → ChEMBL vertical slice → BindingDB corroboration and PubChem lookup; target/source coverage matrix passes |
| ONLINE-01 | CORE / P1 | Working live-model summaries with explicit document/family scope | ONLINE-00 evidence slice plus one endpoint/model; live smoke and citation evaluation pass |
| ONLINE-02 | CORE / P1 | Natural-language requests become validated, reviewable searches | Reuse ONLINE-01 provider configuration; typed planner contract and deterministic execution tests pass |
| ONLINE-03 | CORE / P0 before exposure | Invited users can access only authorized projects and analyses | Ownership migration, session/auth design and adversarial two-user API tests pass |
| ONLINE-04 | CORE / P0 before exposure | Operable HTTPS hosted deployment with bounded model usage | ONLINE-03; source/job reliability gates; restore and failure drills pass |
| ONLINE-05 | CORE / P1 | Real users complete the online workflow with trustworthy evidence | ONLINE-00–04 plus scientific evaluation and measured latency/cost acceptance |

### ONLINE-00 — target-led small-molecule investigation and open data

**User targets:** TSLP, CD40L, IL-6 and IL-6R are the first acceptance set. Support additional targets through the same resolver/adapters, not target-specific keyword rules. Default investigation species is human, visibly editable; do not merge ortholog evidence without labeling it.

#### A. Resolve biological scope before retrieval

| User concept | Entities that must stay distinct | Required behavior |
| --- | --- | --- |
| TSLP | TSLP ligand; TSLP receptor components CRLF2/IL7R | Offer receptor/pathway expansion explicitly; do not treat receptor inhibition or reduced TSLP expression as direct TSLP binding. |
| CD40L | CD40LG/CD154 ligand; CD40 receptor; their interaction | Resolve aliases to stable identifiers; interaction disruption is distinct from a measured binding site on either partner. |
| IL-6 / IL-6R | IL6 ligand; IL6R alpha; IL6ST/gp130 signaling component | Ask/declare selected scope; distinguish ligand, receptor, complex and downstream functional readouts. |

Resolve synonyms, species, protein identifiers, target type and component membership using authoritative records (UniProt initially) and source target IDs. The resolver proposes alternatives when ambiguous; the LLM may explain them but cannot silently choose an unrelated target. Persist the resolved scope and mapping provenance. Review protein/complex, mutant and isoform handling before querying activity records.

#### B. Connect sources in useful vertical slices

| Source | Purpose in this workflow | Current code / next work |
| --- | --- | --- |
| UniProt | Stable target identity, aliases, species and components | Add a bounded resolver adapter and reviewed mappings for the acceptance targets; no potency claims from target metadata. |
| ChEMBL | Primary target → molecules → assays/activities → source documents | Extend `adapters/chembl_activity.py`: it currently requires a known target ChEMBL ID and caller compound map and skips unmapped/missing-structure activity. Add target resolution, molecule retrieval and deterministic identity normalization so novel candidates are retained; validate current official response schemas. |
| BindingDB | Complementary protein–ligand measurements and publication/patent provenance where supplied | Reuse `adapters/bindingdb_activity.py` normalization where valid; current adapter reads local filtered TSV only. Add official bounded API retrieval by resolved target, or an operator-managed versioned download if API coverage/limits require it. End users should not need to download TSV manually. |
| PubChem | Compound identifiers/structures and BioAssay context or targeted follow-up | Add PUG REST identity/assay lookup with request budgets; distinguish screening activity from confirmed direct binding. Avoid exhaustive BioAssay harvesting. |
| SureChEMBL | Existing bridge from chemical identity to covered patent occurrences | Reuse the versioned package path. Link exact validated structures and explicit source patent references; label similarity-only leads separately. A patent occurrence is not proof that the compound inhibits the target or is claimed. |

Implement and review UniProt + ChEMBL end to end first, then BindingDB and PubChem for the defined roles. All are planned integrations, not verified live target coverage. Do not add a new search/database service merely to combine results.

#### C. Preserve the science in the result model

- Store target, compound, assay and measurement independently from patent membership. A candidate with literature/assay evidence but no patent mapping must remain usable and savable; do not invent a family or discard it. Document the domain/project/API extension before implementation, with forward migrations and backward compatibility for existing family saves.
- Keep small molecules as the default result focus using source molecule type plus deterministic chemistry validation. Antibodies, proteins, peptides and unclassified entities must be labeled and excluded or placed in an explicit optional group; molecular weight alone is not a reliable modality classifier.
- Classify evidence conservatively: measured direct binding; experimentally supported interaction disruption; functional/pathway effect; or computational prediction. Binding affinity alone does not establish inhibitory function. Reduced cytokine output or a downstream signaling assay is not evidence of direct ligand/receptor engagement. Preserve uncertainty when mechanism is unspecified.
- Preserve raw and standardized endpoint, value, unit and relation (`<`, `>`, `~`), assay description/format, species, target components, construct/mutation, source confidence/validity flags, DOI/PMID/patent references where supplied, and source record IDs. Keep Kd, Ki, IC50 and EC50 distinct; do not rank heterogeneous assays as a single potency list.
- Deduplicate molecular identities with RDKit while preserving salts/stereochemistry and normalization decisions. Preserve each measurement and its lineage; detect shared original references across databases so a duplicated measurement does not appear to be independent corroboration. Never average conflicting values to hide differences.
- Use the existing Results/Evidence/AI workflow with target, modality, evidence class and compatible assay filters. Show candidate structures, experimental context, source links and patent linkage status; use contextual details rather than a permanent panel per database. Save the selected candidate/evidence scope and export it with provenance.
- Every adapter needs bounded pagination/work, timeout, safe retries, rate-limit handling, cache freshness, retrieval timestamp and release/checksum where available. Distinguish no records, no qualifying small molecules, partial retrieval, source failure and not queried. Missing records do not prove that no inhibitors exist. Do not transmit private structures to public services without an explicit user-controlled operation; target-only queries can remain public-data retrieval.
- Review each source's current access, attribution and redistribution conditions before integration; update `THIRD_PARTY_NOTICES.md` in the implementation change. Public access does not imply unrestricted redistribution. Do not duplicate complete external datasets into PostgreSQL.

Acceptance: record a dated source-by-target coverage matrix for human TSLP, CD40LG, IL6 and IL6R, with receptor/partner expansion assessed separately. Record exact query IDs, pages/limits, source versions, retrieval outcome and qualifying/nonqualifying counts; this plan makes no claim about those counts. For each target retain at least one observed result or an honest empty/coverage-gap case. Use additional documented positive controls if these targets lack qualifying records, so empty responses cannot masquerade as a working adapter. Include biologic exclusion, indirect-effect classification, contradictory values, cross-source duplicates, unavailable source, missing structure, missing patent link and species mismatch. A browser user must be able to save/reopen/export a non-patent candidate and inspect its original assay evidence. Manually validate representative original records before using them in LLM evaluation.

### ONLINE-01 — useful summaries with one real endpoint

Implement within `adapters/llm.py`, `services/ai.py`, existing summary routes and the Evidence/AI inspector; do not create a second agent runtime.

- Select one explicitly configured endpoint/model for the initial compatibility target. Verify its current official protocol before changing adapter parameters; record model identifier, endpoint fingerprint, prompt/schema versions and test date. A configured status is not a successful model invocation.
- Make scope explicit: current document or current family. Add a typed document-scoped service/API path that selects only that document's facts and evidence; do not label today's family summary as a patent-only analysis. Model input contains authorized, bounded stored facts, not entire PDFs.
- Add an explicit target-investigation summary scope for ONLINE-00 results, with corpus/source coverage and evidence classes. Keep it distinct from document/family summaries and apply the same ownership/input-budget/citation rules.
- Present a concise overview, observed chemistry, evidence-supported measurements if present, evidence gaps, and separately labeled interpretation. With no claims text, say claims were not assessed; with no measurements, say none are available. Do not infer absence of activity.
- Keep citations navigable and label output `llm_inferred`. Validate cited identifiers against the supplied scope; evidence existence is necessary but does not prove the statement is entailed, so retain manual scientific evaluation.
- Show loading, unavailable configuration, timeout, provider authentication failure, 429, invalid output, and retry states. Offline summaries remain available with an explicit mode label, never disguised as successful LLM output.
- Cache by authorized data scope, input/source versions, model/endpoint and prompt version. Record available token usage and request outcome, without raw provider payloads, secrets or hidden reasoning. Tell users which data is sent and that stopping the browser wait need not cancel provider billing.

Acceptance: at least two real families plus missing-evidence and conflicting-evidence cases, one actual model call per required scope, clickable in-scope citations, no foreign-document facts in document mode, repeat request reuses the appropriate cache, and model outages leave deterministic search usable. A no-key fixture run does not close this stage.

### ONLINE-02 — LLM-assisted quick search

Extend `services/ai.py::plan_query`, typed domain/API contracts and the existing Search surface. Keep structure execution in RDKit and corpus queries in the service layer.

- Input: natural-language request, current authorized family/project context, and an allowlist of capabilities the current query services actually support.
- Output: a typed plan containing operations, explicit identifiers/filters, scope, and unresolved questions. Validate schema, operation allowlist, parameter types, row/work limits and ownership before execution. The model produces neither SQL nor arbitrary URLs/tool invocations.
- Show a compact editable interpretation in the existing search flow and an explicit Run action. For unsupported or ambiguous instructions, explain what is missing and request clarification; do not invent targets, SMILES, activity values or assay conditions.
- First supported examples: “Open patent <imported publication number>”; “Find structures similar to this selected compound” with an explicit editable threshold; “Summarize this patent/family” routed to ONLINE-01. Add “Find reported small-molecule inhibitors for human TSLP”, “Find small molecules disrupting CD40L–CD40”, and “Compare direct IL-6/IL-6R evidence with indirect effects” using ONLINE-00 typed target/source/evidence filters. Exhaustive claims such as “all potent patents” remain unsupported; unspecified potency thresholds/assay types require clarification.
- Preserve the literal patent-number fast path, manual structure search and reproducible query state. Network/model failures must not disable them. Debounce text where appropriate; explicit action triggers expensive chemistry search. Older plan/search responses cannot overwrite newer requests or selections.
- Do not send full project datasets to the model. Resolve user-selected structures and identifiers server-side after access validation. Treat source text and model output as untrusted data.

Acceptance: maintain at least 20 sealed requests, including all initial target concepts and receptor/ligand ambiguity, covering supported intents, ambiguous references, missing coverage, malformed plans, prompt injection, foreign project IDs and stale responses. Valid plans execute through the same deterministic services as manual search; every invalid/unauthorized case is refused without expanding permissions. Record actual live-model supported-intent success rate and latency; all safety/scope cases must pass before beta.

### ONLINE-03 — authenticated, private workspaces

Write a focused ADR for session/auth integration and ownership before implementation; choose an established compatible solution only after checking the current stack and license obligations.

- Start with invitation-only access and private per-user projects. Public imported patent data may be shared; user selections, notes, analysis requests/results, exports and private inputs are access-controlled. Team sharing/public signup are not initial scope.
- Add migrations for users and ownership. Migrate existing local projects via an explicit operator mapping; unassigned legacy projects are inaccessible to hosted users rather than assigned to the first login. Review schema-wide uniqueness, including today's globally unique project name, for per-owner semantics.
- Enforce authorization in service/API reads and writes, not only in UI or a login gateway. Cover project lists/details/saves, analysis retrieval and cache reuse, exports, jobs and any associated artifacts. Shared caching must not expose private inputs or outputs across owners.
- Define session expiry/logout, secure cookie/CSRF behavior where applicable, same-origin/CORS policy, invitation revocation and administrator-only operations. External users cannot choose arbitrary provider endpoints or access the operator's keys.

Acceptance: user A and B can independently use identical project names; neither can list, read, modify, export, retrieve cached analyses for, or access jobs/artifacts belonging to the other. Anonymous and revoked users fail closed. Public-source access remains explicitly distinguished from private workspace access. Test direct API calls with guessed IDs, not only hidden buttons.

### ONLINE-04 — hosting and operating the LLM workflow

Retain the modular monolith and PostgreSQL+RDKit; start with one app worker. Document HTTPS ingress, secrets, deployment/rollback and backups in a hosted runbook section distinct from the existing local runbook. No new queue, vector store or microservices without the repository's ADR/measurement requirements.

- Select host/domain and auth/model providers using current official documentation during implementation. Define actual operating budget, quota and concurrency limits before enabling paid model requests for invited users; no provider purchase or public deployment is implied by this plan.
- Keep PostgreSQL private and remove default credentials from hosted configuration. Provide HTTPS, private secret injection, a supported secret-rotation procedure and dependency/image version records. Follow dependency/source license inventory rules for new inclusions.
- Enforce authenticated per-user request/token limits and a deployment-wide bound in the service layer. Use atomic PostgreSQL accounting/reservations as appropriate for the existing architecture, bounded retries and explicit quota errors. If pricing is unknown, report token usage without inventing currency cost. Do not rely on browser controls for billing protection.
- Resolve inherited source-refresh semantics: distinguish a full version snapshot from a partial package; handle removed/invalid mappings without retaining obsolete evidence as current. Preserve saved snapshots and source/version drift notices; test retries and cross-package overlap.
- Resolve inherited import-job interruption/recovery using persisted state, bounded retry and acknowledged cancellation where implemented. Imports and source updates remain administrator operations for the first hosted beta.
- Logs contain operational identifiers, latency, usage and sanitized errors; define retention and deletion behavior for private records and backups. Add health/readiness checks and actionable model/source/DB failure reporting.
- Rehearse backup restore and supported upgrade with user ownership, project snapshots and analyses. Verify restart behavior, disconnects, expired sessions and provider outages. Do not claim multi-worker safety until tested.

Acceptance: fresh hosted staging setup is reproducible; DB has no public listener; login/logout/authorization and quotas work by API; a backup restores into a fresh isolated database with matching owned records; provider failure never looks like an empty successful analysis. Record the actual deployed image and configuration class without secrets.

### ONLINE-05 — invited online beta acceptance

A scientist using only the browser must finish: sign in → resolve a requested target → run a supported natural-language open-database query → distinguish small-molecule direct/indirect evidence → inspect structures/assays and available patent links → generate a scoped cited summary → save → sign out/in → reopen → export. Include a candidate without a patent mapping.

- Use at least two real families and a coverage-missing case. Independently cross-read selected chemical identities, stereochemistry, occurrence fields and summary claims against original sources. Label missing patent-text evidence and database-derived evidence correctly; no legal/FTO conclusions.
- Use two accounts for isolation and at least one user who did not implement the application for usability acceptance. Record defects before marking the beta usable.
- Measure startup, lookup/page/structure query latency, depiction, payload size, memory/scroll behavior and external calls; add LLM planning/summary p50/p95, failure rate, token usage and cache hit behavior. Define target latency/cost against chosen host/model in ONLINE-01/04, then use those numbers for go/no-go; historical fixture measurements are not hosted SLOs.
- Freeze tested source versions, model/prompt versions, dependency resolution and image digest. Keep an explicit coverage/capability page and rollback instructions. Production/public release remains separate from invited staging acceptance.

## 3. Deferred scope and unresolved choices

- **NEXT:** evidence-scoped follow-up questions and carefully defined within-assay SAR comparisons once target discovery and the initial summary/search loop pass. Real activity retrieval is now CORE (ONLINE-00), not deferred.
- **LATER:** full-document ingestion, broad patent discovery through additional adapters, team collaboration, self-service billing, multiple providers, Ketcher and Chrome enhancements.
- **REJECT:** autonomous Espacenet scraping, unconstrained model tools, LLM-generated chemical identity, invented scientific search parameters, full Markush/FTO claims, or a general chatbot replacing the evidence workflow.
- **Decide before dependent implementation:** host/domain, auth provider and invited cohort; permitted model endpoint/model and monthly/token budget; data privacy/retention constraints and public cases for live testing. Continue independent contract/fixture work while these are unresolved. Never ask users to put keys into planning docs or chat.

## 4. Implementation and verification record (2026-09-15)

ONLINE-00 through ONLINE-05 are **implemented** (committed in `cb21720`; this section
records what was built, what was verified and what is explicitly still open). The
acceptance gate and its invited-user script live in
[the capability statement §6](../online-capability.md#6-required-before-admitting-users);
that section, not this record, is what a deployment is checked against.

### 4.1 Stage status

| Stage | Status | Evidence |
| --- | --- | --- |
| ONLINE-00 target-led discovery | implemented, live-verified | `benchmarks/online00-coverage-2026-09-15.{md,json}` — dated source×target matrix with query ids, counts, outcomes and versions; EGFR positive control |
| ONLINE-01 scoped summaries | implemented; live smoke recorded, citation evaluation open | family/document/target scopes with separate prompt versions and cache keys; recorded-response contract tests (`tests/test_online01_scoped_summaries.py`); live DeepSeek `deepseek-flash` calls per scope plus the browser AI panel, with cache reuse, token accounting and one bounded content re-sample — `docs/archive/2026-09-15-llm-live-smoke.md` |
| ONLINE-02 validated plans | implemented | 28-request sealed set (`data/fixtures/planner_requests.json`) incl. injection, foreign ids, ambiguity; `tests/test_online02_plan.py` |
| ONLINE-03 access and ownership | implemented | ADR-0002; 19 isolation tests calling the API directly with guessed ids |
| ONLINE-04 hosting operations | partially implemented | quota accounting, readiness, hosted runbook; **deployment/restore-against-host outstanding** |
| ONLINE-05 invited beta | harness ready, **acceptance not run** | evaluation invariants (`tests/test_online05_evaluation.py`), acceptance script, capability page |

### 4.2 What was built

- **Sources** (`adapters/`): `uniprot.py`, `chembl_discovery.py`, `bindingdb_rest.py`,
  `pubchem.py`, sharing a bounded `http.py` client (timeout, throttle, safe
  bounded retries, response cache, honest failure). Every source failure is
  recorded as `failed`, never as an empty result.
- **Chemistry**: `chemistry/modality.py` (deterministic modality classification
  with the deciding rule recorded) and `clean_external_smiles` (CXSMILES hygiene).
- **Result model** (migrations 0009–0012): target scope with resolution
  provenance, evidence classes and assay context per measurement, explicit
  candidates independent of patent membership, per-source retrieval records,
  scoped summaries, owner columns, and model-usage accounting.
- **Services**: `targets.py`, `discovery.py`, `planner.py`, `plan_execution.py`,
  `usage.py`, `auth.py`, plus scope-aware `ai.py` and owner-aware `projects.py`.
- **API**: target resolve/discover/candidates/measurements/coverage, document and
  target summaries, typed plan + execute, invitation sessions, usage, readiness.
- **UI**: target investigation surface (coverage strip, candidate table with
  modality/evidence/patent-linkage columns, assay evidence panel), plan
  interpretation card with editable parameters and an explicit Run, shared AI
  panel with scope selection, and a hosted sign-in gate.

### 4.3 Verified in this turn

- Backend suite: **397 passed** against a live PostgreSQL+RDKit database.
- Frontend: `tsc --noEmit` and production `vite build` clean.
- Browser: target investigation end to end (live retrieval → evidence → save →
  reopen), plan card → Run → investigation, and hosted mode (401 anonymous,
  invitation redemption, signed-in save through CSRF, sign-out returns to gate).
- Restore drill with ownership, including two operational findings now in
  runbook §H7 (see below).
- Performance baseline: `benchmarks/online-baseline-2026-09-15.md`.

### 4.4 Defects found and fixed in this turn

Six defects, listed with how each was found, are in the acceptance record §2.
Two are worth naming here because they show where the checks earned their keep:
the reviewed scope catalog did not ship in the packaged image (found only by
testing the built artifact, not the source checkout), and externally discovered
compounds were stored with `has_stereo = false` regardless of structure (found by
the scientific evaluation re-deriving the flag from the stored SMILES).

### 4.5 Still open before hosted users are admitted

1. One real model provider configured, with a live call per scope recorded
   (model id, endpoint fingerprint, prompt/schema versions, token usage, latency,
   failure rate, cache behaviour). ONLINE-01 acceptance depends on this.
   **Live smoke recorded 2026-09-15**: DeepSeek `deepseek-flash`, one live call per
   scope through the API plus the browser AI panel, cache reuse confirmed — see
   [the live-smoke record](../archive/2026-09-15-llm-live-smoke.md). **Repeatable baseline
   recorded 2026-09-15**: `scripts/llm_summary_eval.py`, 45 requests / 53 calls
   over four runs through the shipped input builder and retry policy, per-call
   compliance and refusal classes, at
   `benchmarks/online01-llm-eval-2026-09-15.md`. The baseline found an
   input/instruction contradiction (aggregate facts with no citable ref); the
   citation rule was corrected, the per-source refs were added, and both changes
   were re-measured in the same record (run 4: 18/18 requests answered, the target
   scope citing its three `source:` refs, chip checked in the browser —
   [record §7.1](../archive/2026-09-15-llm-eval-and-demo-open.md)). What the baseline still does
   not cover is recorded in its own "what these numbers do and do not prove"
   section. Hosted-provider choice and budget remain open.
2. Host, TLS ingress, secret injection, and quota limits set to real values.
3. A restore rehearsed against the actual host.
4. Scientific evaluation of live summaries for entailment (a valid citation does
   not prove the statement follows from it).
5. Independent cross-reading of retrieved chemistry against original sources by a
   second person.
6. Usability acceptance with a scientist who did not build the application.
7. Performance/cost targets defined for the chosen host and model, then measured.

### 4.6 Source and job defects carried into ONLINE-04

- BindingDB's REST path supplies no assay description, species or construct; those
  context fields are empty for BindingDB records.
- PubChem contributes screening context only (bounded AID lists), not measurements.
- CRLF2/TSLPR has no ChEMBL target record, so the TSLP receptor side cannot be
  queried for activity through that path.
- Source refresh/retraction semantics and import-job interruption/recovery from
  the previous milestone remain unresolved for hosted operation.

### Open-source references checked for this planning update

Official documentation was inspected for available interfaces; no target-specific activity count or live adapter behavior was verified. Local ChEMBL/BindingDB adapter code was read; existing planning edits were preserved. This is a scope update, not an implementation or inhibitor assessment.

- [ChEMBL Data Web Services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services): target, molecule and activity resources.
- [BindingDB Web Services](https://www.bindingdb.org/rwd/bind/BindingDBRESTfulAPI.jsp): programmatic target/ligand access; [BindingDB 2024 database paper](https://www.bindingdb.org/rwd/bind/gkae1075.pdf) documents dated downloads and REST services.
- [PubChem PUG REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest) and [tutorial](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest-tutorial): compound and target-centric assay access.
- [UniProt API queries](https://www.uniprot.org/help/api_queries); [human CRLF2](https://www.uniprot.org/uniprotkb/Q9HC73/entry) records CRLF2/IL7R receptor membership; [human IL6R](https://www.uniprot.org/uniprot/p08887) distinguishes IL6, IL6R and IL6ST components; [NCBI human CD40LG](https://www.ncbi.nlm.nih.gov/gene/959) identifies the CD40 ligand gene.
