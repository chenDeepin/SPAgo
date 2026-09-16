# SPAgo capability and coverage — invited beta

Status: **invited staging**, 2026-09-15. This page states what the deployment
does, what it explicitly does not do, and which versions the claims were measured
against. It is a scope statement, not marketing: every "supported" line below has
a test or a recorded measurement behind it, and every "not supported" line is a
deliberate limit rather than an oversight.

Update this page whenever a capability or a source version changes. The
`Rollback` section at the end is part of the release, not an afterthought.

## 1. Frozen versions of this build

| Component | Version / identity |
| --- | --- |
| Application | build from this checkout; `/healthz` reports `api_version` |
| Database | PostgreSQL 15 + RDKit cartridge 4.2.0 |
| Schema | migrations 0001–0015 (forward-only) |
| UniProt | `rest.uniprot.org/uniprotkb/search` (REST, `uniprot-rest-uniprotkb`) |
| ChEMBL | `www.ebi.ac.uk/chembl/api/data` (`chembl-web-services`), including the bounded `document.json` lookup that supplies patent/DOI/PMID, with the activity response projected to the mapped fields |
| BindingDB | `bindingdb.org/rest/getLigandsByUniprot` (`bindingdb-rest`) |
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
- Compound tables with server-side paging (default 100, cap 500 rows per response).
- Exact, substructure and similarity structure search over the loaded corpus,
  executed server-side by RDKit; explicit similarity thresholds.
- Evidence inspection per compound: section, page, table/figure, local label,
  extraction method, provenance state, source link when the source supplies one.
- CSV/SDF export by family, document, structure query or explicit selection, with
  patent numbers, labels, evidence references and dataset versions attached.
- Target-candidate export, including candidates with no patent mapping.

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
- Save and reopen a candidate with no patent mapping; it keeps its target scope,
  source versions and identity snapshot.

## 4. Supported: interpretation, with limits

- Scoped summaries for a family, one document, or a target investigation.
  Each scope is labelled, cached separately and generated from stored facts only.
- Natural-language requests are turned into a **validated plan** against a fixed
  operation allowlist, shown for review, and executed only on explicit action.
- Deterministic identifier requests (publication numbers, reviewed target
  entities) work with no model configured at all.

## 5. Not supported (deliberate limits)

- **No claim of exhaustive or web-wide patent search.** Coverage is the loaded
  corpus plus the named open databases, each with its own recorded status.
- **No inhibitor guarantee for any target.** The measured coverage is what it is:
  see `benchmarks/cohort-coverage-2026-09-16.md` for the acceptance cohort
  re-recorded on this build (and `benchmarks/online00-coverage-2026-09-15.md` for
  the earlier run). For human TSLP, 110 of 111 qualifying ChEMBL activities are
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
  verdict reports it as withdrawn, and a source refresh follows the same rule. The
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
  the structure-search dialog only: the first open fetches 20.3 MB uncompressed
  (4.95 MB gzip) — the dialog chunk 7.8 MB, the Indigo engine a separate 11.8 MB
  `.wasm` (fetched inside its worker), plus a 444 KB chunk and the worker script.
  First paint is unaffected (entry bundle 320 KB raw / 93 KB gzip). Measured, not
  estimated: `benchmarks/online08-structure-editor-2026-09-16.md` — including the
  fact that the shipped container does **not** compress assets, so a slow connection
  pays the uncompressed figure until the deployment's proxy compresses it.
- **No full-document ingestion or OCSR.** Claims text and PDF chemistry are not
  in the pipeline; summaries say "claims were not assessed".
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
The run record names the build identity from `/healthz`.

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

Record the outcome per step, with the build identity from `/healthz` and the coverage
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
  so those fields are empty for BindingDB records (stated on the retrieval, not
  presented as the source's omission).
- **Assay construct is not part of the contract.** No adapter in this build can map
  a protein construct, so no construct field is declared and none is displayed: a
  construct described in prose by a source is not carried into SPAgo, which is a
  coverage limitation rather than something the reader should read as an empty
  column. ChEMBL's variant accession and mutation *are* mapped and shown when the
  source supplies them.
