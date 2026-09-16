# SPAgo capability and coverage — invited beta

Status: **local implementation with historical verification; hosted acceptance open**.
Documentation reviewed at `efb1357` on 2026-09-16; no runtime checks were repeated in
this planning-only round. “Supported” below refers to the implemented scope with the
limits stated here, not an accepted hosted deployment. Tests, local browser records and
selected live-source measurements prove different things; §6 remains the release gate.
Current findings and proposed work: [product review](plans/2026-09-16-product-review-qa.md)
and [backlog](plans/backlog.md).

Update this page whenever a capability or a source version changes. The
`Rollback` section at the end is part of the release, not an afterthought.

## 1. Version contracts in the reviewed checkout

| Component | Version / identity |
| --- | --- |
| Application | reviewed checkout `efb1357`; `/healthz` currently reports package `api_version=0.1.0`, not a unique build identity (B-34) |
| Database | PostgreSQL 15 + RDKit cartridge 4.2.0 |
| Schema | migrations 0001–0020 present (forward-only); verify the deployed schema separately |
| UniProt | `rest.uniprot.org/uniprotkb/search` (REST, `uniprot-rest-uniprotkb`) |
| ChEMBL | `www.ebi.ac.uk/chembl/api/data` (`chembl-web-services`), including the bounded `document.json` lookup that supplies patent/DOI/PMID, with the activity response projected to the mapped fields |
| BindingDB | `bindingdb.org/rest/getLigandsByUniprot` (`bindingdb-rest`) |
| BindingDB operator snapshot | `bindingdb-snapshot-tsv`; release and completed-file digest per run; not a hosted HTTP capability |
| PubChem | `pubchem.ncbi.nlm.nih.gov/rest/pug` (`pubchem-pug-rest`) |
| SureChEMBL | via versioned extraction packages (`dataset_version` per package) |
| Reviewed scope catalog | `services/core/spago_core/data/target_scopes.json`, reviewed 2026-09-15 |
| Plan schema | `search-plan-v1` |
| Potency policy | `potency-gate-v1` (threshold and scope travel with every verdict and export) |
| Prompt versions | `family-summary-v6`, `document-summary-v5`, `target-investigation-v8` (see `benchmarks/online01-llm-eval-2026-09-15.md`) |
| Structure editor | Ketcher 3.18.0 (`ketcher-react` + `ketcher-standalone` + `ketcher-core`, all three pinned — see `THIRD_PARTY_NOTICES.md` § frontend) |

Source retrieval is timestamped per investigation; the exact query identifiers,
counts and outcomes are stored in `source_retrievals` and exportable via
`/api/v1/targets/coverage/matrix`.

## 2. Supported: search and inspection

- Patent lookup by publication number, with family, document and compound views.
- **Tolerant patent entry**: the number is accepted in the forms people actually write
  it (`WO2020123456A1`, `wo 2020/123456`, `US-5153197-A`, `US 10,123,456 B2`) — case,
  separators and the kind code do not matter — and the answer always names the stored
  identifier it matched, which is never rewritten to look like the request. A number the
  corpus does not hold stays a 404, free text is still routed to the ask box rather than
  turned into an identifier, and a form that names more than one stored document is
  refused with the candidates listed (409) instead of being silently resolved to one.
  This is the interactive lookup only: the loaded-corpus coverage report below stays an
  exact comparison, because "was *this* number imported?" must not be softened.
- Compound tables with server-side paging (default 100, cap 500 rows per response).
- Exact, substructure and similarity structure search within the selected loaded
  family/document scope, executed server-side by RDKit; explicit similarity thresholds.
- Evidence inspection per compound: section, page, table/figure, local label,
  extraction method, provenance state, source link when the source supplies one.
- CSV/SDF export by family, document, structure query or explicit selection, with
  patent numbers, labels, evidence references and dataset versions attached.
- Target-candidate export, including candidates with no patent mapping. The target UI
  currently omits its threshold override and evidence-class filter from the export
  request; parity with an actively filtered target view is not established (B-33, §8).
- **Loaded-corpus inventory** (`GET /api/v1/corpus`, and the same view behind the
  top-bar dataset badge): families, documents, compounds, mentions, evidence and
  measurements per dataset version, read from the corpus tables on the request,
  with failed/interrupted import jobs and per-row‑recorded versions named. It
  exists so "no result" can be distinguished from "never imported"; the operator
  side of growing that corpus is `scripts/corpus_batch.py` and
  `python -m spago_core.corpus_status` (runbook §2.1–2.2).

