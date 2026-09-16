# Porting the BindingDB_IO target-vs-ligand process into SPAgo — next-round plan

Date: 2026-09-15. Baseline: working tree of this checkout (ONLINE-00…05 uncommitted,
per `PROMPT.md`). Source reviewed: `/media/chen/Machine_Disk/Datasets/BindingDB_IO/`
(read-only; nothing in that project was modified).

Status: **plan**. The "Implementation record" section at the end is filled in after
the work is done, so this file is both the pre-work plan and the post-work record
(user workflow rule 5).

---

## 1. What the source project actually does (review)

`BindingDB_IO` is a single-target-at-a-time *target → ligand* extractor for BindingDB
with a documented research process. Read in full: `README.md`, `AGENTS.md`,
`task_plan.md`, `bindingdb_io/{activity,filters,dedupe,patents,web_supplement,schema,
match,targets,organism,summary,figures}.py`, `bindingdb_io/readers/{api,multi,tsv}.py`,
`cli/{extract_target,apply_activity,audit_patent_coverage,verify_run}.py`, and the run
artifacts under `outputs/2026-09-15/`.

The process, in the order the project enforces it:

| # | Step | Where it is encoded | Why it exists |
| --- | --- | --- | --- |
| 1 | Resolve the query to source-side identifiers (aliases, UniProt accessions) | `targets.py`, `match.py`, `alias_io.py` | The query a scientist types is not a source key |
| 2 | Retrieve from **every** available view of the source and merge by priority (`tsv` > `bindingdb_api` > `chembl_api` > `lmdb`), filling empty fields and unioning citations | `dedupe.py`, `readers/api.py` | Two snapshots of one database disagree; a merge must not lose provenance |
| 3 | Organism filter (human) | `organism.py` | Species mixing is a silent scientific error |
| 4 | Small-molecule filters: MW ≤ 1000, InChIKey dedupe | `filters.py` | Peptide/large-agent noise; duplicate structures per paper |
| 5 | **Activity classification**: parse value + qualifier + unit → `active` / `weak` / `unknown` at a threshold (default 10 µM) | `activity.py` | A number without a class cannot answer "is this a hit list?" |
| 6 | **Screening-reference gate**: qualifies iff ≥ 1 compound at/below the threshold; a sparse-and-weak or empty set is treated like a *miss* and triggers step 7 | `activity.py::evaluate_gate` | ≤10 compounds, none better than 10 µM, is a negative result — not a hit list |
| 7 | Literature/web supplement with a **mandatory provenance note** ("not from BindingDB"), DOI/PMID/URL kept; structure-less rows allowed as explicit remark rows, never invented | `web_supplement.py`, `AGENTS.md` | When the database misses, the scientist still needs the literature compound — labelled |
| 8 | Export XLSX + SDF with the class columns (`activity_class`, `best_activity_nM`, `activity_label`) and `source`/`note`/`MW` | `schema.py`, `writers/export.py` | The weak rows stay as counter-evidence |
| 9 | **Patent-number audit**: normalize publication numbers from arbitrary text; per patent report `bindingdb` / `chembl` / `structured_supplement` / `chembl_document_only` / `absent` | `patents.py`, `cli/audit_patent_coverage.py` | Patent provenance is the point of the exercise |
| 10 | Deliverable verification with the *run folder as the parameter source* (thresholds, dpi, order are read back, never hardcoded) and independent recomputation | `verify.py`, `cli/verify_run.py`, `run_meta.json` | A verifier that assumes different parameters than the builder proves nothing |

Observed on the real run (`outputs/2026-09-15/`): 7 targets, `activity_gate.json` with
per-target `{n_total, n_active, n_weak, n_unknown, qualifies, reason}` and filter
statistics, `patent_coverage.json` with per-patent status, `run_meta.json` pinning the
exact scale/threshold parameters used.

## 2. Which parts SPAgo already has (so they are not re-imported)

Verified by reading the listed files, not by assumption:

| Source feature | SPAgo status |
| --- | --- |
| Cross-source retrieval with per-source status and provenance | Already implemented: `services/discovery.py`, `source_retrievals`, `RetrievalStatus` |
| Merge without losing provenance | Already implemented: measurements stay per-source; compounds are one row per InChIKey |
| Organism / species preservation | Already labelled per measurement and per target (`ResolvedTarget.organism`, `measurements.species`) |
| MW / small-molecule focus | Better than the source: deterministic modality classifier (`chemistry/modality.py`, `Modality`, `SMALL_MOLECULE_MODALITIES`) rather than an MW cutoff |
| InChIKey identity | Already implemented (`compounds.inchikey` unique, `compound_id_for_inchikey`) |
| Citation union on duplicates | Partially: `_merge_row_fields` equivalent exists as measurements + `potential_duplicate` flags |
| Adaptive structure rendering, XLSX/SDF writers | SPAgo has CSV/SDF export and browser depiction; the source's card/PDF engine is a *different deliverable*, not a gap |
| Alias tempfiles (confidentiality) | Not applicable: SPAgo target queries are runtime user input, not project secrets |

## 3. Cherry-pick decisions (AGENTS.md §37)

