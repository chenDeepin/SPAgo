# SPAgo backlog register

Status: **living register — proposals only.** Nothing listed here is approved scope,
implemented capability or a commitment to build. What this build *does* is stated in
`docs/online-capability.md`; what it *might* do next is stated here. Classification
follows `AGENTS.md` §37 (`CORE` / `NEXT` / `LATER` / `REJECT`). An item marked
**gate** needs an operator decision (host, provider, credential, source choice or user
base) before engineering can finish it, not before engineering can start.

Last updated: **2026-09-16 (B-24 delivered; B-03 promoted to P1)** — the priority table was
re-sorted when B-24 landed: B-03 is the new P1, B-26 moved ahead of B-23, and nothing else
changed. See the update log at the end of this file and §4 for the one-sentence arguments.

## 0. Standing constraints for everything below

- The operator gate in `docs/online-capability.md` §6 comes first. Nothing in this
  register displaces it, and no item here may be presented as closing a §6 checkbox.
- `AGENTS.md` §5 (no Espacenet automation), §6/§33 (no new infrastructure service
  without an ADR and measured need), §23 (dependency + `THIRD_PARTY_NOTICES.md` in the
  same change) apply to every item.
- Effort sizes are rough — `S` ≤ 1 day, `M` ≈ 2–5 days, `L` ≈ 1–3 weeks of focused
  work. They are not calendar promises, and a `LATER` item is not queued.
- Owner-requested on 2026-09-16: the target-led open-database group and the summary
  archive (B-06, B-07, B-08, B-10), and — after the `BindingDB_IO` review — the
  snapshot/patent-led/supplement group (B-23…B-26). Their priority is still argued from
  the product, not from the request; §3 records that argument.

## 1. Priority order

| Priority | ID | Item | Class | Effort | Gate / blocker |
| --- | --- | --- | --- | --- | --- |
| P1 | B-03 | Tolerant publication-number lookup | NEXT | S | — |
| P2 | B-25 | Literature supplement bundle import (agent-produced rows) | NEXT | M | — |
| P2 | B-26 | Patent coverage audit (corpus / snapshot / ChEMBL / supplement / absent) | NEXT | M | — |
| P2 | B-23 | Local BindingDB snapshot search (operator dataset, TSV first) | NEXT | M (TSV) | snapshot terms + §25 versioning |
| P2 | B-06 | Per-source re-run for target investigations *(owner request group)* | NEXT | S–M | — |
| P2 | B-15 | Compress served assets (Ketcher first open) | NEXT | S–M | deployment proxy or image config |
| P2 | B-04 | Import refresh completeness and interrupted-import resume | NEXT | M | — |
| P2 | B-14 | CI running the existing check script | NEXT | S | repo hosting decision |
| P2 | B-09 | Reviewed target-scope catalog expansion | NEXT | M | scientific review |
| P2 | B-11 | Second model-provider evaluation and refusal UX | NEXT | M | provider choice (operator) |
| P2 | B-21 | Claim-text source decision and ingestion plan | LATER | L | source choice + ADR |
| P2 | B-22 | EPO OPS adapter (bibliographic / family / full-text enrichment) | LATER | L | OPS credentials + ADR |
| P2 | B-17 | Frontend test harness and one end-to-end smoke | NEXT | M | dependency + notices |
| P2 | B-18 | Chrome companion: cover the toolbar click and side-panel surface | NEXT | S | unbranded Chromium |
| P3 | B-05 | Bulk analytical filtering surface (DuckDB/Parquet) | LATER | L | ADR + dataset |
| P3 | B-07 | PubChem BioAssay bounded CID→AID path *(owner request group)* | LATER | M–L | bounded design |
| P3 | B-08 | BindingDB assay-context enrichment *(owner request group)* | LATER | M | source capability check |
| P3 | B-27 | Structure review sheet (fixed-scale cards, scaffold folding, lossless PDF) | LATER | L | user workflow ask |
| P3 | B-16 | Operator usage visibility (decide: docs-only or small admin view) | LATER | S | — |
| P3 | B-19 | Accessibility pass on the virtualized table and dialogs | LATER | M | — |
| P3 | B-20 | Chinese UI / i18n | LATER | L | user-base decision |
| P3 | B-29 | A stored analysis as a project artifact | LATER | M | user workflow ask |
| P3 | B-12 | Multi-worker deployment (shared in-flight model registry) | LATER | M | scaling need |
| — | — | *(rejected / deliberately out — see §5)* | REJECT | — | — |

P1 = worth doing before or alongside the invited beta because it strengthens the same
workflow the gate tests. P2 = the next implementation round candidates, in the order
shown. P3 = deliberately later; a P3 item needs a decision or a measured need before it
becomes P2.

**Delivered from this register (kept out of the table, with the artifact that closed
it):**