## 3. Supported: target-led investigation (OPEN databases)

- Target resolution from a gene symbol, protein name or UniProt accession, with
  alternatives and exclusions recorded rather than silently chosen.
- Reviewed ligand/receptor/pathway expansion for the acceptance systems, labelled
  as related rather than merged; no target-specific keyword rules.
- Bounded retrieval from ChEMBL, BindingDB and PubChem, each recorded separately
  as `complete`, `partial`, `empty`, `failed` or `not_queried`.
- Candidate compounds with deterministic modality classification
  (small molecule / peptide / oligonucleotide / biologic / unclassified) and the
  rule that decided each one.
- Measurements kept as reported, with assay context, an explicit evidence class,
  and duplicate flags for shared original references.
- **Potency classes and a screening-reference verdict** per target: every report is
  classified `active` / `weak` / `undecided` / `not a potency` against one explicit
  threshold (default 10 µM, configurable), with the censor direction honored
  (`<`, `>`) and micromolar/picomolar units converted before any comparison.
  The verdict is a deterministic count — how many in-scope compounds are at or
  below the threshold, how many are weak, undecided, or not potencies at all, and
  how many source records carried a value without a public structure — plus the
  policy that produced it (`potency-gate-v1`, threshold, modality scope).
- **Source-declared patent references.** ChEMBL's document record supplies the
  patent number (normalized), DOI and PMID for a discovered compound. Those are
  labelled *declared by the source* and kept in a separate column from a
  *corpus occurrence*, which is what SPAgo's patent linkage means.
- **Retrying one source rewrites that source and nothing else (B-06).** A retrieval
  whose ChEMBL call failed, or whose BindingDB ask stopped at a bound, is recovered by
  asking **that source alone**: `POST /api/v1/targets/discover` with
  `{"sources": ["bindingdb"]}`. Only the named sources are asked and only their stored
  retrieval is rewritten — rows, counts and `retrieved_at` of the sources that were not
  asked are left exactly as they were, so a retry cannot re-date, re-count or blank a
  healthy source's outcome, and cannot re-spend its rate limit. The response carries one
  row per source either way, with `requested_in_run` marking which this run asked; a
  source that has never been asked is still recorded as `not_queried`, which is a
  different fact from a failed or empty one. The control is offered in the target header
  only where the all-source refresh is the wrong tool (a `failed` or `partial` chip), and
  the cost shown before clicking is that source's own last run — pages, records seen and
  wall time — not an estimate. A run that names no source is refused (422). What a retry
  does **not** do: retract a row the source no longer returns (a failed or bounded ask
  establishes no absence, and deciding when a complete ask does is a separate item,
  register B-30), or rewrite a stored summary — the verdict is recomputed from the stored
  rows, and an analysis remains the snapshot it was.
- **How far that linkage actually reaches, per retrieval.** Each retrieval stores a
  disjoint tally over the records it kept — `patent_declared`, `doi_only`,
  `pmid_only`, and the reasons a reference is missing (`the document declares no
  identifier`, `the source row carried no reference`, `the source does not know the
  cited document`, `the lookup bound was reached first`, `the lookup failed`,
  `the record cites no document`) — shown in the target header's *Source notes and
  reference coverage* disclosure together with the retrieval's own notes. A bound or
  a lookup failure is reported as a fact about the retrieval, never rendered as
  "no patent". Measured live on 2026-09-16
  (`benchmarks/reference-declarations-2026-09-16.md`): 135 of IL6's 166 kept records
  carry a source-declared patent, TSLP's 111 carry only DOIs, and 1,210 of EGFR's
  2,397 cite a document the source does not return.
- **Hand-added literature rows per target.** A thin or empty retrieved set can be
  supplemented by hand from a paper or a patent. Each row carries a required note
  (its provenance), goes through the same RDKit normalization, modality
  classification and InChIKey identity as a retrieved structure, and is stored as
  `source_name='user_supplement'` / `provenance_state='user_curated'` with
  `evidence_class` unspecified — never merged into a source fact and never
  presented as a measured mechanism. A row with no public structure is kept as a
  **remark** with its as-reported potency (`target_supplement_remarks`), counted in
  the verdict as `supplement_remarks`, listed in the dialog, and never drawn,
  exported or counted as a compound; a row without a note is refused instead of
  receiving a generated one. Re-posting the same row updates it, and supplying a
  structure later supersedes the remark it replaces.