| # | Item from the source | Verdict | Where it lands |
| --- | --- | --- | --- |
| A | Deterministic **activity classes** (active / weak / unknown) with censored-value (`<`, `>`, `~`) and unit handling | **CORE** | new `chemistry/activities.py` |
| B | **Screening-reference verdict** per target, with counts by endpoint, modality and evidence class, plus a machine reason | **CORE** | new `services/reference.py`, API, UI, coverage matrix |
| C | **Patent-number extraction/normalization** from source-declared ids | **CORE** | new `domain/patent_numbers.py` + ChEMBL document metadata fetch |
| D | **Patent linkage for discovered candidates** (source-declared patent → normalized → matched against the loaded corpus) | **CORE** | `services/discovery.py`, `services/export.py`, candidate API/UI |
| E | Per-source, per-endpoint **counts reported as facts** ("no compound ≤ X", "N records", "M peptides excluded") | **CORE** | verdict payload; AI target snapshot v7; UI coverage strip |
| F | **Policy recorded with the artifact** (`threshold_nM`, `min_compounds`, `policy_version` travel with the verdict and the export) | **CORE** | verdict payload, export columns, AI input snapshot |
| G | Structure-less rows (a potency with no public structure) as explicit, never-invented rows | **NEXT (wave 2)** | reported as a counted rejection + supplement import path (§5) |
| H | Literature/web supplement with mandatory `note` and `user_curated` provenance | **NEXT (wave 2)** | `POST /targets/{id}/supplements`, dialog in the target view |
| I | Fixed-scale structure cards + lossless PDF + run verifier | **LATER** | independent deliverable (print sheet); needs its own plan; SPAgo renders in-browser and exports CSV/SDF today |
| J | Local bulk TSV/LMDB snapshot readers (multi-GB single-pass matching) | **LATER** | operator dataset ingestion; AGENTS.md §6/§33 require an ADR + measured need first; the bounded REST path is the current answer |
| K | XLSX writer | **REJECT** | SPAgo exports CSV/SDF; a second tabular format is duplicate surface |
| L | Trusting a source's `molecule_type` label | **REJECT** | already deliberately not trusted (`chemistry/modality.py`) |

**Follow-up, 2026-09-16 (read-only re-review).** The snapshots this plan deferred as J
are now carried as backlog items with an argued priority: `docs/plans/backlog.md` §2
B-23 (local snapshot search, TSV first), B-24 (patent→compound ChEMBL search, the one
capability here that works in a hosted deployment), B-25 (supplement bundle import),
B-26 (patent coverage audit) and B-27 (card sheet + PDF, still LATER). Two rules learned
in that review are now normative: `AGENTS.md` §7 (operator snapshot files) and §12
(agent-assisted retrieval, mandatory note, no unreviewed promotion to `user_curated`).
The verdicts above are unchanged except J, which is superseded by B-23.

## 4. Wave 1 — implementation spec (CORE)

### 4.1 Chemistry: `services/core/spago_core/chemistry/activities.py` (new)

Pure, deterministic, no I/O:

- `CONCENTRATION_UNITS: dict[str, float]` — unit → nM factor (`nM` 1, `uM`/`µM` 1e3,
  `mM` 1e6, `pM` 1e-3, `M` 1e9, `fM` 1e-6).
- `POTENCY_ENDPOINTS: frozenset[str]` — affinity/potency standard types only
  (`ic50`, `ki`, `kd`, `ec50`, `ac50`, `potency`, `kd_app`, `ki_app`,
  `dissociation constant`, `inhibition constant`). Kinetics (`kon`, `koff`) and
  percent/ratio readouts are explicitly **not** potency endpoints — this is the
  one place where the source's column list is narrower than SPAgo's data.
- `ActivityClass` (str enum): `active`, `weak`, `unknown`, `not_applicable`.
- `to_nanomolar(value, unit) -> float | None`.
- `classify_activity(value, unit, relation, standard_type, threshold_nm) -> ActivityClass`
  with the source's censor semantics, documented per branch:
  `<` bound ≤ threshold → active; `<` bound > threshold → unknown;
  `>` bound ≥ threshold → weak; `>` bound < threshold → unknown;
  `=`/`~` ≤ threshold → active, else weak; unknown unit or non-potency endpoint →
  `not_applicable` (never guessed).
- `potency_label(standard_type, value, unit, relation) -> str` (e.g. `IC50 4 nM`),
  the source's `activity_label` (no cross-endpoint ranking).

### 4.2 Policy + verdict: `services/core/spago_core/services/reference.py` (new)

- `ACTIVITY_POLICY_VERSION = "potency-gate-v1"`.
- `POLICY` read from settings: `activity_threshold_nm` (default 10 000 = 10 µM),
  `min_compounds` (default 10). Request-level override, validated (`1 … 1e9`).
