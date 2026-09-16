# SPAgo backlog register

Status: **living register — open entries are proposals; delivered entries are history.**
An open entry is not implementation approval or a commitment to build. What this build *does* is stated in
`docs/online-capability.md`; what it *might* do next is stated here. Classification
follows `AGENTS.md` §37 (`CORE` / `NEXT` / `LATER` / `REJECT`). An item marked
**gate** needs an operator decision (host, provider, credential, source choice or user
base) before engineering can finish it, not before engineering can start.

Last updated: **2026-09-16 — implementation round 1 after the product review:
B-33 and B-34 delivered; B-42 added.**
Current stage: a locally implemented and previously exercised product, with selected
live-source measurements and a local hosted-shape rehearsal; **hosted acceptance and
independent scientific validation remain open**. Review findings, evidence limits and
open questions: [product review Q&A](2026-09-16-product-review-qa.md).

The earlier conclusion that only operator-gated work remains is superseded: static
inspection found export-policy, saved-project navigation and citation-navigation gaps,
and the existing CI does not run the database suite or browser smoke. **B-31** makes
the existing hosted gate visible in the table. The implementation round of 2026-09-16
delivered **B-33** (export/screen policy parity, browser-reproduced then fixed) and
**B-34** (distinguishable build identity, verified on the served stack), and recorded
**B-42** — the short-viewport table collapse found during B-33's browser verification —
as the new head of the P1 group: it is small, reproduced, and hides the primary
workflow's main object. B-32's gate line drops its B-34 dependency (delivered); the
independent-reviewer gate stands.

## 0. Standing constraints for everything below

- The operator gate in `docs/online-capability.md` §6 comes first. Implementation or
  documentation completion alone cannot close a checkbox. B-31 records acceptance
  only when the corresponding real-deployment and human-review artifacts exist.
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

Rank is top-to-bottom within a priority. Order reflects harm to the existing workflow,
acceptance value and dependencies before coverage breadth or feature count; an empty
priority group is not a reason to promote its successor. A gated item keeps its product
priority, while independent engineering can proceed after an implementation round is
authorized. This planning-only round authorizes none of those actions.

| Priority | ID | Item | Class | Effort | Gate / blocker |
| --- | --- | --- | --- | --- | --- |
| P0 | B-31 | Real hosted pilot acceptance | CORE | M + operator time | real host/TLS, provider/budget, invited scientist; B-32 evidence |
| P1 | B-42 | Candidate table collapses on short viewports (layout, not data) | CORE | S | browser-reproduced 2026-09-16; found during B-33 verification |
| P1 | B-32 | Scientific cross-read and reproducible coverage cohorts | CORE | M + reviewer time | B-34 delivered; independent reviewer for acceptance |
| P1 | B-35 | Full PostgreSQL/RDKit suite and existing browser smoke in CI | CORE | M | runner Docker/build feasibility; reuse shipped stack |
| P1 | B-36 | Reopen every saved target/family scope in a mixed project | CORE | M | static finding; browser reproduction first |
| P1 | B-37 | Summary citation → exact supporting record | CORE | M | typed citation/snapshot navigation contract |
| P1 | B-30 | Source refresh retraction within an explicit access/query scope | CORE | M | absence semantics first; no cross-path retraction |
| P2 | B-38 | Browser regression for failures, stale responses and saved work | NEXT | M | reuse B-17; B-35 for automatic execution |
| P2 | B-19 | Keyboard and dialog accessibility in the existing layout | NEXT | M | browser/assistive-technology evidence |
| P2 | B-29 | A stored analysis as a project artifact | NEXT | M | B-36/B-37 first; preserve owner and snapshot rules |
| P2 | B-39 | Reopen a saved investigation with its filters and policy | NEXT | M | bounded private state contract; no sensitive URL payloads |
| P2 | B-21 | Claim-text source feasibility and evidence design | NEXT | S–M decision; L integration | source/terms/sample decision; integration separately gated |
| P2 | B-09 | Reviewed target-scope catalog expansion | NEXT | M | scientific review |
| P2 | B-11 | Refusal explanation, then second-provider evaluation | NEXT | M | explanation ungated; provider/budget gate on live evaluation |
| P3 | B-40 | Small cross-family SAR comparison with assay comparability | LATER | M–L | reviewed comparison task + matched assay context |
| P3 | B-08 | BindingDB assay-context enrichment *(owner request group)* | LATER | M | source capability check |
| P3 | B-28 | Bounded multi-target snapshot run and change report | LATER | M | B-30 plus measured repeated-batch need |
| P3 | B-27 | Structure review sheet (fixed-scale cards, scaffold folding, lossless PDF) | LATER | L | user workflow ask |
| P3 | B-05 | Bulk analytical filtering surface (DuckDB/Parquet) | LATER | L | ADR + dataset + measured metadata-search need |
| P3 | B-22 | EPO OPS adapter (bibliographic / family / full-text enrichment) | LATER | L | B-21/source decision, credentials + ADR |
| P3 | B-07 | PubChem BioAssay bounded CID→AID path *(owner request group)* | LATER | M–L | bounded design |
| P3 | B-41 | Pick an exact publication from an ambiguous lookup | LATER | S | validate frequency in pilot; exact-number workaround exists |
| P3 | B-20 | Chinese UI / i18n | LATER | L | user-base decision |
| P3 | B-16 | Operator usage visibility (decide: docs-only or small admin view) | LATER | S | pilot evidence that API/runbook is insufficient |
| P3 | B-12 | Multi-worker deployment (shared in-flight model registry) | LATER | M | scaling need |
| — | — | *(rejected / deliberately out — see §5)* | REJECT | — | — |

P0 = required release decision/evidence, including operator work; it is not a feature.
P1 = correctness and repeatability of the workflow the gate tests, before or alongside
the invited beta. P2 = the next implementation round candidates, in the order
shown. P3 = deliberately later; a P3 item needs a decision or a measured need before it
becomes P2.

**What moved and why.** B-09 is no longer the head: validating the current scientific
cohort and repairing export/save/evidence continuity precede expanding that cohort.
B-30 moves P3/LATER → P1/CORE because retries and the snapshot path now coexist, so
current versus historical rows is an existing correctness question. B-19 and B-29 move
P3/LATER → P2/NEXT to make the existing workflow operable and its decisions reusable.
B-21 moves from a broad LATER integration to a NEXT feasibility decision; B-22 moves
P2 → P3 until that decision justifies OPS. B-11 retains P2, but its refusal UX no longer
waits for a second provider. B-28 is ranked P3, behind trustworthy refresh semantics.
B-40/B-41 remain exploratory; they do not displace reliability work. Historical
delivery counts and measurements below are retained as historical evidence, not rerun.

**Delivered from this register (kept out of the table, with the artifact that closed
it):**

