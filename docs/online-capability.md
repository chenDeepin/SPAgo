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
| Schema | migrations 0001–0014 (forward-only) |
| UniProt | `rest.uniprot.org/uniprotkb/search` (REST, `uniprot-rest-uniprotkb`) |
| ChEMBL | `www.ebi.ac.uk/chembl/api/data` (`chembl-web-services`), including the bounded `document.json` lookup that supplies patent/DOI/PMID |
| BindingDB | `bindingdb.org/rest/getLigandsByUniprot` (`bindingdb-rest`) |
| PubChem | `pubchem.ncbi.nlm.nih.gov/rest/pug` (`pubchem-pug-rest`) |
| SureChEMBL | via versioned extraction packages (`dataset_version` per package) |
| Reviewed scope catalog | `services/core/spago_core/data/target_scopes.json`, reviewed 2026-09-15 |
| Plan schema | `search-plan-v1` |
| Potency policy | `potency-gate-v1` (threshold and scope travel with every verdict and export) |
| Prompt versions | `family-summary-v6`, `document-summary-v5`, `target-investigation-v8` (see `benchmarks/online01-llm-eval-2026-09-15.md`) |

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
  see `benchmarks/online00-coverage-2026-09-15.md`. For human TSLP, 110 of 111
  qualifying ChEMBL activities are peptides; IL-6R and CD40LG are thin.
- **A hand-added row is a person's statement, not evidence of record.** It is
  attributed to `user_curated` everywhere it appears (columns, exports, summaries)
  and never proves that the compound occurs in a document in SPAgo's corpus. The
  note is mandatory because the row's provenance cannot be reconstructed later, and
  a row that is not a potency (kinetic constant, percent readout, non-concentration
  unit) is classified `not a potency` rather than counted as active.
- **A hand-added row can be corrected, not deleted.** Re-posting the same row
  (same target, name, endpoint, value, unit, relation and document references)
  updates the stored row, and supplying a structure supersedes a structure-less
  remark for the same claim; withdrawing a row outright is not implemented, so a
  record once added stays visible until that path is designed (it needs its own
  decision about whether a removal keeps a trail).
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
- **No full-document ingestion or OCSR.** Claims text and PDF chemistry are not
  in the pipeline; summaries say "claims were not assessed".
- **No model credential or endpoint chosen by a user.** The endpoint comes from
  server configuration; request schemas reject extra fields.
- **No team sharing, public signup, SSO or password reset.** Invitations only.
- **PubChem BioAssay identifiers are screening context**, never measurements.
- **Molecular weight alone is not used as a modality classifier**; a source's
  `"Small molecule"` label is not trusted either (it is wrong for peptides).

## 6. Required before admitting users

- [ ] Host/domain chosen; HTTPS terminated; `SPAGO_COOKIE_SECURE=true`.
- [ ] `SPAGO_AUTH_MODE=required`, `SPAGO_SEED_MODE=none`, database listener private.
- [ ] Model endpoint, model id and monthly token budget recorded; both quota
      limits set to non-zero values.
- [ ] `SPAGO_ACTIVITY_THRESHOLD_NM` / `SPAGO_ACTIVITY_MIN_COMPOUNDS` reviewed and
      the chosen threshold recorded next to the acceptance coverage matrix.
- [ ] `/api/v1/readyz` reports `ready` with no notes.
- [ ] Backup taken and a restore verified per runbook §H7 (ownership counts match).
- [ ] Coverage matrix re-recorded for the acceptance targets on the deployed build.
- [ ] Invited cohort listed; invitation links issued individually.

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
  end in LLM mode in [record](plans/2026-09-15-llm-live-smoke.md) and again for the
  per-source citation chip in
  [plan](plans/2026-09-15-llm-eval-and-demo-open.md) §7.1). Any other endpoint the
  operator chooses is unverified, and an answer rejected twice in a row (one content
  re-sample is allowed) still fails as 502. Hosted acceptance still requires the
  operator's own smoke run.
- A summary's citations are validated against the exact snapshot sent, so a
  citation the model cannot express is refused rather than stored. The target
  scope's per-source retrievals therefore carry `source:<name>` refs; the residual
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
- BindingDB's REST path supplies no assay description, species or construct, so
  those context fields are empty for BindingDB records.
- **Assay construct is declared but never mapped.** No adapter fills
  `target_construct`, so `measurements.construct` is empty for every source and the
  evidence panel reads "context not provided" even where the source described a
  construct in prose. ChEMBL's variant accession and mutation are mapped separately
  and are shown when the source supplies them. Recorded as a limitation rather than
  printed as a source omission.