- **A hand-added row can be taken back, and the trail stays.** Withdrawal requires
  a reason, marks the row instead of deleting it, drops it out of every count
  (`withdrawn_supplements` in the verdict) and leaves it readable in the dialog's
  "taken back by you" list with that reason and time. If the withdrawal empties the
  compound's live rows for the target, the compound leaves the candidate list and
  the withdrawal says so. Re-adding the same row restores it — identity, not a copy.
- **A whole set of rows arrives as one artifact, and a proposal stays a proposal
  (B-25).** `POST /api/v1/targets/{id}/supplements/bundle` takes a
  `supplement-bundle-v1` JSON file: an envelope (`produced_by`, `produced_by_kind`,
  `searched`, optional `generated_at` and `uniprot`) plus up to 200 `records`. The
  envelope is required — a bare list of rows is refused — because it is the note
  AGENTS.md §12 asks of retrieved-and-transcribed material, and the producer's own
  kind decides what the rows are:
  `human` → `user_curated` on arrival, exactly like the one-row path; `agent` →
  `llm_inferred` and `external` → `machine_extracted`, stored, readable and counted
  as `unreviewed_supplements`, with **no `target_candidates` row**, so an
  unconfirmed proposal cannot move the verdict's counts, the candidate list, an
  export or a summary. `POST …/supplement-imports/{import_id}/confirm` is the one
  recorded act that flips those rows to `user_curated` and admits their live
  compounds (who and when are stored; confirming twice answers "already confirmed"
  rather than writing a second confirmation), and a row the reviewer rejects is
  taken back with the same mandatory-reason control.
  The run itself is stored (`supplement_imports`): the envelope, the counts, the
  per-row answers including every **refused** row and its reason, and the record ids
  the review works from. A row is refused rather than repaired when it contradicts
  itself (`value` and `ic50_nm` disagreeing, two endpoints for one number, a value
  that is not a number), when a stated `inchikey` disagrees with the structure SPAgo
  computed, or when a record carries no note — `reference`/`url` is carried into the
  note when present and never invented. `uniprot`, when the file states it, must
  match the target it is sent to or the whole bundle is refused. Re-importing the
  identical file is recognised as the same artifact (`repeated_of`), and a re-posted
  row is an update, never a duplicate. Provenance never downgrades: an agent's
  re-post cannot turn a person's row into a proposal.
- Save and reopen a candidate with no patent mapping; it keeps its target scope,
  source versions and identity snapshot. Historical verification covers the single
  target path; navigation among all scopes in a mixed project remains a gap (B-36).

## 3b. Supported: what a source declares for a publication (patent-led)

Target-led retrieval starts from a protein. The corpus starts from what was imported.
This path starts from a **patent publication number** and asks one source what it
declares under that number, whether or not SPAgo holds the family:

- **The corpus is no longer the only answer.** Requesting
  `POST /api/v1/patents/{publication_number}/source-compounds` runs a bounded ChEMBL
  lookup for the number as typed (`US-10508115-B2`, `US 10508115`, `US10508115B2` all
  normalize to one token). This is the case the panel exists for: a publication that
  was never imported, or imported thinly, still reaches a declared compound set.
- **The match rule is stated and versioned.** `chembl-document-patent-body-v1`: the
  source's `document.patent_id` normalizes to the same country-plus-digits token
  (kind code and separators ignored). The rule travels with every response, every row
  and every export, so "the source declares nothing" is readable as a statement about
  *this source under this rule* rather than about the patent. A document the body
  search returns under a **different** number is a **near match**: listed with its
  number and excluded — never merged, never silently dropped.
- **Five states, kept apart.** `complete`, `partial` (a document or activity bound was
  reached), `empty` (asked; the source knows no such document), `failed` (could not be
  asked) and `not_queried` (nobody asked). A failed lookup keeps the rows from the last
  successful retrieval and says which retrieval they came from; it never reads as
  "nothing declared".