| ID | Delivered | Artifact |
| --- | --- | --- |
| B-01 | 2026-09-16 | `scripts/corpus_batch.py` (chunked extract → import with resumable `STATE.json`, per-chunk status, non-zero exit and an explicit missing-number list when the corpus does not hold the requested set); `spago_core.corpus_status` (terminal surface; `--patents` exits non-zero and prints every number that is not loaded) and `GET /api/v1/corpus` behind the top-bar dataset badge (`CorpusDialog.tsx`) — counts read from the corpus tables, per dataset version, with failed/interrupted imports and unregistered versions reported. |
| B-10 | 2026-09-16 | Read path over `ai_analyses`: `GET /api/v1/analyses` (owner-scoped list with scope label, model, prompt/policy version, tokens, staleness reasons), `GET /api/v1/analyses/{id}` (stored text + citations + the exact input-fingerprint check), `GET /api/v1/analyses/{id}/export` (Markdown whose header states scope, provider, model, prompt, policy, data version and citations), and the top-bar **Analyses** dialog (`AnalysesDialog.tsx`) that reopens them without a provider call. |
| B-02 | 2026-09-16 | A disjoint per-retrieval tally of how each kept record's document reference resolved (`source_retrievals.reference_counts`, migration 0016; vocabulary in `spago_core/domain/document_refs.py`), served by `GET /targets/{id}/coverage` and rendered in the target header's **Source notes and reference coverage** disclosure together with the source notes that were previously stored and never shown; `scripts/cohort_coverage.py --declarations` measures it live and read-only, recorded in `benchmarks/reference-declarations-2026-09-16.{md,json}` (135 of IL6's 166 kept records carry a source-declared patent — the live linkage the handoff could not previously point at). |
| B-13 | 2026-09-16 | `scripts/restore_check.sh` (dumps, restores, compares the §H7 counts, fails non-zero on mismatch, verified against the rehearsal stack and against a deliberate mismatch) and the §H2 ingress-duty table (compression, TLS, throttling, logs, backup schedule) in `docs/runbook.md`. |
| B-24 | 2026-09-16 | The patent-led read path: `ChEMBLDiscoveryAdapter.declared_compounds` (body-search rule `chembl-document-patent-body-v1`, exact-normalization verification, near matches listed and excluded), `services/patent_sources.py` + migration 0017 (`patent_source_lookups` / `patent_source_compounds`, no `compound_mentions` row ever written), `POST`/`GET /api/v1/patents/{number}/source-compounds` and `/export?format=csv|sdf`, `SourceDeclaredCompounds.tsx` (under the patent view and on a publication the corpus does not hold, where the 404 used to be a dead end), and `scripts/patent_source_lookup.py`; live record `benchmarks/patent-source-declarations-2026-09-16.{md,json}` (US10508115 → 134 declared records for 73 compounds out of 402 seen, 5 states kept apart). |
| B-03 | 2026-09-16 | Tolerant publication entry: `domain/patent_numbers.py` `looks_like_publication_number` + `MATCH_RULE` (`publication-number-tolerant-v1`, one pattern mirrored in `apps/web/src/state/url.ts` and kept in step by a parity test), `services.find_patent` exact-first then one normalized comparison, `PatentLookup` + `AmbiguousError` (409 with the candidates named), `PatentMatch` in the response, the `match-note` in the table heading, and the same rule in `planner.py` / `plan_execution.py`; `services/core/tests/test_b03_tolerant_lookup.py` (48 cases, suite 595 → 643) and `benchmarks/tolerant-lookup-2026-09-16.{md,json}` (exact 1.35 ms unchanged; a tolerant hit or miss costs one metadata scan, 155 ms at 50 000 documents). |
| B-25 | 2026-09-16 | The bundle path: `domain/models.py` `SupplementBundle` / `SupplementImportReport` / `SupplementConfirmation` / `SuppliedRowState`, `services/supplements.py` (`map_bundle_record` alias table + contradiction refusals, `import_supplement_bundle`, `confirm_supplement_import`, provenance-preserving upserts), migrations 0018 (`supplement_imports` — the run, its per-row answers including refusals, and who confirmed it) and 0019 (remark provenance constraint widened to the five states), `POST /targets/{id}/supplements/bundle` + `GET …/supplement-imports` + `POST …/supplement-imports/{id}/confirm`, `unreviewed_supplements` on the verdict, `SupplementDialog`'s bundle pane and `ReferenceStrip`'s review control; `tests/test_b25_supplement_bundle.py` (34 cases, suite 643 → 677). Browser-verified end to end on the local stack (import → report → confirm → verdict/candidates → withdraw → re-import → read back), which found and fixed three defects the unit tests could not (duplicate rendering of the fresh report, a re-posted remark not counted as an update, `repeated_of` not derived on read-back). |
| B-26 | 2026-09-16 | The coverage audit: `CoverageAnswer` / `CoverageLeg` / `PublicationCoverage` / `CoverageReport` + `COVERAGE_RULE = patent-coverage-v1`, `services/coverage.py` (`audit_publications` over the corpus, stored per-publication lookups, target-led rows and hand-added rows; `_headline` order `corpus > declared > supplement > proposed > empty > failed > not_queried`; `unqueried` naming every leg nobody asked; `merge_coverage_reports` for lists over the 50 bound; CSV/Markdown renderers), `POST /api/v1/patents/coverage` and `/coverage/export?format=markdown\|csv\|json` (rule in a header *and* in the file), `PublicationCoverage.tsx` (the collapsed *Coverage* strip in the patent view and on the 404 path, with the document jump and the export control) and `scripts/patent_coverage.py`; `tests/test_b26_coverage_audit.py` (39 cases, suite 677 → 716 — corrected 2026-09-16 from the B-06 round, whose `--collect-only` reads 727 including its own 11 cases; the 741 recorded at delivery was an ad-hoc count); live record `benchmarks/patent-coverage-2026-09-16.{md,json}` (5 publications p50 4.4 ms / 11.7 KB, the 50-publication bound p50 5.5 ms, and one request showing `corpus` / `declared` ×2 / `asked_empty` / `not_queried` kept apart). Browser-verified on the local stack (404 path, family view, document jump, never-asked row, export request) including the failure state by blocking the route: the strip then shows no counts at all, so a failed read cannot be misread as an absence. |
| B-06 | 2026-09-16 | Per-source re-run: `investigate` now persists **only the sources it asked** (a source the run did not ask is reported from its stored row, or recorded `not_queried` only when it has never been asked), `DiscoveryReport.requested_sources` as the run's own scope, `RetrievalResponse.requested_in_run`, a refusal (422) for a run that names no source, the target header's per-source **Retry** control on a `failed`/`partial` chip with that source's own last-run cost, and `discoverNote` naming what the run asked and what it did not; `tests/test_b06_per_source_rerun.py` (11 cases, suite 716 → 727 collected, all passing), record `benchmarks/per-source-rerun-2026-09-16.{md,json}`. |
| B-23 | 2026-09-16 | Local BindingDB release as a source path: `adapters/bindingdb_snapshot.py` (one streaming pass, stdlib only — required/endpoint columns, accession-first matching across every chain's UniProt column, exact `Target Name` by default, organism canonicalized/filtered with counted exclusions, one record per filled endpoint, in-pass digest) and `scripts/bindingdb_snapshot.py` (operator entry point: target from stored rows, `--dry-run`, `--max-rows`/`--max-seconds`, JSON record, exit codes 0/1/2; deliberately not reachable from the app, §21); `tests/test_b23_bindingdb_snapshot.py` (36 cases) over the synthetic fixture `data/fixtures/open_sources/bindingdb_snapshot_sample.tsv` (17 rows); acceptance on the operator's real 8.98 GB / 3,237,052-row release in `benchmarks/bindingdb-snapshot-2026-09-16.{md,json}` — 113.2 s, 153 kept records all matched by accession, digest in the same pass, a bound produces `partial` with no digest, and the stored REST set (9 compounds) reconciles as a strict subset of the file's 133. The round also fixed the retrieval upsert, which never rewrote `query`/`pages_fetched`/`source_version`/`dataset_version`/`checksum` (a snapshot run after a REST call still read `bindingdb-rest`), and surfaced the access path in the target header's source line. |
| B-15 | 2026-09-16 | In-process response compression: `GZipMiddleware` in `spago_core/main.py` (level 6, `minimum_size` 500, thread threshold matched to `FileResponse`'s 64 KiB chunk so file chunks are compressed off the event loop), with `tests/test_served_assets.py` (8 cases: settings asserted from `create_app()` itself, gzip + `vary` for an accepting client, identity for one that does not, small bodies untouched, `application/wasm` compressed, no stale `content-length` on a streamed body, `image/png` never re-encoded). Measured on the rebuilt container in `benchmarks/asset-compression-2026-09-16.md`: the structure dialog's first open transfers **5,234,921 B instead of 20,269,580 B** (3.87×; entry JS+CSS 392,253 → 112,461), the browser's own resource timing confirms the four page-visible dialog assets at their compressed sizes, and `/healthz` stayed at 3.5–7.8 ms during three cold gzipped WASM transfers. No dependency added (§23 not triggered), no new service (§6 not engaged). The round also carried two `scripts/bindingdb_snapshot.py` fixes its tests found: the human preamble now follows `--json -` output to stderr, and the test-side database URL keeps its password. |
| B-04 | 2026-09-16 | Import refresh completeness + interrupted-import resume: migration 0020 (`measurements.retracted_by_dataset_version`, both `m.*` views recreated), `seed.py`'s source-scoped restore-then-retract for the activity release (`SeedReport.retracted_measurements`, the summary reports the count), `import_package.py`'s `resumed_jobs` (interrupted jobs whose package checksums the re-run re-imported), the read-path move to `current_measurements` (`bioactivity.py` compound/family activity — a withdrawn hand-added row had still rendered; `ai.py`'s five family/document measurement reads; `discovery.py`'s evidence-class filter), and the stated resume policy (runbook §2, README); `tests/test_b04_import_refresh.py` (6 cases, suite 773 → 779, all passing), plan `docs/plans/2026-09-16-import-refresh-completeness.md`, `AGENTS.md` §10 gained the retraction-scope and current-state-read rule. Compounds are identity, not mappings — a release that drops a compound retracts its occurrences (the family page follows) and keeps the identity row; a document a release stops carrying entirely is *not* retracted (absence beyond the package's own documents is B-30-class and stays unclaimed). No new dependency, no new service; EXPLAIN on the changed reads confirms the existing partial index still serves them. |
| B-18 | 2026-09-16 | The companion's browser check now verifies the panel-behavior flag the toolbar click relies on: `chrome.sidePanel.getPanelBehavior()` is read back from the running worker and must return `openPanelOnActionClick: true` — a failed `setPanelBehavior` was previously a silent `console.error`, and the click would have done nothing. Run recorded on this machine against the unbranded Playwright Chromium build (`~/.cache/ms-playwright/chromium-1217`), which resolves the item's gate here: load, worker, detection, handoff, panel render and behavior flag all verified. The **physical toolbar click and the side-panel surface chrome stay uncovered**, with the reason stated in the script itself: synthesizing a browser-toolbar user gesture needs OS-level input injection (no Xvfb/xdotool on this workstation) or a keyboard-shortcut command added to the manifest for the test's sake — a product change this round did not make. PROMPT.md M4 and the handoff block, README and the architecture overview were updated to the same wording. |
| B-14 | 2026-09-16 | CI runs the existing check script: `.github/workflows/checks.yml` calls `scripts/run_checks.sh --no-pg` (the developer entry point itself — no duplicated check logic) on every push and pull request, with the shipped container's versions (python 3.12, node 22) and pip/npm caching. **Executed and green on the real host**: run 35102219606, `checks` job success in 1m07s on ubuntu-latest. The stated limit, in the workflow and README alike: the database-dependent majority of the suite keeps its scratch-database behaviour — CI does not run the full suite until someone provides a cartridge-bearing image; a runner Node-24 deprecation annotation on the actions is cosmetic. |
| B-17 | 2026-09-16 | One runner, one smoke of the MVP loop: `@playwright/test` (dev dep, Apache-2.0; §23 decision + alternatives recorded in `THIRD_PARTY_NOTICES.md` §2 in the same change), `apps/web/playwright.config.ts` (baseURL `SPAGO_BASE_URL`, default `http://127.0.0.1:8000`), `apps/web/e2e/smoke.spec.ts` (search `DEMO-PATENT-A` → family table → row opens the **evidence inspector** → `Structure ▾` aspirin substructure → table restates `(structure search)` ≥ 1 row → `Export ▾` yields a `spago-export.csv` download), `npm run test:e2e`, artifacts git-ignored. Passed in 1.6 s against the rebuilt stack — which also applied migration 0020 to the stack database; `npm run build` unchanged. The first run corrected the spec's own assumption: a row click opens the evidence inspector, not a structure drawer — the smoke follows the real UI, no app code changed. Limits stated in the plan (`docs/plans/2026-09-16-e2e-smoke.md`): the smoke is not wired into CI (CI has no seeded stack), and it does not duplicate the Python suite's API coverage. |
| B-33 | 2026-09-16 | Target screen/export parity: `ExportRequest.evidence_class` (validated five-class vocabulary, 422 on a family scope that sends it) + the same `current_measurements` existence clause the screen uses in `collect_candidate_export_rows` (results scope only — a selection names its own rows), the frontend passing the live `referenceThresholdNanomolar` / `evidenceClassFilter` through `ExportMenu` and `api.exportFile`, and a truthful export hint. Browser-reproduced first on the stored IL6 investigation (menu claimed 141, file had 157 rows, every `reference_threshold_nM` read 10000 against a 1 nM override) and browser-verified after (141 = 141, threshold 1 nM; selection 1 row, threshold 1 nM); `tests/test_b33_export_parity.py` (8 cases, per-class export == screen set) + 104-test regression green. Plan: `docs/plans/2026-09-16-export-policy-parity.md`. Found and recorded en route: **B-42**. |
| B-34 | 2026-09-16 | Distinguishable build identity: `SPAGO_BUILD_ID` env injected at packaging (`docker/app/Dockerfile` build arg baked into the image, compose `${SPAGO_BUILD_ID:-unknown}`, `scripts/build_app.sh` computing `git describe --always --dirty`), `/healthz` carries `build_id` + `build_source` with explicit `unknown` (never guessed from `api_version`), and `scripts/build_identity.py --expected <id> [--require]` compares expected vs served and fails on mismatch/unknown. Verified end-to-end on the rebuilt stack: `/healthz` served `12aa498-dirty`, recorder exit 0. The round's own review found the build script exporting an empty variable (never the computed id) — fixed and caught by exactly the served-artifact check the item exists for; the lesson is in the plan. `tests/test_b34_build_identity.py` (6 cases). Plan: `docs/plans/2026-09-16-build-identity.md`. |

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

**Delivered 2026-09-16** (`docs/plans/2026-09-16-tolerant-publication-lookup.md`). The
shipped rule is one deterministic *shape* (`^[A-Z]{2}\d{6,13}(?:[A-Z]\d?)?$` after
separators are removed and the string is uppercased), mirrored in the client and kept in
step by a parity test, so the search box and the server agree on what is a number and
what is prose. Two things the item statement did not anticipate: the plan path had to
learn the same rule (a number typed into the ask box reached the language model instead of
the patent endpoint), and the declared-compound panel had to compare *canonical* forms —
its string comparison silently discarded a successful lookup for a slash form
(`SourceDeclaredCompounds.tsx`), which only the browser check could see.

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
- **Class NEXT · P1 (delivered 2026-09-16) · S.**

### B-04 — Import refresh completeness and interrupted-import resume

**Delivered 2026-09-16** (`docs/plans/2026-09-16-import-refresh-completeness.md`; see
the delivered table in §1). The scope and the two deliberate limits below are kept as
the record. What building it added to the item statement: the *reads* were the bigger
gap — `bioactivity.py`'s compound/family activity views, `ai.py`'s family/document
measurement totals and `discovery.py`'s evidence-class filter all read the
`measurements` base table, so even the withdraw retraction that already existed kept
rendering; those now go through `current_measurements`, and `AGENTS.md` §10 states the
rule so the next read cannot regress. Compounds turned out to need a *negative*
decision rather than code: a compound row is identity (InChIKey-keyed, shared across
sources, referenced by project snapshots), so a release that drops a compound retracts
its occurrences and the family page follows — the identity row stays, and that is
tested as such.

- **Problem.** README still states: source refresh does not yet retract deleted or
  invalid *mappings*, and an interrupted import job has no recovery protocol. D4
  retracts `compound_mentions` + `evidence_records` only (`seed.py`); compounds and
  measurements dropped by a release are not covered. D5 marks a dead job
  `interrupted` (`import_package.py`) but a re-run redoes the whole package.
- **Scope if built.** Extend retraction to the remaining mapping kinds with the same
  never-delete semantics and a recorded reason; define a resume/retry policy for large
  packages (bounded, idempotent, no duplicate records) and state it in the runbook.
- **Acceptance sketch, met.** A release that drops a measurement retracts it and
  reports the count (`tests/test_b04_import_refresh.py`); a release that drops a
  compound's last occurrence empties it from the family page while identity persists;
  an interrupted import's re-run completes without duplicating rows and names the
  interrupted job(s) it carried (`resumed_jobs`, checksum-matched).
- **Deliberate limits.** Document-level retraction (a release that stops carrying a
  document entirely) is B-30-class absence and stays unclaimed; resume is a recorded
  re-run, not incremental checkpointing — the ingest is one transaction, so there is
  no partial state to resume from, and package bounds (100 000 rows/table) keep the
  redo cheap.
- **Class NEXT · delivered 2026-09-16 · M.**

### B-05 — Bulk analytical filtering surface (DuckDB/Parquet)

- **Problem.** `queries/bulk.py` reads a fixture directory only and the single exposed
  endpoint is `/bulk/compound-counts`. PROMPT §11 A (date/assignee/CPC filtering over
  SureChEMBL Parquet) has no user surface.
- **Gate.** A dataset release, a schema version and an ADR (§6/§33); AGENTS §7 keeps
  bulk analysis in DuckDB rather than the transactional database.
- **Class LATER · P3 · L.**

### B-06 — Per-source re-run for target investigations *(owner request group)*

**Delivered 2026-09-16** (P1, `S–M`, ungated). The problem was sharper than the register
recorded: `investigate` built a `not_queried` row for every source it did **not** ask and
persisted all of them, and the retrieval id is one row per (target, source) — so a subset run
**overwrote** the other sources' stored outcome with `not_queried` while their candidate rows
stayed in the database. The status machine could therefore say "nobody asked ChEMBL" beside
ChEMBL's own rows. The recovery path and that defect are the same fix.

- **Delivered scope.** Only the asked sources are written; a source the run did not ask is
  reported from its stored row (status, counts and `retrieved_at` intact) or recorded
  `not_queried` **only** when it has never been asked, so "nobody asked this one" stays
  visible. `DiscoveryReport.requested_sources` is the run's own scope; the response marks
  every row `requested_in_run` (null on the stored-state coverage read); naming no source is
  refused 422. In the target header the retry is offered where the all-source refresh is the
  wrong tool (`failed` / `partial` chips) and carries that source's own last-run cost (pages,
  records seen, wall time) before the click, plus a line stating what the run did and did not
  ask.
- **Not built, deliberately.** No retraction of rows a source no longer returns (a failed or
  bounded ask establishes no absence; when a *complete* ask does is B-30), no stored-summary
  rewrite (the verdict is recomputed on read and does reflect the retry), no per-source
  control on a healthy chip (the all-source refresh owns that case).
- **Acceptance sketch, met.** A target with one failed source retries only that source: the
  other sources' retrieval rows, counts and `retrieved_at` are unchanged, their candidate
  rows keep their own retrieval time, the verdict counts them exactly as before, and the
  retry is a visible new outcome in `source_retrievals`
  (`tests/test_b06_per_source_rerun.py`, 11 cases; the write set is measured in
  `benchmarks/per-source-rerun-2026-09-16.md`).
- **Residual risk to keep in view.** A successful re-run does not remove a row the source no
  longer reports — the investigation then holds that row, dated to when it was retrieved.
  That is stated in the retry's own docs rather than implied away, and is B-30's subject.
- **Class NEXT · delivered · S–M.**

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
- **Order after this review.** Choose the next system from an actual pilot question,
  after B-32 checks the current cohort. More catalog entries alone do not establish
  better scientific coverage (`PROMPT.md` §2.1/§2.5).
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

### B-11 — Refusal explanation, then second model-provider evaluation

- **Problem.** Capability §8: quality/latency/token usage/failure rate are measured for
  **one** provider (DeepSeek `deepseek-flash`); any other endpoint the operator chooses
  is unverified, and an answer rejected twice in a row (one re-sample allowed) still
  fails as 502.
- **Two separable steps.** The refusal explanation for the existing provider can be
  designed and verified with bounded fixture failures now; it need not wait for
  provider procurement. A second live-provider evaluation remains gated.
- **Gate for live evaluation.** The operator picks the provider and budget; the evaluation then records
  model id, endpoint fingerprint, per-scope calls, tokens, latency, failures and cache
  behaviour (`benchmarks/online01-llm-eval-2026-09-15.md` is the method).
- **Scope if built.** Run the same evaluation against a second provider; surface the
  refusal class and the remaining retry budget in the UI instead of a bare 502.
- **Acceptance.** Transport failure, invalid output and quota refusal remain distinct;
  the user can tell whether another call will be billed. No automatic retries beyond
  the current policy. A new provider report measures compatibility, not truth of its
  answers (B-32), and no endpoint is selected by this plan.
- **Class NEXT · P2 · M (provider/budget gate applies to live evaluation only).**

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

**Delivered 2026-09-16** (`.github/workflows/checks.yml`; see the delivered table in
§1, which records the green hosted run). The item's gate ("repo hosting decision") was
argued resolved by the checkout itself — `origin` is GitHub — and the workflow was
verified by its own execution, not by reading it. The coverage limit is stated in the
workflow and README: `--no-pg` only, until a cartridge-bearing CI image exists.

- **Problem (as it was).** There is no `.github/` (or equivalent) in the checkout;
  every recorded round ran `scripts/run_checks.sh` by hand, and the frontend/build
  regression is detectable only by a person remembering to run it.
- **Class NEXT · delivered 2026-09-16 · S.**

### B-15 — Compress served assets (Ketcher first open) — *delivered 2026-09-16*

- **Problem (as it was).** Measured and recorded (capability §5;
  `benchmarks/online08-structure-editor-2026-09-16.md`): the shipped container served
  assets uncompressed, so a first editor open transferred ~20.3 MB raw instead of
  ~4.95 MB gzip. Entry bundle was unaffected (320 KB raw / 93 KB gzip).
- **Delivered.** `GZipMiddleware` in the app process (level 6, 64 KiB thread threshold),
  8 tests in `services/core/tests/test_served_assets.py`, and the re-measurement in
  `benchmarks/asset-compression-2026-09-16.md`: **20,269,580 B → 5,234,921 B** on the
  first editor open, entry JS+CSS 392,253 → 112,461 B, `/healthz` 3.5–7.8 ms during
  three cold gzipped WASM transfers. No dependency, no new service.
- **Class NEXT · delivered · S–M.** The remaining compression is a proxy's option
  (brotli), recorded in `docs/runbook.md` §H2 as optional rather than blocking.

### B-16 — Operator usage visibility

- **Problem.** `/api/v1/usage` and `/api/v1/usage/events` exist (runbook §H6) but the
  operator reads them with curl.
- **Decision needed first.** Is a small admin-only view worth a UI surface (§17
  progressive disclosure), or is the API plus the runbook enough for one beta? If the
  answer is "API is enough", close the item as REJECT with that note.
- **Class LATER · P3 · S.**

### B-17 — Frontend test harness and one end-to-end smoke

**Delivered 2026-09-16** (`docs/plans/2026-09-16-e2e-smoke.md`; see the delivered
table in §1). The §23 dependency decision went to Playwright over Cypress (license +
architecture weight) and component-level Vitest (cannot exercise the real loop); the
smoke runs against the seeded compose stack rather than a self-booted one, because a
test that seeds its own database verifies a different deployment than the one users
run. Not wired into CI — that needs a seeded stack on the runner and is a later,
explicit step.

- **Problem (as it was).** `apps/web/package.json` had no test script and no test
  dependency; AGENTS §27 requires frontend interaction and end-to-end categories, and
  §36 requires browser evidence for UI claims. That evidence was produced manually per
  round.
- **Class NEXT · delivered 2026-09-16 · M.**

### B-18 — Chrome companion: cover the toolbar click and side-panel surface

**Delivered 2026-09-16** to the extent this checkout honestly can (see the delivered
table in §1): the unbranded-Chromium gate resolved on this workstation (the Playwright
build), and the verification now reads `openPanelOnActionClick` back from the running
worker instead of assuming the setup promise resolved. The physical toolbar click and
the side-panel surface chrome remain uncovered with the reason recorded in the script —
automating them would need OS-level input injection or a manifest keyboard-shortcut
added for the test's own sake, which is a product change that was deliberately not
made. Reopening this item means providing one of those two, not re-running the script.

- **Problem (as it was).** `apps/chrome-extension/verify-in-chrome.js` verifies load,
  detection, handoff and side-panel render; the headed toolbar click and the
  side-panel surface itself are explicitly not covered (PROMPT §14 M4).
- **Class NEXT · delivered 2026-09-16 (with the residual limit restated) · S.**

### B-19 — Accessibility pass on the virtualized table and dialogs

- **Evidence.** `CompoundTable.tsx` and `CandidateTable.tsx` place headers outside
  their `role="table"` container and handle Enter/Space on rows without excluding
  nested controls. A checkbox's Space may reach the row handler; this is a static
  finding, pending browser confirmation. `Modal.tsx` already implements focus entry,
  trapping, Escape and return — do not rebuild what is present.
- **User gain / scope.** Operate inspection, selection, structure preview and export
  with the keyboard in the existing layout (`PROMPT.md` §2.5; AGENTS §3/§18).
- **Acceptance.** Checkbox Space selects without inspecting; row Enter still
  inspects; virtual scrolling preserves usable focus; headers/cells/row counts are
  meaningful to assistive technology; modal focus behaviour remains intact. Record
  the browser, viewport, source mode and actual keyboard/reader checks, not DOM alone.
- **Class NEXT · P2 · M.** Promoted from LATER because the affected controls already ship.

### B-20 — Chinese UI / i18n

- **Problem.** The interface is English-only; there is no i18n layer in `apps/web`.
- **Gate.** Who the invited cohort is. If beta users read English, this is premature
  (YAGNI); if not, it becomes a P2 feature with its own decision about scope (UI
  strings only vs. exports and summaries too).
- **Class LATER · P3 · L (gate: user base).**

### B-21 — Claim-text source feasibility and evidence design

- **Problem.** Claims are a product pillar (PROMPT §2.1) but no claim text is stored:
  `services/ai.py` states "Claim text is not stored in this deployment", capability §5
  says claims text is not in the pipeline, and summaries say "claims were not
  assessed". This is the largest remaining gap between the product story and the
  shipped workflow — and it is *not* OCSR.
- **Gate.** A source decision and an ADR: EPO OPS full text (B-22) versus fields in the
  SureChEMBL bulk path versus another licensed source; plus storage and evidence
  mapping (claim number, paragraph, jurisdiction, language).
- **First deliverable, NEXT.** A source/terms decision, bounded representative sample,
  claim-number/paragraph/language/jurisdiction mapping and ADR with success/failure
  criteria. Reuse existing evidence inspection; choosing OPS is not assumed. The
  outcome may be that no available source meets the requirement.
- **Later integration, not approved here.** Import claim text per document with typed
  evidence, so a summary can cite the original claim (`PROMPT.md` §2.1) while retaining
  the legal boundary. This is separate from PDF chemistry and OCSR.
- **Acceptance of the decision.** A reader can trace each sample claim to the chosen
  original source and identify missing languages/jurisdictions; costs, terms, provenance
  and an implementation boundary are recorded. A proposal does not enable claims UI.
- **Class NEXT · P2 · S–M for the decision; integration L and separately gated.**

### B-22 — EPO OPS adapter (bibliographic / family / full-text enrichment)

- **Problem.** PROMPT §6/§11 lists EPO OPS as an initial source, but this checkout has
  no `adapters/ops.py`; family/bibliographic enrichment beyond what was imported does
  not exist.
- **Gate.** OPS registration and credentials (operator), EPO quota/rate-limit handling
  (§16), and an ADR; pairs with B-21.
- **Scope if built.** A bounded, cached OPS adapter for family and bibliographic
  enrichment with source name, version, retrieval timestamp and error/rate-limit state,
  surfaced through the existing evidence/provenance rules.
- **Class LATER · P3 · L (gate: source decision, credentials + ADR).** B-21 may justify
  this adapter, or a pilot may establish an independent family-metadata need; its name
  in the initial technology direction is not sufficient justification.

### B-23 — Local BindingDB snapshot search (operator dataset, TSV first)

**Delivered 2026-09-16** (`docs/plans/2026-09-16-bindingdb-snapshot.md`; record
`benchmarks/bindingdb-snapshot-2026-09-16.{md,json}`). The problem, scope, decisions and
honesty requirements below are kept as the record of what was asked. What the build
changed relative to them, stated because the register should not claim more than the
artifact: the first step is **TSV only** (LMDB deferred as argued below), matching is
the reviewed UniProt accession across every chain's `UniProt … of Target Chain N`
column with `Target Name` **exact** by default (`--name-mode auto` runs the looser
substring rule deliberately), organism rows that state a different species are excluded
and counted while an uncomparable one is kept and reported, and a bounded scan is
stored `partial` with **no** file digest — a prefix has no file identity. The
acceptance run on the operator's real release exposed and fixed a defect in the shared
write path (the retrieval upsert never rewrote the run's ask or its version columns),
which is recorded in this round's files and in B-06's. **The operator gate stands**: the
file's licence terms, where it lives and any run on another release remain the
operator's; the engineering does not close them, and this is operator tooling for a
workstation — not a capability of the hosted beta (`docs/online-capability.md` §5).

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
- **Class NEXT · delivered 2026-09-16 · M (TSV); L if LMDB is ever justified by a measured need.**

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

**Delivered 2026-09-16** (`docs/plans/2026-09-16-supplement-bundle-import.md`). The problem
and scope below are kept as the record of what was asked. Three things the item statement
did not anticipate, all found by the browser check and fixed in the round: a bundle needs
a *read-back* path (the report is stored and listed, not just returned), a re-posted
structure-less row is an update like any other (only the measurement path counted it),
and "the same file was imported before" has to be derived from the runs rather than
remembered at insert time.

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
- **Class NEXT · P1 (delivered 2026-09-16) · M.**

### B-26 — Patent coverage audit

**Delivered 2026-09-16** (see the delivered table in §1 and
`docs/plans/2026-09-16-patent-coverage-audit.md`). Kept here as the item's record: what was
promised, and what was deliberately left out.

The argument as it stood when it was promoted to P1, when B-25 landed and emptied the P1
group: it is the one item that answers "what do we have for this publication, from where,
and what is missing", in a build where four independent paths now contribute to that answer
(the imported corpus, B-02's reference tally, B-24's declared sets, B-25's hand-added rows)
and nothing summarized them per publication. It is ungated, and its `not_queried` state is
exactly the honesty rule the last three rounds were about.

- **Problem.** Nobody could answer "which publications in this family have compounds, from
  where, and which are uncovered?" `BindingDB_IO` answers exactly this per patent:
  `cli/audit_patent_coverage.py` reports a status — `bindingdb` (dump hits), `chembl`
  (structured activities), `structured_supplement`, `chembl_document_only`, `absent` — with
  per-source counts and samples, plus a summary block.
- **Delivered scope.** A per-publication coverage report for a family/document and for an
  operator-supplied manifest: corpus occurrence counts, declared sets (per-publication
  lookup + target-led rows, kept apart), hand-added rows, and an explicit `not_queried`
  distinct from `asked_empty` and from `failed`; Markdown/CSV/JSON export for the operator
  and a collapsed strip in the patent view. Every status is re-derived from stored rows on
  read.
- **Not built, deliberately.** No snapshot leg (B-23 does not exist; the report's notes say
  so instead of carrying a dead column), no external call of any kind, no persisted verdict,
  no cross-leg totals, no new UI destination.
- **Acceptance sketch, met.** A family with mixed coverage yields a table whose every status
  is re-derivable from the database (checked against the live stack in
  `benchmarks/patent-coverage-2026-09-16.md`); a publication never checked reads
  `not_queried`, never `absent`.
- **Class NEXT · delivered · M (the B-23 leg remains open behind its own gate).**

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

### B-28 — Bounded multi-target snapshot run and change report

- **Evidence.** B-23 streams a whole snapshot for one target; the existing cohort
  script already loops targets. A repeated portfolio investigation is a plausible
  operator workflow, not yet a measured requirement for the invited beta.
- **User gain / scope.** Revisit a small named target set and see added, changed and
  withdrawn source records, with one snapshot pass where justified (`PROMPT.md`
  §2.5). Keep target/source/access-path outcomes separate; no scheduler or new service.
- **Dependencies.** B-30 must define trustworthy absence first; B-34 must identify the
  run. Establish repeated-batch volume and operator-file access before implementation.
- **Acceptance sketch.** Bounded multi-target results equal the corresponding single
  target results; a cancelled/partial scan reports partial progress and no false
  withdrawals; the diff carries both releases, queries and policies. Measure any
  scan-time improvement rather than assuming it.
- **Class LATER · P3 · M.** Now a ranked exploration, not an execution commitment.

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
- **Priority rationale.** Promote after the existing save/reopen and citation gaps
  (B-36/B-37): connecting an existing analysis to the selection it explains directly
  serves the saved-decision end of `PROMPT.md` §1/§2.5. Reuse the project view; do not
  introduce a report builder or team-sharing system.
- **Acceptance sketch.** Save a selection and its analysis reference, sign out/in,
  reopen both without a model call, and export with scope/policy/citations preserved.
  Owner isolation, stale analysis and unavailable referenced records remain explicit.
- **Class NEXT · P2 · M.**

### B-30 — A source refresh that retracts what its release no longer contains

- **Problem.** Migration 0015 already carries the columns and the intent ("a source refresh
  could not retract a mapping the new release no longer contains"), and B-06 established
  which rows each retrieval owns (`target_candidates` per (target, source, source_record_id),
  measurements keyed per investigation and source record). What nobody has built is the
  rule: after a **complete** source refresh, the rows of *that source* which the new payload
  does not contain are no longer current, and today they stay current, dated to when they
  were retrieved. A reader looking at a candidate list cannot tell a row the source still
  reports from one it dropped.
- **Why not part of B-06.** Absence is only established by a *complete* ask: a `failed` or
  bound-limited (`partial`) ask must retract nothing, or an outage becomes a deletion. The
  other half is the compound-level candidacy of `investigation_measurements` — retracting the
  last live candidate of a compound takes its measurements out of the investigation, which is
  correct but must be tested as such. That is its own round: rules, tests (failure does not
  retract, a re-delivered row comes back), a reported count, and the reason string each
  withdrawn row carries.
- **Scope decision first.** Define absence by target + source + access path + query /
  release coverage, not merely `status=complete` or `source_name`. B-23's REST and
  snapshot rows share `source_name=bindingdb` but have different record ids and assay
  keys (`benchmarks/bindingdb-snapshot-2026-09-16.md`); either path must preserve the
  other's rows. Decide explicitly when a complete-empty answer establishes absence.
  A complete bounded query is not a claim about a source's entire release.
- **Scope if built.** Retract only within the established coverage; record reason,
  release/query identity and count, never delete; clear retraction on re-delivery.
  Failed/partial asks and unasked targets establish no absence. Document-level corpus
  withdrawal (a package omitting an entire document) still requires an explicit release
  manifest and must not be inferred from the ordinary subset-package import.
- **Acceptance.** Pin no cross-target/source/access-path retraction, failed/partial
  preservation, complete-empty semantics and re-delivery. Candidate counts, verdict,
  exports and summary staleness must agree after a refresh. Identity rows stay intact.
- **Class CORE · P1 · M.** This maintains the truth of the current investigation
  (`PROMPT.md` §2.1), rather than adding another source.

### B-31 — Real hosted pilot acceptance

- **Evidence.** Capability §6 is still unchecked. The hosted-shape rehearsal records
  no real invited scientist and no independent scientific cross-read; its local TLS,
  restore and model results cannot close a real deployment's gate.
- **User gain / scope.** A scientist outside the implementation team can complete
  Search → evidence → interpretation → saved work/export on a known deployment
  (`PROMPT.md` §1/§2.5; AGENTS §3). This is the existing gate made visible, not new
  functionality or a new acceptance standard.
- **Gate / owner.** Operator supplies host/domain/TLS, provider/budget and participants.
  B-32 supplies the scientific evidence; B-34 binds new runs to their build. Preparation
  can be planned independently, but credentials, spending and review are not inferred.
- **Done evidence.** All capability §6 criteria linked to artifacts from the same
  deployed build: readiness, two-owner isolation, restore, resolved-target coverage,
  model smoke, latency/cost go/no-go, non-implementer walkthrough, scientific review
  and defect dispositions. Local rehearsals remain labelled separately.
- **Class CORE · P0 · M plus operator/participant time.**

### B-32 — Scientific cross-read and reproducible coverage cohorts

- **Evidence.** `scripts/cohort_coverage.py` joins source outcomes to the workspace's
  whole reference verdict, which can include supplements. The local cohort record
  reports TSLP 1/2 qualifying, while the isolated rehearsal reports 0/1; they describe
  different stored data, not conflicting measurements of an identical set. The
  rehearsal also lacks stored IL-6/IL-6R results. Existing model evaluation mostly
  checks output structure/citations; it does not establish scientific entailment.
- **User gain / scope.** Understand exactly what the retrieved set and its summary
  support (`PROMPT.md` §2.1). Define a small stratified public/synthetic review set:
  source-only versus supplemented workspaces, direct versus functional evidence,
  censor directions, stereochemistry, declared patents versus corpus occurrences,
  thin/empty/failed sources, and an unsupported summary claim. No private data import
  or new scientific fixture is authorized by this proposal.
- **Artifact contract.** Carry build identity (B-34), schema, resolved accessions,
  source/access-path/version, query bounds, policy, modality and supplement inclusion.
  Report source-only coverage separately from the combined workspace verdict, with
  denominators and unmatched/no-structure records explicit. Read verification
  parameters from the artifact rather than hard-coding another configuration.
- **Existing disclosure defect included.** `services/coverage.py::REPORT_NOTES` still
  says no BindingDB snapshot is configured in this build. B-23 exists, while B-26 has
  no dedicated snapshot leg. Make the report describe the actual access paths it can
  account for; never imply a snapshot hit is a corpus occurrence or a complete
  publication scan. Correcting this note does not add a patent-led snapshot lookup.
- **Done evidence / gate.** An independent reader checks sampled structure/stereo,
  assay/units/target assignment, occurrence and summary-claim support against original
  sources; record discrepancies, resolutions and limits. A machine can prepare the
  pack but cannot approve its own independent review. Small sealed fixtures and live
  observations remain distinct; publish no universal accuracy claim from this sample.
- **Class CORE · P1 · M plus reviewer time.** Feeds B-31; precedes catalog expansion.

### B-33 — Target screen/export filter and potency-policy parity

- **Evidence.** `App.tsx` sends `thresholdOverride` / `evidenceClassFilter` to candidate
  and measurement reads, but its target `ExportMenu` props and `ExportMenu.tsx`'s
  request omit both. The frontend export type also omits them. The backend
  `ExportRequest` accepts `activity_threshold_nm` and otherwise uses the deployment
  default; its export contract has no evidence-class filter. Static call-chain
  finding; downloads have not been reproduced in this planning round.
- **User gain / scope.** Take the current scientific selection to CSV/SDF with the same
  meaning (`PROMPT.md` §2.5; AGENTS §3/§11). Carry the active threshold, evidence class
  and modality through the existing typed export path; define how explicit selections
  outside a later filter are handled. Reuse the existing export control.
- **Done evidence.** Reproduce in a browser, then compare current-results and selection
  downloads at default and changed thresholds/evidence filters: same compound set,
  activity classes, policy and source records as the requested scope, across pages.
  Check CSV and SDF contents, empty/invalid input and bounds. A filename assertion
  alone does not prove this contract. No across-assay potency ranking is introduced.
- **Class CORE · P1 · S–M.** First engineering candidate: the file may currently lose
  the user's policy even when its download succeeds.

### B-34 — Distinguishable build identity in verification artifacts

- **Evidence.** `/healthz` exposes `api_version` from `__version__ = "0.1.0"`
  (`main.py`, `api/routes.py`, `__init__.py`); that cannot distinguish the many builds
  recorded under this version. Capability §6 asks for build identity, and the browser
  runner accepts any server at its configured URL.
- **User gain / scope.** Relate a reported result or defect to the version actually
  served (the reliability of the whole `PROMPT.md` §1 loop). Inject a revision/build
  identity at packaging time and carry it through health and run artifacts. Explicitly
  identify dirty or unknown builds; do not depend on a runtime `.git` directory.
- **Done evidence.** Two different builds are distinguishable; the recorder compares
  expected and served identities, reports a mismatch/unknown rather than passing it,
  and records schema/data/policy alongside them. Historical artifacts remain historical:
  do not backfill a guessed identity into them. No new service or user panel.
- **Class CORE · P1 · S.** Enables reliable new evidence for B-31/B-32/B-35/B-38.

### B-35 — Full PostgreSQL/RDKit suite and existing browser smoke in CI

- **Evidence.** B-14 runs `run_checks.sh --no-pg`: four test files plus `TestPlanner`,
  frontend typecheck/build. This is not every database-free test. B-17's one smoke is
  outside CI. The repo already builds the cartridge image in `docker/db/Dockerfile`;
  supplying a new external service is not a prerequisite.
- **User gain / scope.** Updates keep the patent/structure/evidence/export loop usable
  (`PROMPT.md` §1). Run the existing full backend check and existing smoke on a clean,
  isolated runner stack built from this checkout, with synthetic data and no paid calls.
  Measure runner cost/time; retain logs and failure traces. B-38 adds scenarios later.
- **Done evidence.** A hosted CI run actually executes the database suite and smoke;
  unavailable database/required browser fails rather than silently skips. Respect
  `SPAGO_REQUIRE_TEST_DATABASE` in the older 0006 upgrade helper too (currently it can
  skip unconditionally). Keep existing 0006/0008 upgrade tests; declare the supported
  upgrade starting point and check representative retrieval/supplement/retracted data
  as needed, rather than claiming there are no upgrade tests today.
- **Gate.** Runner Docker/build capability and time budget verified in that round.
  Fixture CI is not hosted user acceptance or live-provider validation.
- **Class CORE · P1 · M.** Extends B-14/B-17's delivered scope, not a rewrite of them.

### B-36 — Reopen every saved scope in a mixed project

- **Evidence.** `SaveCandidatesDialog.tsx` permits appending targets to an existing
  project. `App.tsx::openProject` picks the first usable item; the switcher enumerates
  families only, and the target project's banner has no scope switcher. Historical
  single-target reopening evidence does not cover a mixed project.
- **User gain / scope.** Recover every saved target/family without remembering the
  original searches (`PROMPT.md` §1 saved decision / §2.5). Extend the existing project
  affordance with explicit saved scopes, preserving identity/version snapshots and
  scoped selection. No permanent project dashboard.
- **Done evidence.** Save two targets plus one family, sign out/in and navigate all
  three; retain the correct saved items and visible missing/drift states. Cover an old
  response arriving after a scope switch, withdrawn candidates and owner isolation.
  Reproduce the current gap in a browser before choosing the smallest change.
- **Class CORE · P1 · M.**

### B-37 — Summary citation → exact supporting record

- **Evidence.** `AiPanel.tsx` passes `fact_ref`, but `EvidencePanel.tsx` generally
  switches tab/expands activity; `TargetEvidencePanel.tsx` has explicit source/verdict
  focus but otherwise only switches tab. `AnalysesDialog.tsx` renders citations as
  plain text. A cited measurement can belong to a candidate other than the selected one.
- **User gain / scope.** Check an explanation against its actual record in one action
  (`PROMPT.md` §2.1). Resolve typed refs through authorized read contracts, open the
  correct scope/compound/record in the existing evidence surface, and distinguish the
  saved snapshot from today's record. No provider call to reopen evidence.
- **Done evidence.** Family/document/target and archived summaries navigate citations
  to unselected and not-yet-loaded objects; exact supporting record is identified.
  Stale, retracted, missing and forbidden records give explicit outcomes rather than
  displaying unrelated current selection; older fetches cannot replace newer intent.
- **Class CORE · P1 · M.** Navigable citations are distinct from server validation that
  the cited identifier existed in the model's input.

### B-38 — Browser regression for failures, stale responses and saved work

- **Evidence.** The single smoke in `apps/web/e2e/smoke.spec.ts` tests a happy path and
  CSV filename. Prior manual rounds found bugs that unit tests missed; history-dialog
  empty/error cases remain unexercised in its recorded plan.
- **User gain / scope.** The same workflow stays trustworthy when a request fails or
  the scientist changes context (`PROMPT.md` §2.5). Add a few high-risk cases to the
  existing runner: slow A → fast B selection, unavailable versus empty source, subset
  retry retaining other sources, save/sign-in/reopen, and actual export contents.
- **Done evidence.** Loading/empty/error/stale states and recovery are observed with
  scoped visible controls; record viewport, served build, source mode and bounded route
  fault injection. Owner-isolation checks use a local auth-required shape. Fixtures and
  injected failures are labelled; they do not prove live-source behaviour or B-31.
- **Class NEXT · P2 · M.** Reuse B-17; B-35 can integrate the existing smoke first.

### B-39 — Reopen an investigation with its filters and policy

- **Evidence.** `state/url.ts` carries q/doc/c/t. `App.tsx` keeps modality, evidence
  filter and threshold override only in React state; refreshing returns those to their
  defaults. A saved selection is not a saved query definition.
- **User gain / first scope.** Return to the same target question and verdict settings
  (`PROMPT.md` §2.5; AGENTS §19). Persist a bounded validated set of target parameters
  in navigable or owner-scoped saved state. Choose storage deliberately; no SMILES,
  large result set or sensitive research payload in a URL.
- **Done evidence.** Refresh, Back/Forward and reopening preserve the same target,
  evidence class, modality and threshold; changed source data is labelled as a current
  re-evaluation, not an identical historical result. Invalid/older state has an explicit
  outcome. Structure-search snapshots are a later scope decision, not bundled here.
- **Class NEXT · P2 · M.** Depends on clear display/export semantics (B-33).

### B-40 — Small cross-family SAR comparison with assay comparability

- **Opportunity, not an observed defect.** `PROMPT.md` §2.4 promises eventual
  cross-patent interpretation; current structure search is family-scoped, and assay values remain
  separate. A chemist may need to compare a small saved shortlist without rebuilding
  its provenance in a spreadsheet.
- **Possible first scope.** An explicit shortlist from saved work, deterministic
  structure/scaffold alignment and side-by-side reported measurements with assay,
  target, unit and evidence. Mark incomparable assays; do not infer selectivity or rank
  mixed IC50/Ki/Kd values. Reuse existing tables/drawers; no global chemical-space map.
- **Gate / acceptance sketch.** A pilot supplies a concrete comparison question and
  comparable public examples; the reader can trace every compared value and understand
  why some pairs cannot be compared. Verify against that sample and measure bounded
  rendering/export cost. B-32/B-36/B-37 should come first.
- **Class LATER · P3 · M–L.** Differentiation worth exploring, not a general SAR engine.

### B-41 — Pick an exact publication from an ambiguous lookup

- **Evidence.** B-03 correctly refuses an ambiguous normalized number with 409 and
  names candidate documents; capability §8 mentions a future picker but no separately
  ranked item existed. The exact stored number already opens a chosen document.
- **User gain / possible scope.** Select a named candidate in the existing search
  result instead of retyping (`PROMPT.md` §1 Search → document). Display jurisdiction,
  kind code and available metadata; never auto-select or merge documents.
- **Gate / acceptance sketch.** Validate friction in the pilot before implementation;
  if justified, keyboard selection opens the exact chosen id and retains the match
  explanation. Zero/one/many and outdated candidates remain explicit.
- **Class LATER · P3 · S.** Lower than export/save/evidence defects with no workaround.

### B-42 — Candidate table collapses on short viewports

- **Evidence (browser-reproduced 2026-09-16, found during B-33's verification).**
  In the target view, `.table-panel` sits in the `workspace → table-area` flex
  column below TargetHeader, ReferenceStrip and the candidate filters. When that
  accumulated content exceeds the workspace height, flex shrink collapses
  `.table-panel` to ~32 px and `.table-scroll` to 0 — the virtual candidate table
  renders **zero rows** while its footer still reads "1–100 of 141" and the export
  menu still exports the full scope. Measured on the running stack at 1280×720
  (`table-scroll` clientHeight 0, 0 virtual rows); at 1600×1000 the same view
  lays out normally. The data is present; the layout hides it, and the counts
  around it make the empty area look like a loaded table.
- **User gain / scope.** The candidate table remains usable at common laptop
  viewports (`PROMPT.md` §1 loop; AGENTS §14's "structures are expensive UI
  objects" does not license a zero-height table). Likely a small layout fix —
  a minimum usable height for the table panel and a scroll strategy for the
  header content above it — not a redesign of the reviewed layout.
- **Acceptance sketch.** At a 1280×720 viewport the stored IL6 investigation
  renders candidate rows, selection checkboxes and the evidence inspector
  opening from a row; at 1600×1000 nothing regresses; the fix evidence records
  both viewports. The family view's table must not regress either.
- **Class CORE · P1 · S.** Ranked ahead of B-32/B-35 in the P1 group because it
  is small, browser-reproduced, and it silently hides the primary workflow's
  main object on screens a beta scientist plausibly uses.

## 3. Historical review — what the `BindingDB_IO` implementation changed (2026-09-16)

The comparison below describes the checkout **before** B-23…B-26 were delivered.
Its “SPAgo today” column is historical; current scope is in §1 and the capability page.

Read-only review of `/media/chen/Machine_Disk/Datasets/BindingDB_IO/` (README,
`AGENTS.md`, `task_plan.md`, `bindingdb_io/{readers/{tsv,lmdb,multi,api},web_supplement,patents,schema,activity,filters,dedupe}.py`,
`cli/{extract_target,audit_patent_coverage,apply_activity}.py`,
`docs/version_merge.md`, `examples/`). Nothing in that project was modified, and no code
was copied into SPAgo by this register.

| Source capability | Source evidence | SPAgo today (checked) | Verdict |
| --- | --- | --- | --- |
| Target → ligands over the local snapshots, one pass, several queries | `readers/multi.py`, `readers/tsv.py`, `readers/lmdb.py` | Bounded REST only (`adapters/bindingdb_rest.py`); DuckDB reads a fixture directory (`queries/bulk.py`) | **Adopted, TSV first** → B-23 (delivered 2026-09-16; LMDB deferred, one target per pass) |
| Patent → ligands over the same dumps and over supplements | `patents.py::{search_tsv_by_patents, search_lmdb_by_patents, search_supplements_by_patents}` | No patent-led local search | Fold into B-23 / B-26 |
| Patent → compounds via ChEMBL documents + activities | `readers/api.py::search_chembl_patent_api` | Target-led ChEMBL only; the document lookup serves declared patents of already-discovered compounds | **Adopt** → B-24 |
| Two snapshots of one source merged by a stated priority (newer wins, empties backfilled), keyed by reactant id with an InChIKey fallback | `dedupe.py`, `docs/version_merge.md` | Per-InChIKey union across *different* sources; no two-snapshot case exists yet | Adopt as the policy when B-23 lands |
| Web/literature supplement: mandatory note, refs, structure-less remarks, applied only when the set is empty or fails the gate | `web_supplement.py`, `extract_target.py` (`--web-only-if-empty`, `--web-if-no-active`) | One-row POST + dialog (ONLINE-07); no bundle, no prompt at gate failure | **Adopt** → B-25 |
| Per-patent coverage audit with named statuses and a summary | `cli/audit_patent_coverage.py`, `patents.py` | Ingredients stored, no report or view | **Adopted** → B-26 (delivered 2026-09-16) |
| Activity classes + screening-reference gate | `activity.py` | Already ported and extended (ONLINE-06; deterministic modality classifier, policy version travels) | **Done — do not re-import** |
| MW ≤ 1000 peptide filter | `filters.py` | Deliberately not used; modality classification decides instead | **Reject** (noise filter, not identity) |
| Real target names kept out of source; aliases via tempfile | `alias_io.py`, `BindingDB_IO/AGENTS.md` §Confidentiality | Target queries are runtime user input; the risk is committed fixtures and alias files | **Adopt as hygiene** → `AGENTS.md` §34 |
| XLSX export | `writers/export.py` | CSV/SDF | **Reject** (already decided) |
| Fixed-scale card sheet + lossless PDF + verifier | `figures.py`, `layout.py`, `pdfio.py`, `verify.py` | Browser depiction + CSV/SDF | **LATER** → B-27 |
| A verifier takes its parameters from the artifact it verifies | `verify.py` (dpi/bond/columns read back from `run_meta.json`) | Round records re-state their parameters by hand | **Adopt as a rule** → `AGENTS.md` §36 |

**Ordering argument.** B-24 went first among the new items: it is bounded, ungated,
uses a source the build already talks to, and it repairs a degradation in the primary
loop (enter a patent → see its compounds) that exists today whenever the corpus is
thin. B-25 was second because the supplement path is already shipped and the missing
piece is the shape its real producers use — without it, "agent + sources" stays manual
data entry. B-23 was third: the largest coverage gain, but operator- and file-gated, and
its value is local; it must not be mistaken for a beta capability. B-26 followed
because it is only as useful as the sources it summarizes (B-02, B-23, B-24). All four
of the first group have since been delivered (B-24, B-25, B-26 on 2026-09-16, B-23 on
2026-09-16 as an operator path); **the operator gate on B-23 is explicitly not closed
by that delivery** — the release's terms, the file's location and any run on another
release stay with the operator, and nothing in the port changes the recommendation to
pass the hosted gate first. None of the new items closes a `docs/online-capability.md`
§6 checkbox.

**What does *not* change.** The bounded-REST path stays the default for the hosted
deployment; the snapshots do not become a second source of truth; the potency gate,
modality rules and provenance states are reused rather than reimplemented; and the
rejected items above stay rejected — this review is an argument for four specific
ports, not for adopting the source project as a component (AGENTS §2, §6).

## 4. Historical delivery rationale

This section explains the completed queue; it is not the current order. The planning
review at `efb1357` replaces its old “next item” conclusions with §1 above.

1. **B-13** — *delivered 2026-09-16:* make the §6 gate cheaper to pass and harder to fake.
2. **B-01** — *delivered 2026-09-16:* make "search real patents" mean more than "search
   what was imported".
3. **B-10** — *delivered 2026-09-16:* let a scientist keep and find the analysis they
   already paid for.
4. **B-02** — *delivered 2026-09-16:* prove the patent-linkage claim on live data, and say
   exactly how far it reaches.
5. **B-24** — *delivered 2026-09-16:* make "enter a patent, see its compounds" survive a
   corpus that does not hold that patent.
6. **B-03** — *delivered 2026-09-16:* let the number a scientist actually types open the
   family it names.
7. **B-25** — *delivered 2026-09-16:* let a set of literature rows arrive as one reviewed
   artifact instead of one POST per row, with a proposal that is not evidence until a
   person confirms it.
8. **B-26** — *delivered 2026-09-16:* answer "what do we hold for this publication, from
   which leg, and what has nobody asked" in one read, without letting "never asked" pass
   for "no compounds".
9. **B-06** — *delivered 2026-09-16:* recover a failed source by re-asking that source, and
   only it — no other source's rate limit spent, no other source's rows re-dated.
10. **B-23** — *delivered 2026-09-16:* answer a target from the whole BindingDB release on
    the operator's disk, with the file's release, digest, rows scanned and match rule stored
    next to every row — and without a request, a rate limit or the network; a bounded scan
    is `partial` and records no digest, so a prefix can never read as the snapshot.
11. **B-15** — *delivered 2026-09-16:* send the editor's first open as one quarter of the
    bytes on the install a user actually has — the app compresses its own responses, so the
    win does not depend on a proxy the supported path never included.

**Why B-23 was promoted (2026-09-16), and what replaced it.** With B-06 landed, the
*recovery* gap was closed and the remaining cost of the online path became visible rather
than hidden: every target investigation still asks BindingDB over the network, once per
target. B-26's report named the missing snapshot leg in every row it printed, so the same
gap was legible from two surfaces. B-23 was therefore promoted to P1 with its operator gate
stated rather than lifted — the engineering could start, the gate closed the item — and it
was accepted on the operator's real 8.98 GB release on 2026-09-16
(`benchmarks/bindingdb-snapshot-2026-09-16.md`), with the gate still exactly where it was.
**Why B-15 was promoted, and what landed (2026-09-16).** It was ungated, `S–M`, and the
first Ketcher open was the one measured cost a beta user feels directly: 20.3 MB
uncompressed with no compression anywhere in the shipped container. Delivered as
in-process gzip (level 6) plus the re-measurement
(`benchmarks/asset-compression-2026-09-16.md`): **5,234,921 B instead of 20,269,580 B**
on that first open, entry JS+CSS 392,253 → 112,461 B, `/healthz` unaffected during cold
transfers. At that point **B-04** became the next engineering item and was subsequently
delivered. B-30 was then LATER; the current review promotes it because repeat retrieval
and multiple access paths now need an explicit current-state rule. Its design remains
a separate round, not an unfinished part of B-06.

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

Earlier rows preserve what was concluded at that time. The final row and §1 govern
the present proposal order; a previous “no remaining work” statement is not current.

| Date | Change |
| --- | --- |
| 2026-09-16 | Register created (planning-only stage). Items grounded by reading `PROMPT.md`, `AGENTS.md`, `docs/online-capability.md`, `docs/runbook.md`, the active plans, and the current checkout (`services/core`, `apps/web`, `scripts/`, `migrations/`). Owner request recorded: target-led open-database work (ChEMBL/BindingDB/PubChem) and LLM-summary archive/retrieval enter the backlog as B-06…B-09, B-07, B-08 and B-10. No code changed. |
| 2026-09-16 | Second planning-only stage. `BindingDB_IO` reviewed read-only; §3 added with the adopt/defer/reject argument; new items B-23 (local snapshot search), B-24 (patent-led ChEMBL compounds), B-25 (supplement bundle import), B-26 (patent coverage audit), B-27 (review sheet, LATER) and the B-28 note recorded; priority table and P2 order updated. `AGENTS.md` gained the snapshot, agent-retrieval, repository-hygiene and acceptance/verifier rules; `docs/online-capability.md` §6 gained the hosted-acceptance definition and success criteria. No application code changed. |
| 2026-09-16 | **B-13 delivered** after the hosted-acceptance rehearsal: `scripts/restore_check.sh` (scripted §H7 rehearsal; verified against the rehearsal stack and against a deliberate mismatch) and the §H2 "ingress duties" table (TLS, compression with the measured 20.3 MB → 4.95 MB figure, throttling, logs, backup schedule). The rehearsal also produced `docs/plans/2026-09-16-hosted-acceptance-rehearsal.md` and five defect fixes (target-summary bounds, rejected-call token accounting, transport-failure outcome, drill mode, §H7 column name). |
| 2026-09-16 | **B-01 delivered** (`scripts/corpus_batch.py`, `spago_core.corpus_status`, `GET /api/v1/corpus` + `CorpusDialog.tsx`). No re-sorting needed: the priority order below is unchanged, and B-10 is now the top P1 item. Two scope notes recorded: the batch loop is an operator-side chunker (no queue service, §6/§22), and the corpus counts are computed per request rather than maintained — the measured cost is in the plan file, and a corpus large enough to need counters is a measured problem, not a guess. |
| 2026-09-16 | **B-02 delivered** (`source_retrievals.reference_counts` + migration 0016, `spago_core/domain/document_refs.py`, the `--declarations` live measurement, and the target header's *Source notes and reference coverage* disclosure). Re-sorted: **B-24 is now the top P1 item**; B-02 leaves the table. The delivery answered the item's blocker with a live number instead of an assumption — 135 of IL6's 166 kept records carry a source-declared patent number, and EGFR's are 1,187 DOI-only plus 1,210 whose cited document the source does not return — and it surfaced a defect it did not set out to find: every retrieval's `warnings` (including "the lookup bound was reached") was persisted, served and rendered nowhere in the UI. Three scope notes: the tally is computed by the service over the records it kept, not by each adapter, so it means one thing for every source; a record already excluded for a missing structure or value is counted in `rejection_counts`, never in this tally; and no new dependency was added. |
| 2026-09-16 | **B-10 delivered** (`services/analyses.py`, `GET /api/v1/analyses`, `/analyses/{id}`, `/analyses/{id}/export`, `AnalysesDialog.tsx`). Re-sorted: **B-02 is now the top P1 item**; B-10 leaves the table. One new backlog item recorded from building it — **B-29** (attach a stored analysis to a project, and cite it from the project view), `LATER · M`: the capability statement already promises that saved work reopens, and an analysis is now an artifact a project can point at, but no reviewed workflow asks for it yet. |
| 2026-09-16 | **B-24 delivered** (`ChEMBLDiscoveryAdapter.declared_compounds`, `services/patent_sources.py`, migration 0017, the `source-compounds` read/lookup/export routes, `SourceDeclaredCompounds.tsx`, `scripts/patent_source_lookup.py`; live record in `benchmarks/patent-source-declarations-2026-09-16.md`). Re-sorted, with the moves stated: **B-03 is promoted to P1** — with the corpus no longer the only answer, the remaining primary-loop failure is the *entry*: `find_patent` matches the stored string exactly, and the search box classifies by a kind-code-shaped regex, so `wo 2020/123456` for a stored `WO-2020-123456-A` opens nothing. It is a day of work, ungated, and it feeds the same normalizer the patent-led path already uses. **B-26 moves ahead of B-23**: B-24 landed, so the audit's ChEMBL leg is content that exists today, while B-23 stays operator- and file-gated and is explicitly a workstation gain rather than a beta capability. B-24 leaves the table, and B-25 heads the P2 order unchanged. |
| 2026-09-16 | **B-03 delivered** (`looks_like_publication_number` + `MATCH_RULE`, exact-first `find_patent` with the one normalized comparison, `PatentLookup`/`AmbiguousError`/`PatentMatch`, the `match-note`, the mirrored client rule and the same rule in the plan path; `services/core/tests/test_b03_tolerant_lookup.py`, suite 595 → 643; `benchmarks/tolerant-lookup-2026-09-16.md`: exact 1.35 ms unchanged, tolerant 155 ms at 50 000 documents). Re-sorted, with the reason stated: the P1 group is empty, so **B-25 is promoted to P1** — the thin-target moment the §6 gate exercises ends in one-row-per-POST manual entry today, and B-25 is the control that offers the supplement in the shape the rows are produced in (§4 argues it). B-26 stays second and B-23 stays third with its operator/file gate unchanged. Two scope notes: the tolerant comparison runs **only** after the indexed miss (so the common case pays nothing) and it is a metadata scan, not a maintained normalized column — a second writer of the rule that can go stale silently was the alternative, and 155 ms at 50 000 documents did not buy it. The delivery also fixed a defect the browser found in B-24's panel (a string comparison of the requested number discarded a successful lookup for slash forms). |
| 2026-09-16 | **B-25 delivered** (`SupplementBundle` + the bundle service, migrations 0018/0019, the three `supplement-imports` routes, `unreviewed_supplements` on the verdict, `SupplementDialog`'s bundle pane, `ReferenceStrip`'s review control; `tests/test_b25_supplement_bundle.py`, suite 643 → 677; docs in `docs/online-capability.md` §3a, `README.md` and `docs/runbook.md` §2.5). Browser-verified end to end on the local stack, which found three defects the unit tests did not (the fresh report rendered twice, a re-posted remark not counted as an update, `repeated_of` not derived on read-back — all fixed in the round). Re-sorted, with the reason stated: the P1 group is empty again, so **B-26 is promoted to P1** — with four paths now contributing to a publication's coverage, nothing puts them side by side for one publication, and the gate's criterion 5 asks for exactly that shape at the target level. **B-06 stays second** (a single failed source still forces a full re-run; the status machine to do better already exists), B-23 third with its operator/file gate unchanged. |
| 2026-09-16 | **B-26 delivered** (the coverage service + `patent-coverage-v1`, `POST /api/v1/patents/coverage` and its three exports, `PublicationCoverage.tsx` — the collapsed *Coverage* strip in the patent view and on the 404 path — and `scripts/patent_coverage.py`; `tests/test_b26_coverage_audit.py`, suite 677 → 741; live record `benchmarks/patent-coverage-2026-09-16.{md,json}`). Re-sorted, with the moves stated: the P1 group is empty, so **B-06 is promoted to P1** — the audit gave every source outcome a surface, including `failed`, and what the beta workflow can still hit live is the recovery from a failed source, which today means re-running the whole investigation and re-spending the other sources' rate limits. It is ungated and S–M. **B-23 stays the first P2** with its gates unchanged, and B-15 moves down with them. Three notes recorded from the round: (1) `holds_records` was added to the report's `totals` so the strip reads the service's own headline count instead of re-deriving it (`AGENTS.md` §11); (2) the strip filters its publication list with the mirrored client shape rule before asking, because the synthetic fixture's ids are deliberately not publication numbers and a request carrying none of them is refused 422 — a refusal banner where a coverage line belongs would be worse than no strip; (3) the notes/export `<details>` is controlled state after the browser check found it snapping shut between opening it and clicking export (a DOM-owned marker reset by an unrelated re-render). |
| 2026-09-16 | **B-06 delivered** (asked-only persistence in `TargetDiscoveryService.investigate` + `DiscoveryReport.requested_sources`, `RetrievalResponse.requested_in_run`, the 422 refusal for a run that names no source, the target header's per-source **Retry** control on `failed`/`partial` chips with that source's own last-run cost and a run note naming the asked set, `tests/test_b06_per_source_rerun.py` 11 cases, record `benchmarks/per-source-rerun-2026-09-16.{md,json}`). The round found the defect sharper than the register had it: `investigate` wrote a `not_queried` row for every source it did **not** ask, and the retrieval id is one row per (target, source) — so a subset run **overwrote** the other sources' stored outcome while their candidate rows stayed in the database. A subset run now writes only what it produced, reports the rest from its stored row, and records `not_queried` only for a source that has never been asked. Measured: one retry = 1 upstream request for that source and **0** for the other two; only that source's retrieval row changes; its own candidate rows re-date (2 when it answers, 0 when it fails); measurements and verdict unchanged. Live browser check on two surfaces (IL6R's `bindingdb failed`, IL6's `pubchem partial`) — the other chips' stored outcomes, including `retrieved_at`, were identical afterwards; healthy chips offered no retry control. Re-sorted, with the moves stated: the P1 group is empty again, so **B-23 (local BindingDB snapshot search) takes the top** with its operator/file gate explicitly intact — its engineering is what is unblocked, and a retry without the network is what the beta's own cohort needs. **B-15 moves to the first P2**, and **B-30** joins the register as `LATER · M`: a *complete* refresh retracting rows its release no longer returns is an absence rule of its own (a `failed`/`partial` ask establishes none), so it was not folded into this round. |
| 2026-09-16 | **B-23 delivered** (`adapters/bindingdb_snapshot.py` — one streaming pass, stdlib only, with the file digest computed in the same read; `scripts/bindingdb_snapshot.py` as the operator entry point; `tests/test_b23_bindingdb_snapshot.py` 36 cases over a new synthetic fixture; acceptance on the operator's real 8.98 GB / 3,237,052-row release in `benchmarks/bindingdb-snapshot-2026-09-16.{md,json}`: 113.2 s, 153 kept records all matched by accession, 133 compounds, a `--max-rows` dry-run showing `partial` with no digest, and the stored REST set reconciling as a strict subset; `docs/runbook.md` §2.8, `docs/online-capability.md` §5, `README.md`, fixtures README, `THIRD_PARTY_NOTICES.md`). Two things the round found rather than planned: (1) the **retrieval upsert never rewrote `query`, `pages_fetched`, `source_version`, `dataset_version` or `checksum`**, so a source re-asked through another access path kept the first run's identity — the snapshot run left the row reading `bindingdb-rest` with a REST-only query while its own measurements said `bindingdb-snapshot-tsv`; fixed in `discovery._persist_retrieval`, pinned by a regression test, and corrected in B-06's record; (2) the access path was not visible in the target view at all, so the header's source line and chip tooltip now state it (`via bindingdb-snapshot-tsv (bindingdb-snapshot:2609)`), browser-verified on the rebuilt image. Re-sorted, with the moves stated: the P1 group is empty again, so **B-15 (compress served assets) takes the top** — it is ungated, `S–M`, and the first Ketcher open is the one measured cost a beta user feels directly, with the shipped container still serving assets uncompressed. **B-04 follows**, and **B-23 leaves the table as delivered with its operator gate explicitly intact**: the file's terms, its location and any run on another release remain the operator's, and nothing in this round closes a `docs/online-capability.md` §6 checkbox. |
| 2026-09-16 | **B-04 delivered** (migration 0020 `measurements.retracted_by_dataset_version` + both `m.*` views recreated, `seed.py`'s source-scoped restore-then-retract for the activity release with `SeedReport.retracted_measurements` reported in the import summary, `import_package.py`'s `resumed_jobs` naming the interrupted jobs whose package checksums the re-run re-imported, the read-path move to `current_measurements` in `bioactivity.py` / `ai.py` / `discovery.py`, the resume policy stated in `docs/runbook.md` §2 and README; `tests/test_b04_import_refresh.py` 6 cases, suite 773 → 779 all passing; plan `docs/plans/2026-09-16-import-refresh-completeness.md`). The round's findings beyond the item statement: (1) the reads were the bigger half — compound/family activity still read the `measurements` base table, so even the already-shipped hand-added withdraw kept rendering there; fixed and made a rule in `AGENTS.md` §10 (current-state reads go through the current-state views; a migration adding a column behind a `SELECT *` view recreates the view in the same change); (2) compounds need a *negative* decision, not code — identity rows are never retracted; the occurrences carry the absence, and the test pins that shape; (3) document-level absence stays unclaimed (B-30-class), stated in the runbook. No new dependency, no new service; EXPLAIN confirms the changed reads still use the existing partial index. Re-sorted, with the moves stated: **B-04 leaves the table**, and **B-14 takes the head** — its "repo hosting decision" gate is materially resolved by the checkout itself (`origin` is GitHub), so the minimal pipeline is a GitHub Actions workflow running the existing `scripts/run_checks.sh` in its `--no-pg` mode, with full database coverage staying where it is today (a machine with PostgreSQL + the RDKit cartridge) until someone provides a cartridge-bearing CI image. B-09 (scientific review), B-11 (provider choice), B-21/B-22 (source decisions + credentials + ADR) keep their operator gates and stay behind it; **B-17** is the next ungated engineering item after B-14. |
| 2026-09-16 | **B-18 delivered to the honest extent of this checkout** (the `verify-in-chrome.js` run now asserts `chrome.sidePanel.getPanelBehavior()` → `openPanelOnActionClick: true` in the running worker — previously a failed `setPanelBehavior` was only a silent `console.error`; the run was recorded on this workstation against the unbranded Playwright Chromium build, resolving the item's browser gate here; PROMPT.md, README and the architecture overview updated to the same wording). The physical toolbar click and the side-panel surface chrome stay uncovered, with the reason in the script: automating them needs OS-level input injection (no Xvfb/xdotool on this machine) or a keyboard-shortcut command added to the manifest for the test's own sake — a product change not made. No dependency, no application code changed. **B-18 leaves the table.** Re-sorted, with the moves stated: **B-17 (frontend test harness + one end-to-end smoke) is now the first ungated engineering item**; B-09/B-11/B-21/B-22 keep their operator gates. |
| 2026-09-16 | **B-14 delivered** (`.github/workflows/checks.yml`: push/PR pipeline calling `scripts/run_checks.sh --no-pg` — the developer entry point itself — with the shipped container's python 3.12 / node 22 and pip/npm caching; README's Development checks section updated). Verified by execution, not by reading: hosted run **35102219606 completed green in 1m07s** on ubuntu-latest. The gate question was argued in the register first: `origin` is GitHub, so GitHub Actions *is* the hosting decision, and a workflow file moving to another host later is a file move. Coverage limit stated in the workflow itself: the database-dependent majority of the suite keeps its scratch-database behaviour — CI does not run the full suite until someone provides a PostgreSQL+RDKit-cartridge CI image; the actions' Node-24 deprecation annotation is cosmetic. **B-14 leaves the table**, and the head moves to **B-09** (gated on scientific review) with **B-17 the first engineering-startable item**. An external register commit (`3f24d9b`, Cursor co-authored) landed mid-round adding B-15's two remaining record lines; its "B-04 becomes the next engineering item" statement predates B-04's delivery and is superseded by this log, not reverted. |
| 2026-09-16 | **B-17 delivered** (`@playwright/test` dev dependency with the §23 record and rejected alternatives in `THIRD_PARTY_NOTICES.md` §2 in the same change; `apps/web/playwright.config.ts`; `apps/web/e2e/smoke.spec.ts` covering search → family → compound inspection → structure filter → CSV export; `npm run test:e2e`; `test-results/` and `playwright-report/` git-ignored; README's Development checks updated). Verified by execution: the smoke passes in 1.6 s against the rebuilt compose stack (healthz ok, demo-fixture-v1) — a rebuild that also applied migration 0020 to the stack database — and `npm run build` still passes. Two scope notes from the run: (1) the spec's first draft assumed a row click opens a structure drawer; the real affordance is the evidence inspector, and the smoke follows the real UI — no application code changed; (2) the smoke is deliberately **not** wired into CI, because CI has no seeded stack; connecting them is its own later step. **B-17 leaves the table.** Final order after this round: the table's head is **B-09** (gated on scientific review); **B-11, B-21, B-22 keep operator gates** (provider choice; source decisions + credentials + ADRs); everything remaining is `LATER`-class with its gate named. No further engineering-startable item remains in the P2 group — the next move is the operator's (§6 hosted acceptance), or an ungated item must be added to the register first. |
| 2026-09-16 | **Planning-only product review at `efb1357`** ([Q&A](2026-09-16-product-review-qa.md)). Added B-31…B-41: hosted acceptance, scientific cohort/cross-read, target export parity, build identity, full CI, mixed-project navigation, precise citation navigation, browser failure regression, reproducible target state, bounded SAR comparison and ambiguity selection. B-33 is the first engineering candidate; B-31 remains the operator gate. Promoted B-30 to P1/CORE, B-19/B-29 to P2/NEXT; narrowed B-21 to a P2/NEXT source decision and deferred B-22 to P3; B-09 follows validation of the present cohort; split B-11's ungated explanation from gated provider evaluation; ranked B-28 as P3. Reasons and dependencies are in §1. Corrected stale handoff/capability/architecture claims; preserved historical artifacts and completed-item records. Static source inspection and document consistency only: no application changes, tests, builds, browser/source calls, acceptance execution, commit or push. |
| 2026-09-16 | **Implementation round 1 (owner-authorized queue).** Evidence refreshed first: full backend suite **779 passed**, frontend build, e2e smoke 1/1 — then **B-33 delivered** (browser reproduction on the stored IL6 investigation: menu claimed 141 / file 157 rows / threshold 10000 vs a 1 nM override; fix: `evidence_class` in the export contract + the screen's existence clause in `collect_candidate_export_rows`, threshold and filter passed from `App.tsx` through `ExportMenu`; 8 new tests, 104-test regression green; after-fix browser check 141 = 141 and `reference_threshold_nM` 1 for both scopes) and **B-34 delivered** (subagent implementation + coordinator review; the review caught the build script exporting an empty variable — fixed and proven by the served `/healthz` reading `12aa498-dirty` with the recorder exit 0). **B-42 added** (P1 head): short viewports collapse the candidate table to zero rendered rows while the footer claims 1–100 of 141 — measured, not guessed. Re-sorted with the moves stated: B-42 takes the P1 head (small, reproduced, hides the primary workflow's main object); B-33/B-34 leave the table; B-32's B-34 gate dependency resolves. AGENTS.md §11 gained the export-parity sentence (screen filters define the "current results" scope). |