- `reference_verdict(engine, target_id, *, threshold_nm, min_compounds,
  include_all_modalities=False) -> ReferenceVerdict`:
  - counts: measurements total (and classed), distinct compounds,
    `active`/`weak`/`unknown`/`not_applicable`, per endpoint type,
    per modality (default scope = small molecule + unclassified), evidence classes,
    `potential_duplicate` count, `records_without_structure` (rejection counts
    summed from `source_retrievals.rejection_counts`), patent-linked candidates,
    source-declared-patent candidates;
  - `qualifies` = ≥1 compound whose **small-molecule-scope** measurement is `active`;
  - `reason` — deterministic sentence, e.g. `<n> compound(s) at or below 10 µM`,
    `only 3 compounds, none at or below 10 µM (sparse and weak)`,
    `no compound at or below 10 µM (negatives only)`, `no measurement is recorded`,
    `only peptide measurements are at or below 10 µM (no small-molecule reference)`;
  - `scope_note` — states which modality filter the verdict used;
  - `policy` block with version/threshold/min_compounds/threshold display string.
- Read-only; the verdict is computed from stored rows on demand so a class can
  never go stale against a changed threshold.

### 4.3 Patent numbers: `services/core/spago_core/domain/patent_numbers.py` (new)

Ported (semantics, not code) from `BindingDB_IO/bindingdb_io/patents.py`:
`patent_tokens(text) -> list[str]`, `normalize_patent_number(text) -> str`,
`patent_number_match(a, b) -> bool`. Lenient extraction for *source-declared*
identifiers; the strict planner regex (`services/planner.py::_PUBNUM_RE`) is untouched
because it validates user input, not foreign data.

### 4.4 Source: ChEMBL document metadata (patent/DOI/PMID)

`adapters/chembl_discovery.py` gains a bounded, cached `documents(document_ids)` step
(batched `document_chembl_id__in`, ≤100 per request, `only=document_chembl_id,patent_id,
doi,pubmed_id,year,doc_type`), and `ActivityRecord` gains
`document_patent_number` (normalized), `document_doi`, `document_pmid`. The activity
payload itself carries `document_chembl_id` only, so without this step a discovered
compound cannot be linked to a patent — the product's central relation.
BindingDB's REST path supplies no patent id; that stays recorded as a warning.

### 4.5 Storage: `migrations/0013_activity_reference_patents.sql`

Forward-only, additive: `measurements.document_patent_number text`,
`measurements.document_doi text`, `measurements.document_pmid text`, plus
`idx_measurements_document_patent`. No column stores a *computed* class (see 4.2).

### 4.6 API

- `GET /targets/{id}/reference?activity_threshold_nm=&min_compounds=&include_all_modalities=`
  → `ReferenceVerdictResponse`.
- `DiscoverResponse.reference` — the same verdict with the deployment policy, so the
  UI needs no second call after a retrieval.
- `MeasurementResponse` += `activity_class`, `activity_class_rule`, `document_patent_number`,
  `document_doi`, `document_pmid`.
- `CandidateResponse` += `activity_class`, `potency_label`, `sources`, `source_declared_patents`.
- `CoverageMatrixRow` += `reference_qualifies`, `reference_reason`, `reference_threshold_nM`,
  `reference_n_active`, `reference_policy_version` (live, deployment policy).
- Export (`services/export.py`): candidate rows carry `activity_class`,
  `potency_label`, `source_declared_patents`, `reference_qualifies`,
  `reference_reason`, `reference_threshold_nM`, `reference_policy_version`.

### 4.7 AI

`services/ai.py::_collect_target_facts` gains a citable `reference` block
(ref `reference:{target_id}`) and the new measurement fields; `TARGET_PROMPT_VERSION`
→ `target-investigation-v7`; the prompt states that the verdict is a deterministic
count, not a biological conclusion. `benchmarks/online01-llm-eval-2026-09-15.md` gets
a re-measurement note (the eval runner must be re-run in offline mode at minimum).

### 4.8 UI (no new permanent panel)

- `TargetHeader`: a reference strip under the coverage chips — qualifies/does-not,
  the reason, threshold with an editable value (µM) and explicit apply, and the
  modality scope note. `docs/design` conventions and the existing `.coverage-chip`
  styles are reused.
- `CandidateTable`: an `Activity` column (class + `potency_label`); the patent column
  gains `source declares WO…` when a patent number comes from the source but is not in
  the loaded corpus.
- `TargetEvidencePanel`: the measurement table gains the class and the patent/DOI
  reference, keeping "shown as reported, not ranked".

### 4.9 Tests

- `tests/test_activity_classification.py` — censor/unit/endpoint edge cases
  (including `>10000` weak, `<5` active, `>5` unknown, `uM`, `pM`, `%` →
  not applicable, `kon` → not applicable, malformed value).
- `tests/test_patent_numbers.py` — ported regression cases (`WO2021/123456 A1`,
  `US-10,123,456-B2`, absent, two numbers in one string, kind codes).
- `tests/test_reference_verdict.py` (PG) — sparse-and-weak, negatives-only, actives
  present, peptide-only actives, no measurement, potential duplicates, structure-less
  rejections, policy override, and the coverage-matrix projection.
- `tests/test_online00_patents.py` (PG + stubbed ChEMBL) — document metadata is
  fetched once for a page of activities, patent numbers normalized and linked to a
  corpus family when present, absent from the corpus otherwise.