- **A declaration is not an occurrence** (AGENTS.md §11). The set is stored in its own
  tables (`patent_source_lookups`, `patent_source_compounds`), its compounds share the
  corpus identity by InChIKey, and **no `compound_mentions` row is written**: a lookup
  does not change a family's compound count, does not enter the compound table, and is
  never presented as evidence. The panel is a separate surface with its own vocabulary
  ("declared", the rule, the retrieval time).
- **What was thrown away is reported.** Records are kept when they carry a structure
  and a numeric value; the rest are counted by reason (`missing_structure`,
  `missing_standard_value`, …). Live on `US10508115`, 268 of 402 records are the
  document's kinetic rows and are counted, not dropped.
- **Potency is computed on read, under the same policy as everywhere else.**
  `activity_class` / `potency_label` come from `potency-gate-v1` on each read, with
  `reference_threshold_nM` and `reference_policy_version` on the response and in the
  export. No ranking is implied; the patent path claims no `evidence_class` (it does not
  resolve the assayed biological object), and it says so.
- **Export carries what it holds.** `GET .../source-compounds/export?format=csv|sdf`
  writes the whole stored set (not the loaded page); every row is labelled
  `record_kind = source_declared_compound` with the source, its version, the match rule,
  the retrieval time, the policy and the declared document number. Exporting a set that
  was never looked up, or an empty one, is refused with the reason instead of writing an
  empty file.
- **Operator path without a browser:** `scripts/patent_source_lookup.py --patents …`
  runs the same service call against a database and prints/records the view; the live
  record is [`benchmarks/patent-source-declarations-2026-09-16.md`](../benchmarks/patent-source-declarations-2026-09-16.md).

What this is not: a completeness claim for a publication (one source, one rule), a
resolution-rate claim over a cohort, or a corpus occurrence. See *Not supported*.

## 3c. Supported: what is stored for a publication, and what nobody asked (B-26)

The three paths above can each contribute chemistry to one publication, and nothing
put them side by side: a reader could conclude "this patent has no compounds" from a
compound table that only ever showed the imported corpus. `POST /api/v1/patents/coverage`
takes up to 50 publication numbers and answers, per publication, what SPAgo holds, from
which leg, and which leg nobody has asked:

- **Three legs, never summed.** `corpus` (live compound mentions of an imported
  document), `declared` (a stored B-24 lookup, plus B-02's target-led rows for the same
  number) and `supplement` (hand-added rows citing it). Each carries its own state and
  counts. A declared compound is not an occurrence and a hand-added row is not evidence
  (`AGENTS.md` §10/§11), so the report has no cross-leg total — counting them together
  would be the exact confusion the surface exists to prevent.
- **`not_queried` is not `empty`** (the rule's whole point). A leg nobody asked is
  reported as never asked, with the row naming which legs were never asked and could
  still add records; `asked_empty` means a source was asked and answered nothing.
  `patent-coverage-v1` is the versioned rule and it travels with every row, every
  summary and the export.
- **Read-only, on read, no external call.** Every leg is a stored-row read, so the audit
  needs no user action and spends no rate limit — unlike the B-24 lookup it summarizes.
  Nothing is persisted: a later retrieval or import cannot leave a stale status behind
  (`AGENTS.md` §11), and the surface has no verdict to invalidate.
- **Four states of "an answer that did not resolve", kept apart.** `corpus` / `declared`
  / `supplement` / `proposed` name a leg that holds records; `empty`, `failed` and
  `not_queried` are the absence of an answer, and a failed ask says so in the row's
  reason rather than reading as a complete answer.
- **Ambiguity is reported, not guessed.** A number matching two stored documents lists
  both identifiers on the row rather than choosing between them, following `find_patent`.
- **Coverage limits.** The corpus leg can only report documents SPAgo imported (the
  true sibling set needs a bibliographic source, B-22). B-23's target-led snapshot tool
  exists, but this audit has no dedicated snapshot leg or patent-led snapshot scan.
  Its fixed runtime note saying the build has no configured snapshot is stale and
  tracked in B-32; this documentation correction does not change that output.
  `not_queried` is never an absent verdict.
- **Two surfaces, one rule.** The patent view's *Coverage* strip (collapsed to one line,
  on the family view and on the 404 "the corpus does not hold it" path, where coverage is
  the question the reader actually has) and `scripts/patent_coverage.py` for an operator
  auditing a portfolio file against the database, with Markdown/CSV export from both.