| ID | Delivered | Artifact |
| --- | --- | --- |
| B-01 | 2026-09-16 | `scripts/corpus_batch.py` (chunked extract → import with resumable `STATE.json`, per-chunk status, non-zero exit and an explicit missing-number list when the corpus does not hold the requested set); `spago_core.corpus_status` (terminal surface; `--patents` exits non-zero and prints every number that is not loaded) and `GET /api/v1/corpus` behind the top-bar dataset badge (`CorpusDialog.tsx`) — counts read from the corpus tables, per dataset version, with failed/interrupted imports and unregistered versions reported. |
| B-10 | 2026-09-16 | Read path over `ai_analyses`: `GET /api/v1/analyses` (owner-scoped list with scope label, model, prompt/policy version, tokens, staleness reasons), `GET /api/v1/analyses/{id}` (stored text + citations + the exact input-fingerprint check), `GET /api/v1/analyses/{id}/export` (Markdown whose header states scope, provider, model, prompt, policy, data version and citations), and the top-bar **Analyses** dialog (`AnalysesDialog.tsx`) that reopens them without a provider call. |
| B-02 | 2026-09-16 | A disjoint per-retrieval tally of how each kept record's document reference resolved (`source_retrievals.reference_counts`, migration 0016; vocabulary in `spago_core/domain/document_refs.py`), served by `GET /targets/{id}/coverage` and rendered in the target header's **Source notes and reference coverage** disclosure together with the source notes that were previously stored and never shown; `scripts/cohort_coverage.py --declarations` measures it live and read-only, recorded in `benchmarks/reference-declarations-2026-09-16.{md,json}` (135 of IL6's 166 kept records carry a source-declared patent — the live linkage the handoff could not previously point at). |
| B-13 | 2026-09-16 | `scripts/restore_check.sh` (dumps, restores, compares the §H7 counts, fails non-zero on mismatch, verified against the rehearsal stack and against a deliberate mismatch) and the §H2 ingress-duty table (compression, TLS, throttling, logs, backup schedule) in `docs/runbook.md`. |
| B-24 | 2026-09-16 | The patent-led read path: `ChEMBLDiscoveryAdapter.declared_compounds` (body-search rule `chembl-document-patent-body-v1`, exact-normalization verification, near matches listed and excluded), `services/patent_sources.py` + migration 0017 (`patent_source_lookups` / `patent_source_compounds`, no `compound_mentions` row ever written), `POST`/`GET /api/v1/patents/{number}/source-compounds` and `/export?format=csv|sdf`, `SourceDeclaredCompounds.tsx` (under the patent view and on a publication the corpus does not hold, where the 404 used to be a dead end), and `scripts/patent_source_lookup.py`; live record `benchmarks/patent-source-declarations-2026-09-16.{md,json}` (US10508115 → 134 declared records for 73 compounds out of 402 seen, 5 states kept apart). |

## 2. Items

### B-01 — Corpus scale-up workflow (batch extract/import, loaded-corpus surface)

**Delivered 2026-09-16** (`docs/plans/backlog.md` §1 artifact table). The problem and
scope below are kept as the record of what was asked; the shipped shape differs in two
places worth naming: the batch loop runs on the operator's host rather than inside the
service (no new worker, §6/§22), and the "what is loaded" surface reads counts from the
corpus tables on every request instead of maintaining a counter.

- **Problem.** "Search real patents" today means "search what an operator imported".
  `scripts/extract_surechembl.py` takes one publication per run and
  `python -m spago_core.import_package <dir>` one package per run (README "Loading real
  patent data"; runbook §2). Growing a useful corpus is a manual, unbounded chore, and
  the UI only shows a dataset badge in the top bar (`TopBar.tsx`).
- **Scope if built.** An operator workflow for many families: a family list in, a
  queued/bounded extraction and import out, per-item status (reusing `import_jobs`),
  and a read-only "loaded corpus" surface (families/documents/compounds/versions per
  source) so a scientist can see what a search actually covers. No Espacenet path
  (§5); SureChEMBL bulk stays the source.
- **Acceptance sketch.** Import N families in one run with per-family status; a
  not-imported publication still returns the explicit not-found; the corpus surface
  reports counts that match the database.
- **Class NEXT · P1 · M.** Depends on B-04 at large N.

### B-02 — Live source-declared patent linkage and candidate→corpus match

**Delivered 2026-09-16** (`docs/plans/2026-09-16-source-declared-linkage.md`). The three
gaps it closed: nothing counted what happened to a record's document reference; the
retrieval's own warnings were stored and served but rendered nowhere in the UI; and the
live declaration coverage had never been measured on the acceptance cohort. The display
and export halves already kept `patent_numbers` and `source_declared_patents` apart — they
are now verified on live data rather than assumed.

- **Problem.** The headline "patent linkage" claim is only half proven live. The
  ChEMBL document lookup is implemented and bounded (`adapters/chembl_discovery.py`,
  `DOCUMENT_PATH`, `MAX_DOCUMENT_LOOKUPS`, `_attach_document_references`), but the
  handoff states **no live row carries a source-declared patent number yet** and that
  rendering path is fixture-tested only. Corpus matching exists as a count
  (`services/discovery.py`, `patent_occurrences`).
- **Scope if built.** Measure live declaration coverage honestly (how many
  measurements actually get a patent/DOI/PMID, and why the rest do not — missing
  document, field absent, lookup bound reached); show the candidate's source-declared
  patent next to its corpus occurrence with both labelled; export keeps the
  distinction. A bound being reached is reported, never silently dropped.
- **Acceptance sketch.** A recorded live run on the acceptance cohort with per-source
  declaration counts, plus a browser check that a declared patent and a corpus
  occurrence never appear as one column.
- **Class NEXT · P1 · M.**

### B-03 — Tolerant publication-number lookup

- **Problem.** Lookup is exact string equality: `services/core.py::find_patent` matches
  `publication_number = :pn`, and `GET /patents/{publication_number}` passes the raw
  path segment. `domain/patent_numbers.py` has normalization (`normalize_patent_number`,
  `patent_number_match`) but it is used for source-declared numbers, not for the search
  box. A scientist typing `WO2020123456A1` or `wo 2020/123456` for a stored
  `WO-2020-123456-A` gets a not-found.
- **Scope if built.** Normalize on lookup, match against the stored corpus, and say
  which stored identifier was matched (never rewrite the stored value). Ambiguity is
  reported, not guessed.
- **Acceptance sketch.** Unit cases for separator/case/kind-code variants; a
  not-found stays not-found for a genuine miss.
- **Class NEXT · P2 · S.**

### B-04 — Import refresh completeness and interrupted-import resume

- **Problem.** README still states: source refresh does not yet retract deleted or
  invalid *mappings*, and an interrupted import job has no recovery protocol. D4
  retracts `compound_mentions` + `evidence_records` only (`seed.py`); compounds and
  measurements dropped by a release are not covered. D5 marks a dead job
  `interrupted` (`import_package.py`) but a re-run redoes the whole package.
- **Scope if built.** Extend retraction to the remaining mapping kinds with the same
  never-delete semantics and a recorded reason; define a resume/retry policy for large
  packages (bounded, idempotent, no duplicate records) and state it in the runbook.
- **Acceptance sketch.** A release that drops a measurement/compound retracts it and
  reports the count; an interrupted large import resumes or fails cleanly without
  duplicating rows.
- **Class NEXT · P2 · M.**

### B-05 — Bulk analytical filtering surface (DuckDB/Parquet)

- **Problem.** `queries/bulk.py` reads a fixture directory only and the single exposed
  endpoint is `/bulk/compound-counts`. PROMPT §11 A (date/assignee/CPC filtering over
  SureChEMBL Parquet) has no user surface.
- **Gate.** A dataset release, a schema version and an ADR (§6/§33); AGENTS §7 keeps
  bulk analysis in DuckDB rather than the transactional database.
- **Class LATER · P3 · L.**

### B-06 — Per-source re-run for target investigations *(owner request group)*

- **Problem.** The base path is implemented and recorded (ONLINE-00/06/07), but
  recovery from a single bad source is all-or-nothing. `DiscoverRequest.sources`
  accepts a subset, yet the UI always sends all three (`App.tsx`) and the control is
  "Refresh sources" / "Query open sources" (`TargetHeader.tsx`). A `failed` or stale
  BindingDB leaves no way to retry just that source without re-spending the others.
- **Scope if built.** Re-run a named source for a stored investigation, honouring the
  existing per-source status machine (`complete` / `partial` / `empty` / `failed` /
  `not_queried`) and the retraction rules from migration 0015; show what the retry
  costs (upstream requests, wall time) before it runs.
- **Acceptance sketch.** A target with one failed source retries only that source; the
  other summaries/verdicts do not change; the retry is visible in `source_retrievals`.
- **Class NEXT · P2 · S–M.**

### B-07 — PubChem BioAssay bounded CID→AID path *(owner request group)*

- **Problem.** Capability §8: PubChem contributes screening context only; a CID→AID
  measurement path is not implemented because it "would require unbounded BioAssay
  harvesting".
- **Scope if built (bounded by design first).** A single explicit user action on a
  named CID, a hard cap on requests/records, per-record provenance and an honest
  partial status. If the bound cannot be made honest, the item stays closed.
- **Class LATER · P3 · M–L.**

### B-08 — BindingDB assay-context enrichment *(owner request group)*

- **Problem.** Capability §8: the REST path supplies no assay description, species or
  variant context, so those fields are empty for BindingDB records.
- **Scope if built.** Check whether another documented BindingDB path or a different
  field set supplies the context; if yes, map it through the adapter and say where it
  came from. If no, record the negative result and close the item.
- **Class LATER · P3 · M.**

### B-09 — Reviewed target-scope catalog expansion

- **Problem.** `services/core/spago_core/data/target_scopes.json` (reviewed 2026-09-15)
  covers the acceptance systems. Other targets resolve by UniProt identity but carry
  no reviewed ligand/receptor/pathway mapping, which is the honest-scope mechanism.
- **Scope if built.** Add reviewed systems one at a time (identity, members, related
  vs. merged, disclaimer), each with a recorded review note — never keyword rules
  (AGENTS §12).
- **Acceptance sketch.** New entries change only the targets the user investigates;
  the coverage matrix shows related systems labelled as related.
- **Class NEXT · P2 · M (review-heavy).**

### B-10 — Summary archive and retrieval *(owner request)*

**Delivered 2026-09-16** (`docs/plans/2026-09-16-analysis-history.md`). The shipped
shape keeps the stated scope and adds one thing the problem statement implied but did
not name: an *exact* staleness answer, not just a version comparison. Opening a stored
analysis recomputes its input fingerprint with the same function the write path uses,
so "would this request be a cache hit now?" is answered by computation instead of by
assumption.

- **Problem.** The data exists but is write-only from the product's point of view.
  Successful scoped summaries are stored in `ai_analyses` with `input_hash`, scope
  kind, `prompt_version`, `input_snapshot`, citations, usage and owner
  (`services/ai.py`), and are reachable only by re-issuing the same POST and hitting
  the content-keyed cache. There is no list, no open-by-id, no export, no attachment to
  a project (`api/routes.py` exposes only the three POST summary routes). A scientist
  who generated a good target analysis cannot find it again except by re-running the
  same view.
- **Scope if built.** A read API and a bounded history surface (per owner): list stored
  analyses with scope, model/prompt version, timestamp, provenance state; open one and
  render it with its citations; label a cache hit `cached`; export the text (Markdown
  or plain) with its scope/version/policy header; optionally attach a summary to a
  project. Staleness stays visible — an analysis whose snapshot version no longer
  matches the current data says so instead of being silently served as current.
- **Acceptance sketch.** Generate a target summary, sign out/in, reopen it from history
  without a provider call; the exported file states scope, prompt version, provider,
  model and citations; a changed threshold/dataset marks the old entry stale.
- **Class NEXT · P1 · M.**

### B-11 — Second model-provider evaluation and refusal UX

- **Problem.** Capability §8: quality/latency/token usage/failure rate are measured for
  **one** provider (DeepSeek `deepseek-flash`); any other endpoint the operator chooses
  is unverified, and an answer rejected twice in a row (one re-sample allowed) still
  fails as 502.
- **Gate.** The operator picks the provider and budget; the evaluation then records
  model id, endpoint fingerprint, per-scope calls, tokens, latency, failures and cache
  behaviour (`benchmarks/online01-llm-eval-2026-09-15.md` is the method).
- **Scope if built.** Run the same evaluation against a second provider; surface the
  refusal class and the remaining retry budget in the UI instead of a bare 502.
- **Class NEXT · P2 · M (gate: provider).**

### B-12 — Multi-worker deployment (shared in-flight model registry)

- **Problem.** Capability §8: multi-worker deployments are unsupported because the
  in-flight model-call registry is per process (`services/ai.py`, `_INFLIGHT`).
- **Gate.** A measured scaling need; then a database-backed registry (or an equivalent
  documented decision) — requires an ADR and a concurrency test.
- **Class LATER · P3 · M.**

### B-13 — Gate support kit: restore rehearsal and deployment configuration examples

**Delivered 2026-09-16** — `scripts/restore_check.sh` plus the §H2 ingress-duty table.
Kept below as the original statement of the problem; the priority table no longer lists
it.

- **Problem.** The §6 checklist is hand-run from prose: TLS/secret injection, the
  restore rehearsal (§H7), and readiness verification. One checklist entry ("backup
  taken and a restore verified, ownership counts match") is script-shaped, and every
  operator re-invents the deployment wiring.
- **Scope if built.** (a) A rehearsal script that performs the §H7 dump/restore into a
  scratch database and compares the documented counts, exiting non-zero on mismatch;
  (b) a documented, minimal configuration example for hosted mode (env/secret
  checklist, proxy/compression note) — documentation first, and if a proxy container
  enters the repo it gets a short ADR per §33.
- **Acceptance sketch.** On a scratch stack, the script reseeds a dump and reports the
  same ownership counts; a deliberate mismatch fails the check.
- **Class NEXT · P1 · S–M (gate: host chosen).**

### B-14 — CI running the existing check script

- **Problem.** There is no `.github/` (or equivalent) in the checkout; every recorded
  round ran `scripts/run_checks.sh` by hand, and the frontend/build regression is
  detectable only by a person remembering to run it.
- **Scope if built.** A minimal pipeline that runs the existing script without
  duplicating its logic; database-dependent tests keep their scratch-database
  behaviour. Hosting decision (where CI runs) is the operator's.
- **Class NEXT · P2 · S.**

### B-15 — Compress served assets (Ketcher first open)

- **Problem.** Measured and recorded (capability §5; `benchmarks/online08-structure-editor-2026-09-16.md`):
  the shipped container serves assets uncompressed, so a first editor open transfers
  ~20.3 MB raw instead of ~4.95 MB gzip. Entry bundle is unaffected (320 KB raw /
  93 KB gzip).
- **Scope if built.** Enable compression at the image or proxy layer, then re-measure
  bytes and time-to-usable-editor with the same method; record the delta.
- **Class NEXT · P2 · S–M.**

### B-16 — Operator usage visibility

- **Problem.** `/api/v1/usage` and `/api/v1/usage/events` exist (runbook §H6) but the
  operator reads them with curl.
- **Decision needed first.** Is a small admin-only view worth a UI surface (§17
  progressive disclosure), or is the API plus the runbook enough for one beta? If the
  answer is "API is enough", close the item as REJECT with that note.
- **Class LATER · P3 · S.**

### B-17 — Frontend test harness and one end-to-end smoke

- **Problem.** `apps/web/package.json` has no test script and no test dependency;
  AGENTS §27 requires frontend interaction and end-to-end categories, and §36 requires
  browser evidence for UI claims. Today that evidence is produced manually per round.
- **Scope if built.** One runner and one smoke path (search → family → compound →
  structure filter → export) against a seeded stack; dependency choice follows §23 and
  updates `THIRD_PARTY_NOTICES.md` in the same change. Do not duplicate the Python
  suite's coverage.
- **Class NEXT · P2 · M (dependency decision).**

### B-18 — Chrome companion: cover the toolbar click and side-panel surface

- **Problem.** `apps/chrome-extension/verify-in-chrome.js` verifies load, detection,
  handoff and side-panel render; the headed toolbar click and the side-panel surface
  itself are explicitly not covered (PROMPT §14 M4).
- **Scope if built.** Extend the verification to the toolbar action in an unbranded
  Chromium / Chrome for Testing build, or record the residual limit again with the
  reason.
- **Class NEXT · P2 · S.**

### B-19 — Accessibility pass on the virtualized table and dialogs

- **Problem.** No accessibility record exists; the product leans on a virtualized table
  (`@tanstack/react-virtual`), dialogs, and keyboard-driven search.
- **Scope if built.** Keyboard traversal, focus management in dialogs, table semantics
  and screen-reader labels for the structure/depiction controls; scoped to the existing
  layout (§18), with a written check list.
- **Class LATER · P3 · M.**

### B-20 — Chinese UI / i18n

- **Problem.** The interface is English-only; there is no i18n layer in `apps/web`.
- **Gate.** Who the invited cohort is. If beta users read English, this is premature
  (YAGNI); if not, it becomes a P2 feature with its own decision about scope (UI
  strings only vs. exports and summaries too).
- **Class LATER · P3 · L (gate: user base).**

### B-21 — Claim-text source decision and ingestion plan

- **Problem.** Claims are a product pillar (PROMPT §2.1) but no claim text is stored:
  `services/ai.py` states "Claim text is not stored in this deployment", capability §5
  says claims text is not in the pipeline, and summaries say "claims were not
  assessed". This is the largest remaining gap between the product story and the
  shipped workflow — and it is *not* OCSR.
- **Gate.** A source decision and an ADR: EPO OPS full text (B-22) versus fields in the
  SureChEMBL bulk path versus another licensed source; plus storage and evidence
  mapping (claim number, paragraph, jurisdiction, language).
- **Scope if built.** Claim text imported per document with typed evidence records, so
  a document/target summary can cite a claim instead of declaring it unassessed.
- **Class LATER · P2 · L (decision first).**

### B-22 — EPO OPS adapter (bibliographic / family / full-text enrichment)

- **Problem.** PROMPT §6/§11 lists EPO OPS as an initial source, but this checkout has
  no `adapters/ops.py`; family/bibliographic enrichment beyond what was imported does
  not exist.
- **Gate.** OPS registration and credentials (operator), EPO quota/rate-limit handling
  (§16), and an ADR; pairs with B-21.
- **Scope if built.** A bounded, cached OPS adapter for family and bibliographic
  enrichment with source name, version, retrieval timestamp and error/rate-limit state,
  surfaced through the existing evidence/provenance rules.
- **Class LATER · P2 · L (gate: credentials + ADR).**

### B-23 — Local BindingDB snapshot search (operator dataset, TSV first)

- **Problem.** SPAgo's only BindingDB path is the bounded REST adapter
  (`adapters/bindingdb_rest.py`): what the endpoint returns within its caps *is* the
  set, and a rate-limited or partial answer cannot be checked against anything. The
  research workflow this product is meant to serve already keeps the full local
  snapshots (`/media/chen/Machine_Disk/Datasets/`: `BindingDB_All_2609.tsv`, 8.9 GB;
  `bindingdb_processed.lmdb`, 21 GB) and searches them directly. Reference
  implementation, read in full: `readers/tsv.py`, `readers/lmdb.py`,
  `readers/multi.py` (single pass, several queries at once, `Target Name` alias
  matching plus optional UniProt columns, progress every 500k rows) and
  `patents.py::search_tsv_by_patents` / `search_lmdb_by_patents` (the same dump
  queried by publication number).
- **Scope if built (first step, TSV only).** An adapter that streams a
  operator-supplied TSV (stdlib, no new dependency), takes target aliases or
  publication numbers, normalizes rows into the existing measurement/candidate
  pipeline and records the snapshot release, row count, file checksum and search
  parameters. It runs as a bounded batch job (AGENTS §21: never inside an interactive
  HTTP request) and reports what it scanned, so a zero result can be distinguished
  from a partial scan. LMDB is deliberately deferred: it is the older dump, it stores
  pickles and computed features RDKit already reproduces, and reading it would add a
  dependency for no unique field except the historical backfill.
- **Non-negotiables.** A snapshot hit is `DATABASE_CURATED` with the snapshot's own
  source name/version — never a corpus occurrence and never a source-declared patent
  (AGENTS §10/§11); version + checksum recorded (§25); the file never enters the repo
  (§34); the data's terms of use are recorded in `THIRD_PARTY_NOTICES.md` (BindingDB
  data terms are not the software license).
- **Acceptance sketch.** On a machine holding the dump: a query for an acceptance
  target resolves with zero upstream API calls and reports rows + scan time; the rows
  are reconcilable against the REST result, and any difference is explainable in the
  report; the recorded release + checksum travel with the run.
- **Honest limit.** Local-only value: a hosted deployment would need the dump on the
  host (tens of GB), so this is operator tooling for a workstation, not a feature of
  the invited beta.
- **Class NEXT · P2 · M (TSV); L if LMDB is ever justified by a measured need.**

### B-24 — Patent-led compound discovery via ChEMBL patent search

**Delivered 2026-09-16** (`docs/plans/2026-09-16-patent-source-compounds.md`). The problem
and the honesty requirements below are kept as the record of what was asked. Two scope
notes from building it: the declared set is a separate storage shape (its own tables; a
lookup writes no `compound_mentions` row and cannot move a family's compound count), and
the browser check found a defect the unit tests could not — the panel compared the
answer's *canonical* number with the number as typed, discarding a successful lookup.

- **Problem.** The patent view shows compounds only from the imported corpus. A family
  that was not imported (or is thin) has an empty compound table even when the
  compound set is publicly indexed, and the product's first promise — enter a patent,
  see its compounds — silently degrades to "enter a patent SPAgo happens to hold".
  ChEMBL indexes compounds by the patent document that reports them, and
  `BindingDB_IO` implements the reverse path SPAgo lacks: `readers/api.py::search_chembl_patent_api`
  resolves `document` by `patent_id__icontains` on the normalized numeric body,
  verifies the match with the same normalizer the local audit uses, then pulls
  `activity` by `document_chembl_id__in` with `standard_type__in=Ki,IC50,Kd,EC50`,
  `standard_units__iexact=nM`, `standard_flag=1`, projected with `only=` (the same
  projection SPAgo measured as a bandwidth saver with no latency gain,
  `benchmarks/online00-chembl-projection-2026-09-16.md`), and returns SMILES,
  preferred name, assay, target, organism plus the document's DOI/PMID/patent.
- **Scope if built.** A bounded patent-led adapter/service reusing the existing ChEMBL
  adapter rules (timeout, retry, cache, error and rate-limit state), exposed on the
  family/document view as **source-declared compounds**, kept in separate fields,
  columns and labels from corpus occurrences (AGENTS §11), with the match rule stated
  ("documents that declare this publication body") and non-matching candidates
  excluded and counted rather than dropped silently.
- **Honesty requirements.** Jurisdiction and kind-code variance means a body match can
  include a sibling publication; the count of body-only matches is reported. A
  declared compound is not evidence that the compound occurs in the patent's corpus
  record, and the potency class of its measurements is computed on read under the
  stated policy — no ranking is implied.
- **Acceptance sketch.** A publication with a known ChEMBL patent record returns
  compounds with assay/target/document references; a deliberately wrong number returns
  empty *with the rule stated*; the UI never merges the declared set into the corpus
  count; the export carries the source and the match rule.
- **Class NEXT · P2 (delivered 2026-09-16) · M.**

### B-25 — Literature supplement bundle import (agent-produced rows)

- **Problem.** SPAgo accepts one hand-added row per POST
  (`services/supplements.py`, `POST /targets/{id}/supplements`, `SupplementDialog.tsx`),
  which is the right contract for a single claim but the wrong shape for the workflow
  that actually produces these rows: an agent (or a scientist) searches the literature
  and returns a set. `BindingDB_IO` handles the set: `web_supplement.py`
  (`load_web_supplement_file`, `load_supplement_bundle`, `normalize_web_records`,
  `examples/web_supplement.example.json`) accepts a JSON list or a per-output bundle,
  requires a `note` for every row, auto-prefixes one that is missing, keeps
  structure-less rows as remarks, carries DOI/PMID/URL, and the CLI only applies the
  supplement when the merged result is empty or fails the gate
  (`--web-only-if-empty`, `--web-if-no-active`).
- **Scope if built.** (a) A documented bundle schema + import endpoint that runs each
  row through the existing ONLINE-07 validation (mandatory note, RDKit normalization,
  modality classification, InChIKey identity, class computed on read, structure-less
  row → remark, re-post = update, withdrawal semantics unchanged) and returns a
  per-row outcome (accepted / refused with reason); (b) a visible trigger state — "no
  compound at or below the threshold was retrieved; literature rows may be added" —
  so the supplement is prompted at the moment the gate fails rather than remembered;
  (c) an import report stored with the run.
- **Provenance.** The import records who asserted each row and what it cites. An
  agent-produced bundle that a human has not reviewed is not `user_curated` (AGENTS
  §12); confirming it is a separate, recorded action. Where the source project
  auto-prefixes a missing note, SPAgo keeps its stricter ONLINE-07 rule: a row without
  a note is refused, not given a generated one.
- **Acceptance sketch.** A bundle of N rows imports with per-row outcomes; a row
  without a note is refused with its reason; a structure-less row becomes a remark
  that is never drawn, exported or counted as a compound; re-importing the same bundle
  does not duplicate rows.
- **Class NEXT · P2 · M.**

### B-26 — Patent coverage audit

- **Problem.** Nobody can currently answer "which publications in this family have
  compounds, from where, and which are uncovered?" `BindingDB_IO` answers exactly this
  per patent: `cli/audit_patent_coverage.py` reports a status — `bindingdb` (dump
  hits), `chembl` (structured activities), `structured_supplement`, `chembl_document_only`,
  `absent` — with per-source counts and samples, plus a summary block. SPAgo has the
  ingredients (`source_declared_patents`, `patent_occurrences`, `source_retrievals`,
  `target_supplement_remarks`) but no audit view or report.
- **Scope if built.** A per-publication coverage report for a family/document (and for
  an operator-supplied manifest): corpus occurrence counts, snapshot hits (if B-23
  exists), ChEMBL documents/compounds (if B-24 exists), hand-added rows, and an
  explicit `not_queried` distinct from `absent`; export JSON/Markdown for the operator
  and a compact strip in the patent view. Every status is reproducible from stored
  rows.
- **Acceptance sketch.** A family with mixed coverage yields a table whose every
  status can be re-derived from the database; a publication never checked reads
  `not_queried`, never `absent`.
- **Class NEXT · P2 · M (depends on B-23/B-24 for content, not for the shape).**

### B-27 — Structure review sheet (fixed-scale cards, scaffold folding, lossless PDF)

- **Problem.** SPAgo renders in the browser and exports CSV/SDF; it has no printable
  review artifact. `BindingDB_IO` has a mature one: one fixed pixel scale for every
  molecule so relative size is real (`figures.py`), cards with facts in the footnote
  and labels in the header (`layout.py`), a coverage rule (≤ 8 structures draws each;
  above that, Morgan2/Butina clusters labelled by Murcko scaffold, largest first, with
  the covered share stated), adaptive columns, a lossless PDF writer (`pdfio.py`), and
  a verifier that rebuilds the pages from the run folder and compares (`verify.py`).
- **Verdict LATER.** This is an independent deliverable — a second rendering engine, a
  PDF dependency, its own verifier — that duplicates nothing today and blocks nothing.
  AGENTS §17/§18: do not add the surface until a user workflow asks for an offline
  review sheet or a report attachment.
- **If built, the non-negotiables.** One scale for all molecules (no per-molecule
  normalization); records vs distinct structures kept apart in every count; no
  structure dropped silently — the artifact states its coverage; parameters travel
  with the artifact and the verifier reads them back from it.
- **Class LATER · P3 · L.**

### B-28 — Batch target run with change diff *(discussion only, not yet an item)*

`scripts/cohort_coverage.py` already loops the acceptance cohort; `BindingDB_IO`
supports several queries in one pass (`readers/multi.py`). If B-23 lands, a batch
"investigate N targets, diff against the previous run" operator command becomes cheap
and worth its own small item — record it here so it is not invented twice. It stays a
note until B-23 exists; it is not in the priority table.

### B-29 — A stored analysis as a project artifact

- **Problem.** A summary is now findable (B-10) but not *attachable*: a project can hold
  compounds and families, not the analysis that explains why they were picked. A
  scientist assembling a report still copies the summary text out by hand, and the copy
  loses its scope/version header — the exact thing B-10's export exists to preserve.
- **Scope if built.** Reference a stored analysis from a project (id + the identity
  snapshot the project already keeps for items), render it in the project view with its
  staleness stated, and include it in the project export. Deletion of the analysis must
  leave the project item readable and marked, as family/compound deletion does today
  (migration 0008's contract).
- **Why not now.** No reviewed workflow asks for it, and the export already covers "take
  it out of the app". Build it when a project-level report is actually requested.
- **Class LATER · P3 · M.**

## 3. Review discussion — what the `BindingDB_IO` implementation changes (2026-09-16)

Read-only review of `/media/chen/Machine_Disk/Datasets/BindingDB_IO/` (README,
`AGENTS.md`, `task_plan.md`, `bindingdb_io/{readers/{tsv,lmdb,multi,api},web_supplement,patents,schema,activity,filters,dedupe}.py`,
`cli/{extract_target,audit_patent_coverage,apply_activity}.py`,
`docs/version_merge.md`, `examples/`). Nothing in that project was modified, and no code
was copied into SPAgo by this register.

| Source capability | Source evidence | SPAgo today (checked) | Verdict |
| --- | --- | --- | --- |
| Target → ligands over the local snapshots, one pass, several queries | `readers/multi.py`, `readers/tsv.py`, `readers/lmdb.py` | Bounded REST only (`adapters/bindingdb_rest.py`); DuckDB reads a fixture directory (`queries/bulk.py`) | **Adopt, TSV first** → B-23 |
| Patent → ligands over the same dumps and over supplements | `patents.py::{search_tsv_by_patents, search_lmdb_by_patents, search_supplements_by_patents}` | No patent-led local search | Fold into B-23 / B-26 |
| Patent → compounds via ChEMBL documents + activities | `readers/api.py::search_chembl_patent_api` | Target-led ChEMBL only; the document lookup serves declared patents of already-discovered compounds | **Adopt** → B-24 |
| Two snapshots of one source merged by a stated priority (newer wins, empties backfilled), keyed by reactant id with an InChIKey fallback | `dedupe.py`, `docs/version_merge.md` | Per-InChIKey union across *different* sources; no two-snapshot case exists yet | Adopt as the policy when B-23 lands |
| Web/literature supplement: mandatory note, refs, structure-less remarks, applied only when the set is empty or fails the gate | `web_supplement.py`, `extract_target.py` (`--web-only-if-empty`, `--web-if-no-active`) | One-row POST + dialog (ONLINE-07); no bundle, no prompt at gate failure | **Adopt** → B-25 |
| Per-patent coverage audit with named statuses and a summary | `cli/audit_patent_coverage.py`, `patents.py` | Ingredients stored, no report or view | **Adopt** → B-26 |
| Activity classes + screening-reference gate | `activity.py` | Already ported and extended (ONLINE-06; deterministic modality classifier, policy version travels) | **Done — do not re-import** |
| MW ≤ 1000 peptide filter | `filters.py` | Deliberately not used; modality classification decides instead | **Reject** (noise filter, not identity) |
| Real target names kept out of source; aliases via tempfile | `alias_io.py`, `BindingDB_IO/AGENTS.md` §Confidentiality | Target queries are runtime user input; the risk is committed fixtures and alias files | **Adopt as hygiene** → `AGENTS.md` §34 |
| XLSX export | `writers/export.py` | CSV/SDF | **Reject** (already decided) |
| Fixed-scale card sheet + lossless PDF + verifier | `figures.py`, `layout.py`, `pdfio.py`, `verify.py` | Browser depiction + CSV/SDF | **LATER** → B-27 |
| A verifier takes its parameters from the artifact it verifies | `verify.py` (dpi/bond/columns read back from `run_meta.json`) | Round records re-state their parameters by hand | **Adopt as a rule** → `AGENTS.md` §36 |

**Ordering argument.** B-24 goes first among the new items: it is bounded, ungated,
uses a source the build already talks to, and it repairs a degradation in the primary
loop (enter a patent → see its compounds) that exists today whenever the corpus is
thin. B-25 is second because the supplement path is already shipped and the missing
piece is the shape its real producers use — without it, "agent + sources" stays manual
data entry. B-23 is third: the largest coverage gain, but operator- and file-gated, and
its value is local; it must not be mistaken for a beta capability. B-26 follows because
it is only as useful as the sources it summarizes (B-02, B-23, B-24). None of the new
items closes a `docs/online-capability.md` §6 checkbox, and none of them changes the
recommendation to pass the hosted gate first.

**What does *not* change.** The bounded-REST path stays the default for the hosted
deployment; the snapshots do not become a second source of truth; the potency gate,
modality rules and provenance states are reused rather than reimplemented; and the
rejected items above stay rejected — this review is an argument for four specific
ports, not for adopting the source project as a component (AGENTS §2, §6).

## 4. P1 in one sentence each

1. **B-13** — *delivered 2026-09-16:* make the §6 gate cheaper to pass and harder to fake.
2. **B-01** — *delivered 2026-09-16:* make "search real patents" mean more than "search
   what was imported".
3. **B-10** — *delivered 2026-09-16:* let a scientist keep and find the analysis they
   already paid for.
4. **B-02** — *delivered 2026-09-16:* prove the patent-linkage claim on live data, and say
   exactly how far it reaches.
5. **B-24** — *delivered 2026-09-16:* make "enter a patent, see its compounds" survive a
   corpus that does not hold that patent.
6. **B-03** — *open:* let the number a scientist actually types open the family it names.

## 5. Deliberately out (do not treat as queued)

- PDF extraction / OCSR as a data path — AGENTS §30; no measured coverage gap justifies
  it yet, and M6 is not started.
- Markush / R-group search — AGENTS §31.
- General chat / open-ended assistant — deferred in the current contract.
- XLSX writer, a second tabular export format — duplicate surface (§18; bindingdb plan K).
- Redis / Celery / Elasticsearch / vector or graph database / microservices — §6, no
  ADR and no measured need.
- Espacenet UI automation — §5, permanent.
- Multi-tenant team sharing, SSO, password reset, public signup — out of the invited-beta
  scope until the operator decides otherwise.

## 6. Update log

| Date | Change |
| --- | --- |
| 2026-09-16 | Register created (planning-only stage). Items grounded by reading `PROMPT.md`, `AGENTS.md`, `docs/online-capability.md`, `docs/runbook.md`, the active plans, and the current checkout (`services/core`, `apps/web`, `scripts/`, `migrations/`). Owner request recorded: target-led open-database work (ChEMBL/BindingDB/PubChem) and LLM-summary archive/retrieval enter the backlog as B-06…B-09, B-07, B-08 and B-10. No code changed. |
| 2026-09-16 | Second planning-only stage. `BindingDB_IO` reviewed read-only; §3 added with the adopt/defer/reject argument; new items B-23 (local snapshot search), B-24 (patent-led ChEMBL compounds), B-25 (supplement bundle import), B-26 (patent coverage audit), B-27 (review sheet, LATER) and the B-28 note recorded; priority table and P2 order updated. `AGENTS.md` gained the snapshot, agent-retrieval, repository-hygiene and acceptance/verifier rules; `docs/online-capability.md` §6 gained the hosted-acceptance definition and success criteria. No application code changed. |
| 2026-09-16 | **B-13 delivered** after the hosted-acceptance rehearsal: `scripts/restore_check.sh` (scripted §H7 rehearsal; verified against the rehearsal stack and against a deliberate mismatch) and the §H2 "ingress duties" table (TLS, compression with the measured 20.3 MB → 4.95 MB figure, throttling, logs, backup schedule). The rehearsal also produced `docs/plans/2026-09-16-hosted-acceptance-rehearsal.md` and five defect fixes (target-summary bounds, rejected-call token accounting, transport-failure outcome, drill mode, §H7 column name). |
| 2026-09-16 | **B-01 delivered** (`scripts/corpus_batch.py`, `spago_core.corpus_status`, `GET /api/v1/corpus` + `CorpusDialog.tsx`). No re-sorting needed: the priority order below is unchanged, and B-10 is now the top P1 item. Two scope notes recorded: the batch loop is an operator-side chunker (no queue service, §6/§22), and the corpus counts are computed per request rather than maintained — the measured cost is in the plan file, and a corpus large enough to need counters is a measured problem, not a guess. |
| 2026-09-16 | **B-02 delivered** (`source_retrievals.reference_counts` + migration 0016, `spago_core/domain/document_refs.py`, the `--declarations` live measurement, and the target header's *Source notes and reference coverage* disclosure). Re-sorted: **B-24 is now the top P1 item**; B-02 leaves the table. The delivery answered the item's blocker with a live number instead of an assumption — 135 of IL6's 166 kept records carry a source-declared patent number, and EGFR's are 1,187 DOI-only plus 1,210 whose cited document the source does not return — and it surfaced a defect it did not set out to find: every retrieval's `warnings` (including "the lookup bound was reached") was persisted, served and rendered nowhere in the UI. Three scope notes: the tally is computed by the service over the records it kept, not by each adapter, so it means one thing for every source; a record already excluded for a missing structure or value is counted in `rejection_counts`, never in this tally; and no new dependency was added. |
| 2026-09-16 | **B-10 delivered** (`services/analyses.py`, `GET /api/v1/analyses`, `/analyses/{id}`, `/analyses/{id}/export`, `AnalysesDialog.tsx`). Re-sorted: **B-02 is now the top P1 item**; B-10 leaves the table. One new backlog item recorded from building it — **B-29** (attach a stored analysis to a project, and cite it from the project view), `LATER · M`: the capability statement already promises that saved work reopens, and an analysis is now an artifact a project can point at, but no reviewed workflow asks for it yet. |
| 2026-09-16 | **B-24 delivered** (`ChEMBLDiscoveryAdapter.declared_compounds`, `services/patent_sources.py`, migration 0017, the `source-compounds` read/lookup/export routes, `SourceDeclaredCompounds.tsx`, `scripts/patent_source_lookup.py`; live record in `benchmarks/patent-source-declarations-2026-09-16.md`). Re-sorted, with the moves stated: **B-03 is promoted to P1** — with the corpus no longer the only answer, the remaining primary-loop failure is the *entry*: `find_patent` matches the stored string exactly, and the search box classifies by a kind-code-shaped regex, so `wo 2020/123456` for a stored `WO-2020-123456-A` opens nothing. It is a day of work, ungated, and it feeds the same normalizer the patent-led path already uses. **B-26 moves ahead of B-23**: B-24 landed, so the audit's ChEMBL leg is content that exists today, while B-23 stays operator- and file-gated and is explicitly a workstation gain rather than a beta capability. B-24 leaves the table, and B-25 heads the P2 order unchanged. |