- Extend `tests/test_online00_api.py` and `tests/test_export_scope.py` for the new
  payload and export fields.

### 4.10 Docs / contract

- `AGENTS.md`: new short section — potency classification and the screening-reference
  gate (deterministic, per endpoint, no cross-assay ranking; the verdict states
  coverage, it is not a biological conclusion).
- `docs/online-capability.md`: §2/§3 supported lines, §5 the honest limits
  (no cross-assay ranking is unchanged; the verdict is a count, not an inhibitor claim),
  and the `SPAGO_ACTIVITY_THRESHOLD_NM` / `SPAGO_ACTIVITY_MIN_COMPOUNDS` knobs.
- `.env.example`: the two new settings.
- `THIRD_PARTY_NOTICES.md`: no new dependency; record the adaptation provenance
  (logic adapted from the author's local `BindingDB_IO` project, files listed).

### 4.11 Verification (DoD)

1. `python -m pytest tests` in `services/core` against the live PG+RDKit test DB.
2. `npx tsc --noEmit` + `npm run build` in `apps/web`.
3. Browser: rebuild `docker compose up -d --build app` and walk the TSLP-style flow —
   resolve → discover → read the verdict → change the threshold → open a candidate's
   evidence → export. Screenshot the settled states; record loading/empty/failed states.
4. Benchmark: `benchmarks/online06-reference-2026-09-15.md` (raw JSON beside it) —
   reference-verdict read cost, the class-carrying candidate page, the coverage
   matrix, and the bounded ChEMBL document-lookup cost added to an investigation.
5. Record what is checked/not checked in the implementation record below.

## 5. Wave 2 — NEXT (after wave 1 verifies)

**Manual literature supplement, ported from the source's `web_supplement.py`.**

- `POST /targets/{target_id}/supplements`, body bounded (≤200 rows), `extra=forbid`:
  `[{name, smiles?, activity_type?, value?, unit?, relation?, doi?, pmid?, patent_number?, note}]`.
- Validation: `note` is **required**; a row without SMILES is kept only as a
  structure-less remark with its potency; structure goes through the same RDKit
  normalization, modality classification and InChIKey identity as every other path;
  stored with `source_name='user_supplement'`, `provenance_state='user_curated'`,
  `evidence_class='unspecified'` (a supplement claims no mechanism), never merged into
  a `source_fact`.
- Reuses the verdict, export and evidence panel unchanged.
- UI: a bounded dialog ("Add literature compounds") next to the existing filters, with
  a paste-JSON textarea, per-row validation errors, and the mandatory note visible.
- Tests: validation refusal (missing note, unparseable structure, over-bound), identity
  reuse when the compound already exists from ChEMBL/BindingDB, verdict change after
  import, export provenance, and a browser pass.

Explicitly **not** in this round: full-document ingestion, OCSR, the structure-card PDF
(item I), bulk BindingDB snapshot ingestion (item J).

### 5.1 Decisions taken while implementing wave 2

Deviations from the source project and from the sketch above, each for a stated reason:

1. **No auto-filled note.** The source substitutes a default note
   (`"WebSearch supplement; not found in BindingDB."`) when a row has none. SPAgo
   refuses the row instead: a default note asserts a provenance check the user may not
   have made, which is exactly the silent provenance upgrade AGENTS.md §10 forbids.
   The note is required per row and travels into the measurement's assay description.
2. **Behaviour is per row, not per batch.** A row that fails validation is reported in
   `rejected[]` with its reasons while the other rows are stored; the response states
   exactly what was applied. An invalid *body* (not a JSON array, >200 rows, unknown
   keys) is a 422, because that is a contract failure, not a data rejection.
3. **Structure-less rows get their own table** (`target_supplement_remarks`).
   `compounds.canonical_smiles` / `inchikey` are `NOT NULL` and every measurement is
   compound-scoped, so a remark cannot masquerade as a compound. It keeps the name,
   the as-reported potency, the note and any DOI/PMID/patent number, is counted in the
   verdict (`supplement_remarks`) and is listed in the dialog — never in the compound
   table or the compound export (there is no compound to export).
4. **Re-posting the same row updates, never duplicates.** Each row's
   `source_record_id` is a content hash of (target, structure, endpoint, value, unit,
   relation, document references), so retrying an import, or importing the same
   literature row twice, is idempotent (AGENTS.md §22).
5. **Export provenance is derived, not hardcoded.** The candidate export previously
   wrote `provenance_states=['database_curated']` for every row; a user-added compound
   would then have been labelled as a curated database fact in the file. It now lists
   the distinct states of that compound's measurements for the target, so
   `user_curated` is visible in the artifact.
6. **A `GET /targets/{id}/supplements/remarks` read** exists so stored remarks stay
   retrievable after the dialog closes; the main view is unchanged (no new permanent
   panel), the remarks are listed inside the dialog.


## 6. Implementation record

Wave 1 and wave 2 are implemented and tested; the browser pass for wave 2 is in
§7 (wave 1's is §6.3).

### 6.1 What was built (files)

New:

- `services/core/spago_core/chemistry/activities.py` — potency classification
  (unit conversion, censor direction, non-potency endpoints, `not_applicable`).
- `services/core/spago_core/domain/patent_numbers.py` — extract/normalize/match
  publication numbers from source strings.
- `services/core/spago_core/services/reference.py` — policy, classified rows,
  per-compound class, target verdict.
- `migrations/0013_source_declared_patents.sql` — `measurements.document_patent_number`
  / `document_doi` / `document_pmid` (+ index, comments: source-declared, not
  corpus-verified; no backfill for rows stored earlier).
- `apps/web/src/components/ReferenceStrip.tsx`, CSS in `styles.css`.
- `services/core/tests/test_activity_classification.py`,
  `tests/test_patent_numbers.py`, `tests/test_online06_reference.py`.
- `benchmarks/online06-reference-2026-09-15.md` + `.json`,
  screenshots in `docs/plans/ui-round-verification/online06-*.png` (local-only: that
  directory is gitignored, because a screenshot of a running build shows live rows).

Changed: `domain/models.py` (`ReferencePolicy`/`ReferenceVerdict`/`ActiveCompound`,
candidate + measurement extras), `adapters/bioactivity_base.py`,
`adapters/chembl_discovery.py` (bounded `document.json` lookup),
`adapters/bindingdb_rest.py` (source attribution), `services/discovery.py`,
`services/export.py`, `services/ai.py` (target snapshot v7), `config.py`,
`api/routes.py` (`GET /targets/{id}/reference`, class fields on candidates,
measurements, coverage matrix, export), `docker-compose.yml`, `.env.example`,
`apps/web/src/{App.tsx,api/types.ts,api/client.ts,styles.css}`,
`components/{CandidateTable,TargetEvidencePanel}.tsx`, `AGENTS.md`,
`docs/online-capability.md`, `THIRD_PARTY_NOTICES.md`, `benchmarks/README.md`.

### 6.2 Commands and results

| Check | Command | Result |
| --- | --- | --- |
| Backend suite | `cd services/core && .venv/bin/python -m pytest` (live PG + RDKit) | **480 passed** in 76.3 s (0 failed, 0 skipped) |
| Frontend typecheck | `npx tsc -b apps/web` | exit 0, no diagnostics |
| Frontend build | `docker compose up -d --build app` (runs `npm run build` in the image) | image built, `/healthz` ok |
| Migration | `max(version)` in `schema_migrations` after start | `13` |

### 6.3 Browser verification (settled states)

Stack served from this checkout by the `app` container (`/assets/index-DLAtaz50.js`),
viewport 1220×927, dataset = synthetic demo fixture + the live TSLP investigation
stored earlier (`0cd78fd9-…`, 69 candidates, 120 measurement rows).

Checked, with DOM text captured at each step:

1. **Verdict strip, deployment policy** — "No reference set · Only 53 compound(s)
   outside the modality scope are at or below 10 µM; no in-scope compound is. ·
   1 in-scope compound · 0 at or below · 0 above · 0 undecided · 1 not a potency ·
   1 in-scope record · 53 active outside the modality scope"; threshold input `10`,
   `Apply` disabled, no reset button. Screenshot `online06-default-1220.png`.
2. **Threshold override** — set `1` → `Apply`: strip recomputed server-side ("Only 51
   compound(s)… at or below 1 µM"), policy line reads "threshold set in this session",
   `Use deployment policy` appears, `Apply` disabled again. The candidate table footer
   and the strip state the same policy (`1 µM (potency-gate-v1)`).
3. **Reset to deployment policy** — one click, strip and footer return to 10 µM, reset
   button disappears.
4. **Modality scope expansion** — "Include peptides, oligonucleotides and biologics
   · 68 peptide" toggled on: verdict becomes "**Reference set** · 50 of 69 in-scope
   compound(s) at or below 10 µM", counts 69 / 50 / 1 / 1 / 17, "114 in-scope records",
   "3 flagged as duplicate references", strongest reports `KD 2 nM … 4 nM`, policy note
   "Counted over every modality the source returned", footer "Showing all modalities",
   table `aria-rowcount=69` with peptide rows showing `not a potency | INHIBITION 15 %`.
   Screenshot `online06-all-modalities-1220.png`.
5. **Candidate → evidence** — clicking a strongest report selects that compound
   (URL gains `c=…`) and opens the panel: `Kd | 2 nM (pChEMBL 8.7) | active | measured
   binding | Homo sapiens · CHEMBL5537198 · DOI 10.1021/acs.jmedchem.3c02163 ·
   PMID 38284169 · source record`, i.e. the class column and the clickable DOI/PMID.
   Screenshot `online06-evidence-class-1220.png`.
6. **Default-scope row** — `INHIBITION 77.5 %` renders as `not a potency` in the
   Activity column, patent linkage "no patent mapping" with the explanatory line.

Both live verdicts agree with the ONLINE-00 coverage record for TSLP (69 candidates,
68 of them peptides, 1 small molecule), which is the intended reading: the default
scope has no small-molecule active, and the 53 peptide actives are counted and
reported rather than dropped.

### 6.4 Defects found during verification and fixed

1. **500 on live discovery (SQL).** The source-attribution upsert carried a `#`
   comment inside the SQL string → `psycopg.errors.SyntaxError` at runtime. Changed to
   `--`; the full suite is green after the fix. The failure was caught by the live API
   call, not by the suite, because the edit landed after the previous suite run.
2. **Candidate-table footer under-reported the policy.** The page object passed to
   `CandidateTable` omitted `policy`, so the footer always printed "the deployment
   threshold (policy unstated)" — wrong whenever a session threshold was applied. The
   table now receives the policy the service classified under; verified live at both
   10 µM and 1 µM.
3. **Misleading count label.** The strip's "N record(s)" counted in-scope records only;
   it now reads "N in-scope record(s)" so the number cannot be read as the total stored
   for the target.
4. **Stale source attribution (pre-existing).** 114 stored measurement rows were
   attributed to `uniprot` (the resolver) instead of the reporting source. The upsert
   now refreshes `source_name`/`dataset_version`; after re-investigation the rows read
   111 `chembl` + 3 `bindingdb` (+6 fixture), and the candidate page lists `chembl`.

### 6.5 Not checked / open

- **Source-declared patents on live data.** All 111 live TSLP documents are journal
  articles (0 rows with `document_patent_number`), so the "source declares WO…" label
  was not exercised in the browser. Covered by `tests/test_online06_reference.py`
  (fixture documents with `patent_id`) and `tests/test_patent_numbers.py`.
- Loading/failed states of the strip were not re-driven in the browser this round; the
  error branch is exercised in tests and was previously verified for the panel family.
- No memory, concurrency or sustained-load measurement (see the benchmark's
  "What these numbers do and do not say" section).
- Export latency not re-measured; export content is asserted in tests.
- **`target_construct` is declared but never populated (pre-existing, found while
  mapping the adapter layer for this port).** No adapter sets
  `ActivityRecord.target_construct` (grep-verified across `spago_core/`), so
  `measurements.construct` and the evidence panel's construct context are empty for
  every source — including ChEMBL, whose activity payload carries variant
  accession/mutation (mapped) rather than a construct string. Recorded instead of
  papered over: the panel says "context not provided" for a source that may have
  stated the construct in prose. Not fixed in this round (§37): filling it is a
  per-source parsing decision, not part of the port.
- **ChEMBL activity pages are fetched in full.** The discovery adapter sends no
  `only=` field list (only `target_chembl_id`, `limit`, `offset`), so one
  114-activity page is 103 KB and the dominant upstream cost (2.4–3.0 s in
  `benchmarks/online06-reference-2026-09-15.md`). Narrowing the projection to the
  fields the adapter reads is a measurable optimization candidate; it was not done
  and no saving is claimed (§20).
  **Closed 2026-09-16 (defect D6 + this measurement):** the projection now ships,
  and it was measured rather than assumed —
  `benchmarks/online00-chembl-projection-2026-09-16.md` records a **−42 % transfer**
  (216,632 → 127,415 and 297,821 → 169,798 bytes per page) with **no latency
  improvement**: the projected pages were equal or slower in the same interleaved
  samples. "Dominant upstream cost" was true of bandwidth, not of waiting time —
  the page count is what an investigation waits on.
- Wave 2 record: see §7 (implemented).

### 6.6 Deviations from the plan

- Migration named `0013_source_declared_patents.sql` (plan sketched
  `0013_activity_reference_patents.sql`) — same content, name states what it stores.
- Benchmark file named `benchmarks/online06-reference-2026-09-15.*` (plan sketched
  `activity-reference-…`) to match the existing `online0X` convention.
- `include_all_modalities` exists on the reference, candidate and export paths (the
  plan specified it for the verdict); without it the peptide actives could be counted
  but not read, and the strip's single explicit control would have no effect.

## 7. Wave 2 implementation record — hand-added literature rows (ONLINE-07)

**Status: implemented, tested, browser-verified on the local stack.** The
decisions are in §5/§5.1; this section records what exists, what was checked, what
was not, and where the implementation deviates.

### 7.1 What was built (files)

New:

- `migrations/0014_user_supplements.sql` — `target_supplement_remarks` (own table,
  `provenance_state` check-constrained to `user_curated`, `UNIQUE (target_id,
  source_record_id)`, comments stating it is never a measurement).
- `services/core/spago_core/services/compound_store.py` — the shared compound
  identity + upsert path (`compound_id_for_inchikey`, `CandidateStructure`,
  `persist_compounds`), extracted from the discovery service so a user-added
  structure is inserted by the *same* code as a retrieved one.
- `services/core/spago_core/services/supplements.py` — row validation, remark
  storage, structure identity, measurement/candidate upsert, remark listing and
  counting (`import_supplements`, `list_supplement_remarks`,
  `count_supplement_remarks`).
- `apps/web/src/components/SupplementDialog.tsx` — the bounded add-rows dialog.
- `services/core/tests/test_online07_supplements.py` — 23 tests
  (refusals, remark path, identity/salt/descriptor checks, verdict change and
  isolation, idempotence and remark supersession, export provenance, HTTP
  contract, and the target-summary v8 fact).
- `benchmarks/online07-supplements-2026-09-15.md` + `.json` — serving cost of the
  import/remark/verdict reads.
- `docs/plans/ui-round-verification/online07-{before,refused,stored,strip,evidence-note}-1220.png`
  — the five settled screenshots cited in §7.3 (this directory is git-ignored, as
  in §6.3).

Changed: `domain/models.py` + `domain/__init__.py` (`SupplementRow`,
`SupplementRowOutcome`, `SupplementImport`, `SupplementRemark`,
`USER_SUPPLEMENT_SOURCE`, `MAX_SUPPLEMENT_ROWS`, `ReferenceVerdict.supplement_remarks`),
`services/reference.py` (remark count + reason suffix), `services/export.py`
(provenance derived from the compound's stored measurements instead of the
hardcoded `database_curated`), `services/discovery.py` (measurement rows expose
`note`), `services/ai.py` (target snapshot v8 + offline sentence),
`api/routes.py` (`POST /targets/{id}/supplements`,
`GET /targets/{id}/supplements/remarks`, `MeasurementResponse.note`,
`ReferenceVerdictResponse.supplement_remarks`), `tests/conftest.py`
(`target_supplement_remarks` in the reset list),
`apps/web/src/{api/types.ts,api/client.ts,App.tsx,styles.css}`,
`components/{ReferenceStrip,TargetEvidencePanel}.tsx`,
`docs/online-capability.md`, `THIRD_PARTY_NOTICES.md`, `PROMPT.md`.

### 7.2 Commands and results

| Check | Command | Result |
| --- | --- | --- |
| Backend suite (wave 2 module) | `cd services/core && .venv/bin/python -m pytest tests/test_online07_supplements.py` | **23 passed**, 0 failed (includes the prompt-v8 snapshot fact) |
| Backend suite (whole tree) | `cd services/core && .venv/bin/python -m pytest -o addopts=""` (live PG + RDKit) | **503 passed**, 0 failed, 88.41 s |
| Frontend typecheck | `cd apps/web && npx tsc -b --force` | exit 0, no output |
| Frontend build | `npm run build` | built in 635 ms; `index-Dev5C05t.js` 313.03 kB (gzip 93.98 kB), CSS 20.51 kB — the same bundle name the browser was served, i.e. the verified UI is this source |
| Migration | `select max(version) from schema_migrations` after `docker compose up -d --build app` | `14` |
| Export content | `POST /api/v1/export` for the user-added compound | `provenance_states=machine_extracted\|user_curated`, verdict reason present (§7.3 item 8) |
| Serving cost | `benchmarks/online07-supplements-2026-09-15.md` | import 7.73 ms p50 (2 rows), remarks 1.83 ms, verdict 4.97 ms |
| Whitespace | `git diff --check` | clean |

### 7.3 Browser verification (settled states)

Same stack and viewport as §6.3 (app container from this checkout,
`/assets/index-Dev5C05t.js`, 1220×927, dataset = synthetic demo fixture + the live
TSLP investigation `0cd78fd9-…`). The two rows used are labelled in their own notes as
acceptance rows with placeholder values, so nothing stored by this pass reads as a
literature claim about TSLP.

1. **Entry point.** Only one new control exists: `Add a row by hand` inside the
   reference strip's policy row (no new panel, no toolbar button). Strip before the
   pass: "No reference set · Only 53 compound(s) outside the modality scope are at or
   below 10 µM · 1 in-scope compound · 0 at or below · 1 not a potency · 1 in-scope
   record". Screenshot `online07-before-1220.png`.
2. **Refusal is per row, with the reason.** A row with
   `N=C(N)this-is-not-valid-smiles` was submitted: the banner read "0 measurement(s)
   stored, 0 kept as a remark, 1 refused." and the row itself showed
   "refused · unparseable_structure: RDKit failed to parse SMILES: 'N=C(N)this-is-not-valid-smiles'
   · the row was not stored; correct the structure and re-submit". Nothing was written
   (the compound count was unchanged). Screenshot `online07-refused-1220.png`.
3. **Correction and store.** Replacing the SMILES with a valid structure and
   submitting again gave "1 measurement(s) stored … 1 already in the corpus" on the
   row ("stored · active · existing compound · stored as a user-curated measurement ·
   class active (value_at_or_below_threshold) under the stated threshold · Open
   evidence"). The identity reuse is real, not cosmetic: the structure is
   `HEFNNWSXXWATRW-UHFFFAOYSA-N`, which the synthetic demo fixture already had, and the
   database shows **one** compound row carrying both the fixture's measurement
   (`machine_extracted`) and the supplement's (`user_curated`). Screenshot
   `online07-stored-1220.png`.
4. **Structure-less row.** A second row with no SMILES was stored as a remark: "kept
   as a remark · stored without a structure: no public SMILES was supplied, so the row
   is kept as a remark with its potency and cannot be drawn or exported as a
   compound", and the dialog's "Stored remarks for this target" section listed
   `ACCEPTANCE-ROW-2 (structure not published) = 3 nM IC50` with its note. Same
   screenshot as (3).
5. **Idempotence.** Re-posting the stored compound row (the dialog keeps its rows)
   reported "1 updated an existing row instead of duplicating it." with the candidate
   count unchanged — the content-hash row id doing its job (AGENTS.md §22).
6. **The verdict changes and says why.** After the import the strip read: "**Reference
   set** · 1 of 2 in-scope compound(s) at or below 10 µM; the retrieved set can serve as
   a potency reference for this target. **1 literature remark(s) added by hand also
   carry a value without a public structure.**" Counts: 2 in-scope compounds, 1 at or
   below, 3 in-scope records, 53 active outside scope, "1 literature remark added by
   hand", strongest reports `IC50 250 nM` / `IC50 4100 nM`. There is no separate
   "user data" panel: the remark count is in the same sentence as the other counts.
   Screenshot `online07-strip-1220.png`.
7. **Evidence panel states the provenance and the note.** Selecting the new compound
   (`?c=ba20e319-…`) shows the header "small molecule · class unspecified · from
   user_supplement", the assay "user_supplement:TSLP · type user_supplement", the row
   "IC50 | 250 nM | active | class unspecified | context not provided" with "note added
   with this row: ONLINE-07 acceptance row: …", and — below it — the fixture's own
   "Demo cyclooxygenase (synthetic) … IC50 4100 nM" row for the same compound. Two
   provenance states on one structure, both legible. Screenshot
   `online07-evidence-note-1220.png`.
8. **Export (API check, not browser).** `POST /api/v1/export` for that compound returns
   `provenance_states: machine_extracted|user_curated`, `activity_class: active`,
   `reference_qualifies: true` and the verdict reason including the remark sentence —
   the file states a mixed provenance instead of the previous hardcoded
   `database_curated`.

### 7.4 Open items for this wave

- **The two acceptance rows remain in the local dev database** (target `0cd78fd9-…`,
  1 measurement + 1 remark + 1 merged compound). They are labelled as acceptance rows
  in their own notes and names, so they cannot be mistaken for a finding; correcting
  them is a re-post, and taking them back is now the withdrawal path below (they were
  left in place deliberately: the withdrawn-row display has to be exercised by
  something).
- **No delete/withdraw path for a hand-added row.**
  **Closed 2026-09-16 (defect D3).** A row can be taken back with a required reason:
  `retracted_at`/`retracted_reason` on the row, a `withdrawn_supplements` count in the
  verdict, the withdrawn rows listed in the dialog with their reason, and re-posting
  the same row restoring it. The decision the item asked for was taken in favour of a
  **recorded retraction instead of a deletion** — a user-curated row that vanishes
  silently would leave a count that changed with no trace (AGENTS.md §9/§10). Code:
  `services/supplements.py`, `api/routes.py`, `SupplementDialog.tsx`,
  `TakeBackControl.tsx`; tests: `TestWithdrawal`, `test_online07_supplements.py`.
- **No bulk paste.** The plan sketched a paste-JSON textarea; the dialog uses
  per-row fields instead (deviation recorded in §7.5).
- The dialog's loading, empty-remarks and refused-row states were driven in tests
  and in the browser pass only for the paths recorded in §7.3; the "target has no
  candidates at all" case was not re-driven.
  **Closed 2026-09-16 (browser, served build, 1220×1000).** A target with no
  retrievals at all (`DEMO-TARGET-1`, `/?t=cd46db5c-…`) renders three separate
  honest statements rather than one ambiguous blank: the coverage strip says
  "No retrieval has been run for this target yet." next to a *Query open sources*
  button, the verdict strip says "No reference set — No stored measurement for this
  target." with zeroed counts, and the candidate area carries the banner that names
  the three different facts ("no records" / "source failed" / "not queried"). The
  add-rows dialog opens in that state and states its `user_curated` provenance.
  Screenshots (local, gitignored): `docs/plans/ui-round-verification/online06-zero-candidate-target-1220.png`
  and `online07-zero-candidate-dialog-1220.png`.
- Remark rows are counted in the verdict and listed in the dialog, but they are
  not part of any export (there is no compound to export) and do not appear in the
  candidate table — that is the intended contract, stated in
  `docs/online-capability.md` §3.

### 7.5 Deviations from the plan

- **Per-row fields instead of a paste-JSON textarea.** A form makes the required
  note and the endpoint/unit pairing explicit at the point of entry, and it cannot
  be defeated by malformed JSON; the JSON path would have needed its own error
  surface for no scientific gain. The submitted shape is still the documented row
  object (and is what the tests post).
- **The `note` is a measurement column, not a new one.** It is stored in the
  existing `measurements.assay_description` and exposed as its own `note` field on
  the API/UI, because the schema already had a "free text about this measurement"
  slot and adding a second one would have made two places say the same thing.
- **A structure-less row and the same row with a structure are one claim.**
  Supplying the SMILES later deletes the remark instead of leaving both. This is
  stricter than the plan (which did not state it) and is needed so the verdict
  cannot count one paper twice.
- **`supplement_remarks` is on the verdict, not a separate call.** The reader sees
  it in the same sentence as the counts, which is where the risk of reading a thin
  set as "nothing recorded" actually lives.