What this is not: a statement about a patent's true content, a completeness claim for a
family's publication set, or a substitute for asking a source. See *Not supported*.

## 4. Supported: interpretation, with limits

- Scoped summaries for a family, one document, or a target investigation.
  Each scope is labelled, cached separately and generated from stored facts only.
- **Stored analyses are readable again** (`GET /api/v1/analyses`, the top-bar
  **Analyses** dialog, and a Markdown export per analysis): the owner's own
  summaries with their scope, model, prompt version, data version and billed
  tokens. Reopening one is a read — no provider call — and an entry whose data or
  potency policy has moved since is shown as out of date, with the reason, rather
  than presented as current.
- Natural-language requests are turned into a **validated plan** against a fixed
  operation allowlist, shown for review, and executed only on explicit action.
- Deterministic identifier requests (publication numbers, reviewed target
  entities) work with no model configured at all.
- Citation validation checks the stored input reference. Exact navigation from every
  citation to its supporting record is not complete: several active callbacks only
  change tabs, and archived-analysis citations are text (B-37).

## 5. Not supported (deliberate limits)

- **No claim of exhaustive or web-wide patent search.** Coverage is the loaded
  corpus plus the named open databases, each with its own recorded status.
- **No inhibitor guarantee for any target.** The measured coverage is what it is:
  see `benchmarks/cohort-coverage-2026-09-16.md` for the acceptance cohort
  recorded on that local run (and `benchmarks/online00-coverage-2026-09-15.md` for
  the earlier run). These are dated observations, not a live coverage guarantee.
  The local workspace includes supplements; the isolated `*-accept` cohort uses
  different stored data and lacks IL-6/IL-6R. Its TSLP verdict is 0/1 while the local
  workspace's is 1/2; neither is a substitute for a source-only baseline (B-32).
  In the recorded source retrieval, 110 of 111 qualifying ChEMBL activities are
  peptides and one genuine small molecule remains; **IL-6R is the thin one** (one
  in-scope compound whose only record is not a potency, and BindingDB failed for
  it); IL-6 and CD40LG do reach the policy's minimum (`potency-gate-v1`: IL-6 124
  of 144 in-scope compounds at or below 10 µM, CD40LG 6 of 10).
- **A hand-added row is a person's statement, not evidence of record.** It is
  attributed to `user_curated` everywhere it appears (columns, exports, summaries)
  and never proves that the compound occurs in a document in SPAgo's corpus. The
  note is mandatory because the row's provenance cannot be reconstructed later, and
  a row that is not a potency (kinetic constant, percent readout, non-concentration
  unit) is classified `not a potency` rather than counted as active.
- **A hand-added row is corrected or withdrawn, never deleted.** Re-posting the
  same row (same target, name, endpoint, value, unit, relation and document
  references) updates the stored row, and supplying a structure supersedes a
  structure-less remark for the same claim. Taking a row back is a recorded
  retraction with a required reason, not a deletion: the row stays readable, the
  verdict reports it as withdrawn. B-04 applies recorded retraction within its corpus
  package / complete activity-release scope; missing rows after online investigation
  retries are not yet retracted (B-30). The
  UI has no physical delete, so no count changes without a reason on the row.
- **The reference verdict is a count, not a biological conclusion.** "2 of 3
  in-scope compounds at or below 10 µM" states what the retrieved records support
  under the stated policy. It is not a claim about the literature, not an
  inhibitor count, and not a measure of target druggability. A thin set is never
  reported as a negative result: values without a public structure — from a source
  or added by hand — are counted and shown next to the verdict.
- **No potency ranking across assays.** Kd, Ki, IC50 and EC50 stay distinct; no
  selectivity numbers are computed. The class of a compound is decided from its
  own records, and per-endpoint counts are reported rather than a single number.
- **No legal conclusions.** Nothing here is legal advice, freedom-to-operate
  analysis, or a statement about claim scope.
- **No full Markush analysis.** R-group handling is not implemented.
- **The structure editor loads on demand and is large.** Ketcher (3.18.0) ships in
  the structure-search dialog only: the first open fetches 5.2 MB (20.3 MB decoded) —
  the dialog chunk 7.8 MB, the Indigo engine a separate 11.8 MB `.wasm` (fetched
  inside its worker), plus a 444 KB chunk and the worker script. First paint is
  unaffected (entry bundle 320 KB raw / 107 KB gzip). Measured, not estimated:
  `benchmarks/asset-compression-2026-09-16.md` — the app compresses its own responses
  (gzip, level 6, in the app container), so the figure holds on `docker compose up`
  without a proxy; an ingress may still add brotli.
