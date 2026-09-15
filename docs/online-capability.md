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
| Schema | migrations 0001–0012 (forward-only) |
| UniProt | `rest.uniprot.org/uniprotkb/search` (REST, `uniprot-rest-uniprotkb`) |
| ChEMBL | `www.ebi.ac.uk/chembl/api/data` (`chembl-web-services`) |
| BindingDB | `bindingdb.org/rest/getLigandsByUniprot` (`bindingdb-rest`) |
| PubChem | `pubchem.ncbi.nlm.nih.gov/rest/pug` (`pubchem-pug-rest`) |
| SureChEMBL | via versioned extraction packages (`dataset_version` per package) |
| Reviewed scope catalog | `services/core/spago_core/data/target_scopes.json`, reviewed 2026-09-15 |
| Plan schema | `search-plan-v1` |
| Prompt versions | `family-summary-v6`, `document-summary-v5`, `target-investigation-v6` (see `benchmarks/online01-llm-eval-2026-09-15.md`) |

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
- **No potency ranking across assays.** Kd, Ki, IC50 and EC50 stay distinct; no
  selectivity numbers are computed.
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