- **No full-document ingestion or OCSR.** Claims text and PDF chemistry are not
  in the pipeline; summaries say "claims were not assessed".
- **The local BindingDB snapshot path is operator-only and not part of the hosted
  beta.** `scripts/bindingdb_snapshot.py` answers a target from an operator-supplied
  release file (8.9 GB in the measured case) against the database directly. The
  hosted app keeps the REST adapter; no HTTP request can trigger a bulk-file scan
  (`AGENTS.md` §21), and the file itself stays outside the repository (§34). What it
  buys is a workstation gain: the whole release instead of the endpoint's bounded
  answer, with the target organism, the chain count and the document the source
  states, and the file's release/digest recorded on the retrieval and on every
  measurement row. It is not a hosted-user capability, and its rows are
  `database_curated` facts about that file — never a corpus occurrence and never a
  patent-coverage claim. Measured shape:
  `benchmarks/bindingdb-snapshot-2026-09-16.md`.
- **No model credential or endpoint chosen by a user.** The endpoint comes from
  server configuration; request schemas reject extra fields.
- **No team sharing, public signup, SSO or password reset.** Invitations only.
- **PubChem BioAssay identifiers are screening context**, never measurements.
- **Molecular weight alone is not used as a modality classifier**; a source's
  `"Small molecule"` label is not trusted either (it is wrong for peptides).

## 6. Required before admitting users

This section is the gate: this checklist and the script below are what a new
deployment must satisfy. The dated register of what one earlier round did and did not
verify is kept as history in `docs/archive/2026-09-15-beta-acceptance.md` — it records a
past run, it does not replace this list.

**What hosted acceptance is.** Hosted acceptance is the deliberate decision that a
*deployed* build may be handed to invited external users. It has two halves that must
both hold: the operator checklist below (configuration, readiness, restore, model smoke,
coverage, budget) and the invited-user script further down, executed by a person who did
not implement the application, using only the browser, in one sitting. A run on the
local compose stack is a **rehearsal**: it proves the workflow, not the deployment.
Nothing else — a green test suite, a working demo, a passed review — substitutes for it.

- [ ] Host/domain chosen; HTTPS terminated; `SPAGO_COOKIE_SECURE=true`.
- [ ] `SPAGO_AUTH_MODE=required`, `SPAGO_SEED_MODE=none`, database listener private.
- [ ] Model endpoint, model id and monthly token budget recorded; both quota
      limits set to non-zero values.
- [ ] `SPAGO_ACTIVITY_THRESHOLD_NM` / `SPAGO_ACTIVITY_MIN_COMPOUNDS` reviewed and
      the chosen threshold recorded next to the acceptance coverage matrix.
- [ ] `/api/v1/readyz` reports `ready` with no notes.
- [ ] Backup taken and a restore verified per runbook §H7 (ownership counts match).
- [ ] Coverage matrix re-recorded for the acceptance targets on the deployed build
      (`scripts/cohort_coverage.py`; last local record:
      `benchmarks/cohort-coverage-2026-09-16.md`).
- [ ] Invited cohort listed; invitation links issued individually.
- [ ] One real model provider smoke-tested from the deployed build (model id,
      endpoint fingerprint, per-scope call, token usage, latency, failure rate,
      cache behaviour); any other endpoint stays unverified.
- [ ] An invited user — not the implementer — completed the script below, and any
      defect they reported was answered before the beta is called usable.
- [ ] Independent scientific cross-reading of retrieved structures,
      stereochemistry and occurrence fields against the original sources.
- [ ] Latency and cost targets for the chosen host and model defined, then
      measured for a go/no-go.

### Success criteria

All of the following must hold, each closed by an artifact rather than an assertion —
a checked box without the output, report or record that produced it is not evidence.
The run record includes `/healthz` and the actual revision/image identity. Currently
`api_version=0.1.0` alone cannot identify a build; record the packaging identity
separately until B-34 supplies a comparable served identity. Do not infer that a
server matches a checkout merely because their API versions agree.

1. **Deployment shape is the reviewed one.** HTTPS terminates in front of the app;
   `SPAGO_COOKIE_SECURE=true`; `SPAGO_AUTH_MODE=required`; `SPAGO_SEED_MODE=none`; a
   connection attempt to the database port from outside fails.
2. **Readiness is clean.** `/api/v1/readyz` returns `ready` with an empty `notes`
   array, and `/healthz` reports the recorded `api_version`.
3. **Budget is bounded and known.** Model endpoint, model id and monthly token budget
   are recorded; both quota limits are non-zero; `/api/v1/usage` accounting works;
   the operator's latency/cost targets (§H9) are filled in *and* measured — a go/no-go
   decision is written down.
4. **One provider is real from this host.** The model smoke (per scope: family,
   document, target) is recorded with model id, endpoint fingerprint, token usage,
   latency, failure rate and cache behaviour. Other endpoints stay unverified.
5. **Coverage is re-recorded on this build.** The acceptance-target matrix is produced
   by `scripts/cohort_coverage.py` on the deployed build, with the chosen potency
   threshold recorded next to it and every source's outcome explicit (`complete` /
   `partial` / `empty` / `failed` / `not_queried`).
6. **Restore is rehearsed.** A backup is taken and restored per §H7 with ownership
   counts matching (`scripts/restore_check.sh` performs and checks exactly this); the
   rehearsal result is part of the run record.
7. **Isolation is verified.** With two accounts, one owner cannot see the other's
   projects.
8. **A non-implementer completes the script.** The invited user finishes all eight
   steps in one sitting; every defect they report is fixed or recorded with an owner
   and a decision before the beta is called usable.
9. **The chemistry has been read by a human.** An independent reader checks retrieved
   structures, stereochemistry and occurrence fields against the original sources;
   discrepancies are recorded and either fixed or accepted as documented limitations.

### What a pass does not prove

State these limits whenever the acceptance run is quoted:

- **Not scientific truth.** A valid schema and a valid citation are not correctness;
  only the items in the cross-read sample were checked by a human.
- **Not general provider compatibility.** One endpoint, host and model were tested.
- **Not coverage completeness.** Thin coverage for a target stays a coverage fact, not
  a negative result, and no source is claimed to be exhaustive.
- **Not a legal or druggability conclusion.** The reference verdict remains a count
  under a stated policy.
- **Not the unsupported capabilities.** Multi-worker operation and everything listed
  in §5 remain unsupported regardless of the run.

### If a criterion fails

Record the failure in the active plan with its owner, impact and date; fix it and
re-run the affected criterion — or narrow the invited cohort and add the limitation to
§5 of this page. An unchecked box is a fail, and no failure is closed by editing the
box; it is closed by the artifact that shows the criterion now holds.

### Acceptance script for the invited-beta run

A scientist using only the browser must be able to complete, in one sitting:

1. Open the invitation link, sign in.
2. Resolve a requested target (TSLP, CD40L, IL-6, IL-6R, or another) and read
   the scope: what was resolved, what was excluded, which partners are related.
   `IL-6` and `IL-6R` resolve **ambiguously** by gene symbol and need the
   accession (`P05231`, `P08887`) — record which entry the run selected.
3. Run a supported natural-language request (review the plan, then Run) **or**
   use manual search/structure search.
4. Read the per-source coverage and distinguish small-molecule from
   peptide/biologic evidence, and direct binding from functional/interaction
   evidence.
5. Inspect a candidate's structures and assay evidence, and the patent linkage
   status (including a candidate that has none).
6. Generate a scoped, cited summary and check at least one citation against the
   underlying record.
7. Save the selection, sign out, sign in again, reopen the project, and export.
8. Report any defect before the beta is called usable.

Record the outcome per step, with `/healthz`, the revision/image identity and the coverage
matrix for the run. A run against the local stack is a rehearsal, not this gate: it
proves the workflow, not the deployment.

## 7. Rollback

The deployment is one app image plus one database. To roll back:

1. **Stop serving** to invited users (the reverse proxy is the switch).
2. **Restore** the most recent verified dump into a fresh database per runbook
   §H7, or redeploy the previous image tag if the schema did not change.
3. **Check the schema version** after rollback:
   `SELECT max(version) FROM schema_migrations;` — migrations are forward-only, so
   an older image against a newer schema is unsupported. If migrations advanced,
   restore the matching dump instead of downgrading the image.
4. **Verify** `/healthz`, `/api/v1/readyz` and one owned-project read before
   re-admitting users.
5. **Record** what happened in the active plan: who was affected, for how long,
   and whether any analysis or saved item was lost.

## 8. Known gaps carried forward

- LLM summary quality, latency, token usage, failure rate and cache behaviour are
  measured for **one** provider (DeepSeek `deepseek-flash`, 2026-09-15:
  `benchmarks/online01-llm-eval-2026-09-15.md` — 45 recorded requests over four
  runs, per-call compliance and refusal classes; browser AI panel verified end to
  end in LLM mode in [record](archive/2026-09-15-llm-live-smoke.md) and again for the
  per-source citation chip in
  [record](archive/2026-09-15-llm-eval-and-demo-open.md) §7.1). Any other endpoint the
  operator chooses is unverified, and an answer rejected twice in a row (one content
  re-sample is allowed) still fails as 502. Hosted acceptance still requires the
  operator's own smoke run.
- A summary's citations are validated against the exact snapshot sent, so a
  citation the model cannot express is refused rather than stored. The target
  scope's per-source retrievals therefore carry `source:<name>` refs, and the
  potency verdict carries `reference:<target-id>` — a ref the shipped prompt
  requires the model to use, which the validator did not allow until the sparse-scope
  run exposed it (0/2 answered before, 2/2 after:
  `benchmarks/online01-llm-eval-2026-09-16-sparse.md`). The residual
  class is a ref written *without* its namespace (`facce3fd-…` instead of
  `document:facce3fd-…`), which is refused — deliberately, since a bare UUID does
  not say whether it names a document, an evidence record or a candidate.
- Multi-worker deployments are unsupported: the in-flight model-call registry is
  per process.
- The `open_patent` plan step cannot be exercised against the synthetic demo
  fixture, whose identifiers are intentionally not publication-number shaped. The
  landing and 404 hints therefore carry an explicit control ("open
  `DEMO-PATENT-A`") that opens the sample record through the same server lookup as
  a search; the search box still classifies free text for the offline planner, and
  the planner is not allowed to turn text into an identifier (AGENTS.md §12).
- PubChem contributes screening context only; a CID→AID measurement path is not
  implemented (it would require unbounded BioAssay harvesting).
- BindingDB's REST path supplies no assay description, species or variant context,
  so those fields are empty for that access path (stated on the retrieval, not
  presented as a property of every BindingDB record). The operator snapshot can
  retain organism and chain context; its coverage must be identified separately.
- **Assay construct is not part of the contract.** No adapter in this build can map
  a protein construct, so no construct field is declared and none is displayed: a
  construct described in prose by a source is not carried into SPAgo, which is a
  coverage limitation rather than something the reader should read as an empty
  column. ChEMBL's variant accession and mutation *are* mapped and shown when the
  source supplies them.
- **A number that names more than one stored document cannot be opened by that form.**
  When the corpus holds, say, both `US-8618102-B1` and `US8618102B2`, the tolerant
  lookup answers 409 and lists both instead of choosing; the reader opens one by its
  stored number. A candidate picker is backlog B-41 (`LATER`), not a shipped
  control, because nothing reviewed asks for it yet. The same tolerant path costs a
  full metadata scan when the indexed lookup misses — measured at 155 ms on a
  50 000-document corpus (`benchmarks/tolerant-lookup-2026-09-16.md`) — which is why
  it runs only after the exact miss and is unmeasured above that corpus size.
- **Target display/export parity (B-33).** Static inspection finds that the browser
  does not send the active target threshold or evidence filter to export. The backend
  supports an explicit threshold but otherwise uses the deployment default, and has
  no export evidence-class parameter. Browser reproduction is still required; do not
  claim a filtered target view and its downloaded artifact have identical semantics.
- **Saved-work continuity (B-36/B-39).** Mixed projects can hold several targets and
  families, but reopening selects the first usable item and the existing switcher
  covers families only. Target modality/evidence/threshold controls are not restored
  from the URL. These static findings are distinct from the verified single-scope paths.
- **Regression scope (B-35/B-38).** CI executes a selected non-database subset and
  frontend typecheck/build; the full PostgreSQL/RDKit suite and browser smoke are not
  in CI. One recorded successful browser smoke does not cover failed sources, late
  responses, auth-required persistence or export-content parity.
