/** Domain types mirroring the FastAPI response models (spago_core/api/routes.py). */

export interface PatentFamily {
  id: string;
  family_key: string;
  title: string | null;
}

export interface PatentDocument {
  id: string;
  publication_number: string;
  family_id: string;
  title: string | null;
  abstract: string | null;
  assignee: string | null;
  publication_date: string | null;
  jurisdiction: string | null;
  doc_type: string | null;
}

export interface Compound {
  id: string;
  canonical_smiles: string;
  inchikey: string;
  inchi: string | null;
  molecular_formula: string | null;
  molecular_weight: number | null;
  hbd: number | null;
  hba: number | null;
  tpsa: number | null;
  logp: number | null;
  has_stereo: boolean;
  is_multi_component: boolean;
  scaffold: string | null;
  normalization_notes: string | null;
}

export interface ActivitySummary {
  target_name: string | null;
  assay_key: string;
  assay_type: string | null;
  standard_type: string;
  value: number;
  unit: string;
  relation: string;
  provenance_state: string;
  dataset_version: string;
}

export interface Mention {
  id: string;
  compound_id: string;
  document_id: string;
  publication_number: string | null;
  patent_label: string | null;
}

export interface CompoundRow {
  compound: Compound;
  mentions: Mention[];
  activity: ActivitySummary[];
}

export interface CompoundPage {
  total: number;
  offset: number;
  limit: number;
  items: CompoundRow[];
}

/** B-03: how the requested number reached the stored row. `matched` is the corpus
 * value verbatim — never rewritten to look like what was typed. */
export interface PatentMatch {
  requested: string;
  matched: string;
  exact: boolean;
  rule: string;
}

export interface PatentResponse {
  document: PatentDocument;
  family: PatentFamily;
  documents: PatentDocument[];
  mention_counts: Record<string, number>;
  match: PatentMatch;
}

export interface FamilyResponse {
  family: PatentFamily;
  documents: PatentDocument[];
  mention_counts: Record<string, number>;
}

export interface EvidenceRecord {
  id: string;
  compound_id: string | null;
  compound_mention_id: string | null;
  document_id: string | null;
  publication_number: string | null;
  source_type: string;
  section: string | null;
  page: number | null;
  table_ref: string | null;
  figure_ref: string | null;
  paragraph: string | null;
  compound_local_id: string | null;
  raw_excerpt: string | null;
  source_url: string | null;
  extraction_method: string;
  provenance_state: string;
  confidence: number | null;
  dataset_version: string;
  retrieved_at: string;
}

export interface HealthResponse {
  status: string;
  database: string;
  chemistry: string;
  rdkit_cartridge: string;
  dataset_version: string | null;
  ingestion_issues: number;
  api_version: string;
}

export interface DatasetInfoResponse {
  source_name: string;
  dataset_version: string;
  synthetic: boolean;
  release_label: string | null;
  files: Record<string, { sha256: string; rows: number }>;
  notes: string | null;
  ingestion_issues: {
    source_record_id: string | null;
    document_id: string | null;
    patent_label: string | null;
    raw_smiles: string;
    issue: string;
  }[];
  /** All loaded datasets (demo + imported), newest first (PROD-01). */
  datasets?: DatasetEntry[];
}

export interface DatasetEntry {
  source_name: string;
  dataset_version: string;
  synthetic: boolean;
  release_label: string | null;
  retrieved_at: string;
}

/** What the loaded corpus covers, by dataset version (B-01). Every number is a
 * count over the corpus tables, so a number absent here was never imported. */
export interface CorpusSourceRow {
  dataset_version: string;
  source_name: string | null;
  synthetic: boolean;
  /** False for a version recorded per row by a source lookup instead of an
   * operator-imported package. */
  registered: boolean;
  release_label: string | null;
  retrieved_at: string | null;
  notes: string | null;
  files: number;
  families: number;
  documents: number;
  compounds: number;
  mentions: number;
  evidence: number;
  measurements: number;
  issues: number;
}

export interface CorpusResponse {
  generated_at: string;
  sources: CorpusSourceRow[];
  totals: Record<string, number>;
  imports: {
    queued: number;
    running: number;
    completed: number;
    failed: number;
    interrupted: number;
    last_finished_at: string | null;
    last_error: {
      source_name: string;
      dataset_version: string;
      error: string;
      finished_at: string | null;
    } | null;
  };
  notes: string[];
}

/* --- M1: projects + save --- */

export interface ProjectSummary {
  id: string;
  name: string;
  description: string | null;
  item_count: number;
  created_at: string;
}

export interface ProjectItem {
  id: string;
  /** Null for a target-candidate item: it has no patent mapping. */
  family_id: string | null;
  family_key: string | null;
  compound_id: string | null;
  inchikey: string | null;
  canonical_smiles: string | null;
  dataset_version: string;
  /** Server-derived source list at save time (PROD-03). */
  dataset_versions?: { source_name: string; dataset_version: string }[];
  record_missing?: boolean;
  source_updated?: boolean;
  added_at: string;
  /** ONLINE-00: target scope of a saved candidate. */
  target_id?: string | null;
  target_key?: string | null;
  target_name?: string | null;
  evidence_class?: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  items: ProjectItem[];
}

export interface SaveScopeResult {
  created_rows: number;
  already_present_rows: number;
  scope_family: boolean;
  dataset_versions?: { source_name: string; dataset_version: string }[];
}

/* --- M2: structure search --- */

export interface StructureSearchResponse {
  mode: string;
  total: number;
  offset: number;
  limit: number;
  query_canonical_smiles: string;
  query_inchikey: string;
  query_has_stereo: boolean;
  threshold: number | null;
  items: { compound: Compound; mentions: Mention[]; score: number | null }[];
}

/* --- M5 + LLM interface: evidence-grounded AI --- */

export interface CitationRef {
  fact_ref: string;
  /** The citation kinds the server can emit. `source` is a per-source retrieval
   * outcome in a target analysis (`source:<name>`); clicking it focuses the
   * matching coverage chip rather than a molecule or an excerpt. `reference` is
   * the ONLINE-06 potency verdict (`reference:<target-id>`), which the target
   * prompt asks the model to cite for potency statements. */
  kind:
    | "family"
    | "document"
    | "target"
    | "candidate"
    | "measurement"
    | "source"
    | "reference"
    | "evidence";
  label?: string;
  evidence_id?: string;
  inchikey?: string;
  measurement_id?: string;
  target_id?: string;
  /** Set on `source` citations: the coverage chip to focus. */
  source_name?: string;
}

export interface CoverageEntry {
  dataset_version: string;
  synthetic: boolean | null;
  documents: number;
  compounds: number;
  measurements: number;
}

export interface FamilySummaryResponse {
  analysis_id: string;
  provider: string;
  /** family | document | target — the scope the analysis actually covers. */
  scope?: "family" | "document" | "target";
  provenance_state: string;
  text: string;
  citations: CitationRef[];
  dataset_version: string;
  created_at: string;
  mode?: string;
  model?: string | null;
  cached?: boolean;
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
  coverage?: CoverageEntry[];
  input_snapshot?: Record<string, unknown>;
}

export interface AiStatusResponse {
  state: "offline" | "configured" | "config_invalid";
  model: string | null;
  target: string | null;
  reason: string | null;
}

/* --- ONLINE-00: target-led investigation --- */

export interface TargetComponent {
  accession: string | null;
  name: string | null;
  gene_symbol: string | null;
  role: string | null;
  organism: string | null;
}

export interface ResolutionCandidate {
  identifier: string;
  name: string | null;
  organism: string | null;
  target_type: string | null;
  source_name: string | null;
  reason: string | null;
}

export interface TargetResolution {
  status: "resolved" | "ambiguous" | "not_found" | "not_queried" | "failed";
  query: string;
  species: string;
  target_id: string | null;
  target_key: string | null;
  name: string | null;
  organism: string | null;
  uniprot_accession: string | null;
  gene_symbol: string | null;
  target_type: string | null;
  scope_kind: string | null;
  aliases: string[];
  components: TargetComponent[];
  candidates: ResolutionCandidate[];
  excluded: ResolutionCandidate[];
  notes: string[];
  source_name: string;
  source_version: string | null;
  retrieved_at: string;
}

export interface ResolvedTarget {
  id: string;
  target_key: string;
  name: string | null;
  organism: string | null;
  taxon_id: number | null;
  uniprot_accession: string | null;
  gene_symbol: string | null;
  target_type: string | null;
  scope_kind: string | null;
  aliases: string[];
  components: TargetComponent[];
  source_name: string | null;
  dataset_version: string | null;
  resolution?: TargetResolution | null;
}

/** Per-source retrieval outcome. `empty` and `failed` are different facts and
 * the UI must keep them different (never "no inhibitors exist"). */
export interface SourceRetrieval {
  source_name: string;
  status: "complete" | "partial" | "empty" | "failed" | "not_queried";
  query: Record<string, unknown>;
  dataset_version: string | null;
  source_version: string | null;
  pages_fetched: number;
  records_seen: number;
  records_kept: number;
  records_excluded: number;
  rejection_counts: Record<string, number>;
  /** B-02: how the source-declared document reference resolved over this
   * retrieval's kept records — disjoint buckets whose sum is `records_kept`
   * (`spago_core/domain/document_refs.py`). Empty means the run predates the
   * tally, which is not "nothing declared". */
  reference_counts: Record<string, number>;
  latency_ms: number | null;
  warnings: string[];
  checksum: string | null;
  retrieved_at: string;
}

export interface DiscoverResponse {
  target_id: string;
  target_key: string;
  sources: SourceRetrieval[];
  compounds_stored: number;
  compounds_reused: number;
  measurements_stored: number;
  candidates_stored: number;
  small_molecule_candidates: number;
  modality_counts: Record<string, number>;
  rejections: Record<string, number>;
  warnings: string[];
  coverage_note: string;
  /** ONLINE-06: the potency verdict under the deployment policy, computed from
   * the rows just persisted. One rule produces the verdict, the table's class
   * column and the export columns. */
  reference?: ReferenceVerdict | null;
}

/** Whether a target's retrieved set can serve as a potency reference: a
 * deterministic count under an explicit policy, never a biological conclusion. */
export interface ActiveCompound {
  compound_id: string;
  inchikey: string;
  /** As reported by the source, e.g. `IC50 4 nM` (never silently converted). */
  potency_label: string;
  standard_type: string;
  value: number;
  unit: string;
  relation: string;
  value_nm: number;
  evidence_class: string;
  source_name: string;
  measurement_id?: string | null;
  potential_duplicate: boolean;
}

export interface ReferencePolicy {
  version: string;
  threshold_nm: number;
  threshold_label: string;
  min_compounds: number;
  all_modalities: boolean;
  modality_scope: string;
  scope_note: string;
}

export interface ReferenceVerdict {
  target_id: string;
  target_key: string;
  target_name?: string | null;
  qualifies: boolean;
  reason: string;
  policy: ReferencePolicy;
  compounds: number;
  compounds_active: number;
  compounds_weak: number;
  compounds_unknown: number;
  compounds_not_applicable: number;
  active_compounds_outside_scope: number;
  measurements: number;
  class_counts: Record<string, number>;
  endpoint_counts: Record<string, number>;
  evidence_class_counts: Record<string, number>;
  modality_counts: Record<string, number>;
  actives: ActiveCompound[];
  best_active?: ActiveCompound | null;
  potential_duplicates: number;
  /** Source records that reported a value but no drawable structure: counted
   * rejections, so a thin set is not read as a negative result. */
  records_without_structure: number;
  /** ONLINE-07: hand-added rows that carry a value but no public structure.
   * Counted separately from `records_without_structure`: one is a source that
   * could not supply a structure, the other is a person who added a claim. */
  supplement_remarks: number;
  source_declared_patents: string[];
  truncated: boolean;
}

/** One literature/patent row a person added by hand. The note is what makes the
 * row auditable, so the server requires it; a row with no SMILES is kept as a
 * structure-less remark rather than dropped. */
export interface SupplementRowInput {
  name: string;
  note: string;
  smiles?: string | null;
  activity_type?: string | null;
  value?: number | null;
  unit?: string | null;
  relation?: string;
  doi?: string | null;
  pmid?: string | null;
  patent_number?: string | null;
}

/** What happened to one submitted row, stated per row and per reason. */
export interface SupplementRowOutcome {
  index: number;
  status: "measurement" | "remark" | "rejected";
  name: string;
  /** The id `…/supplements/{record_id}/withdraw` accepts, so the row just stored
   * can be taken back without a re-read (defect D3). */
  record_id?: string | null;
  compound_id?: string | null;
  inchikey?: string | null;
  activity_class?: ActivityClass | null;
  reused_compound: boolean;
  reasons: string[];
}

export interface SupplementImport {
  target_id: string;
  received: number;
  measurements: number;
  remarks: number;
  compounds_created: number;
  compounds_reused: number;
  /** Rows that updated an existing identical row instead of duplicating it. */
  updated: number;
  rows: SupplementRowOutcome[];
}

/** A stored structure-less row: a claim SPAgo cannot draw, kept so a thin set is
 * not read as a negative result. Never counted as a measurement or a compound. */
export interface SupplementRemark {
  id: string;
  target_id: string;
  name: string;
  note: string;
  activity_type?: string | null;
  value?: number | null;
  unit?: string | null;
  relation?: string | null;
  doi?: string | null;
  pmid?: string | null;
  patent_number?: string | null;
  provenance_state: string;
  created_at: string;
  /** Present when the row was taken back: the row stays readable and states why. */
  source_record_id: string;
  retracted_at?: string | null;
  retracted_reason?: string | null;
}

/** A hand-added row the user took back (defect D3). */
export interface WithdrawnSupplement {
  kind: "measurement" | "remark";
  record_id: string;
  name: string;
  note?: string | null;
  activity_type?: string | null;
  value?: number | null;
  unit?: string | null;
  relation?: string | null;
  retracted_at: string;
  retracted_reason?: string | null;
  /** True when the compound also left the investigation's candidate list. */
  candidate_retracted: boolean;
}

/** What one withdrawal did, so the dialog can state it instead of guessing. */
export interface SupplementWithdrawal {
  kind: string;
  record_id: string;
  status: string;
  reason: string;
  compound_id?: string | null;
  candidate_retracted: boolean;
}

/** What one compound's own reports support under the stated threshold. */
export type ActivityClass = "active" | "weak" | "unknown" | "not_applicable";

export interface Candidate {
  compound_id: string;
  canonical_smiles: string;
  inchikey: string;
  molecular_formula: string | null;
  molecular_weight: number | null;
  modality: "small_molecule" | "peptide" | "oligonucleotide" | "biologic" | "unclassified" | "unparseable";
  modality_rule: string | null;
  modality_source: string | null;
  source_name: string;
  source_record_id: string;
  evidence_class:
    | "measured_direct_binding"
    | "interaction_disruption"
    | "functional_effect"
    | "screening_assay"
    | "computational_prediction"
    | "unspecified";
  patent_occurrences: number;
  patent_labels: string[];
  measurements: number;
  /** ONLINE-06: this compound's own potency class under the requested policy,
   * with the as-reported label that decided it, the sources behind it, and any
   * publication numbers the *source* declares (source-declared, not corpus). */
  activity_class: ActivityClass;
  activity_rule?: string | null;
  potency_label?: string | null;
  sources: string[];
  source_declared_patents: string[];
  /** Defect D2: true only for a row returned because it was asked for by id
   * while the active filter excludes it (not part of `total`). */
  outside_filter?: boolean;
}

export interface CandidatePage {
  total: number;
  offset: number;
  limit: number;
  items: Candidate[];
  modality_breakdown: Record<string, number>;
  default_filter: string;
  /** The policy the row classes were computed under, so the table can state it. */
  policy?: ReferencePolicy | null;
}

export interface TargetMeasurement {
  id: string;
  compound_id: string;
  inchikey: string | null;
  target_name: string | null;
  target_key: string | null;
  target_type: string | null;
  assay_key: string;
  assay_type: string | null;
  assay_description: string | null;
  assay_format: string | null;
  standard_type: string;
  value: number;
  unit: string;
  relation: string;
  raw_value: string | null;
  evidence_class: string;
  species: string | null;
  variant_accession: string | null;
  variant_mutation: string | null;
  pchembl_value: number | null;
  potential_duplicate: boolean;
  validity_comment: string | null;
  document_ref: string | null;
  source_url: string | null;
  source_record_id: string | null;
  source_name: string;
  extraction_method: string;
  provenance_state: string;
  dataset_version: string;
  retrieved_at: string;
  /** ONLINE-06: the reference decomposed (source-declared, not corpus-verified)
   * and the class this single report supports under the requested threshold. */
  document_patent_number?: string | null;
  document_doi?: string | null;
  document_pmid?: string | null;
  /** ONLINE-07: the note a person wrote when adding the row by hand. Shown as the
   * row's provenance, never as a source's assay description. */
  note?: string | null;
  activity_class?: ActivityClass | null;
  activity_class_rule?: string | null;
}

/* --- ONLINE-02: interpreted search plans --- */

export interface PlanStep {
  op: string;
  description: string;
  parameters: Record<string, unknown>;
  expensive: boolean;
}

export interface SearchPlanResponse {
  plan_version: string;
  query: string;
  producer: "offline" | "llm";
  steps: PlanStep[];
  unresolved: string[];
  clarification_required: boolean;
  note: string;
  model: string | null;
  mode: string;
}

export interface PlanStepResult {
  op: string;
  status: "ok" | "not_found" | "ambiguous" | "invalid" | "failed";
  detail: string;
  data: Record<string, unknown>;
}

export interface PlanExecuteResponse {
  query: string;
  producer: string;
  steps: PlanStepResult[];
  unresolved: string[];
}

/* --- ONLINE-03: hosted access --- */

export interface AuthStatus {
  mode: "disabled" | "required";
  required: boolean;
  authenticated: boolean;
  email?: string | null;
  display_name?: string | null;
  is_admin?: boolean;
  csrf_token?: string | null;
  session_expires_at?: string | null;
  note?: string;
}

export interface SessionInfo {
  email: string;
  display_name?: string | null;
  is_admin: boolean;
  csrf_token: string;
  expires_in_hours: number;
}

export interface UsageReport {
  window: string;
  user_tokens: number;
  user_limit: number;
  deployment_tokens: number;
  deployment_limit: number;
  requests: number;
  failures: number;
  estimated_cost: number | null;
  currency: string | null;
  cost_note: string;
}

/** One stored analysis as the history list shows it (B-10). */
export interface AnalysisEntry {
  analysis_id: string;
  scope: "family" | "document" | "target";
  analysis_kind: string;
  /** What this analysis covers, named the way the workspace names it. */
  scope_label: string;
  /** What to submit to the search box to reopen the scope; null when the
   * scope no longer exists, in which case no navigation is offered. */
  scope_query: string | null;
  scope_id: string | null;
  provider: string;
  model: string | null;
  mode: string;
  provenance_state: string;
  prompt_version: string | null;
  dataset_version: string;
  created_at: string;
  citation_count: number;
  total_tokens: string | null;
  stale: boolean;
  stale_reasons: string[];
  exact_check: { same_inputs: boolean | null; note?: string } | null;
}

export interface AnalysisListResponse {
  items: AnalysisEntry[];
  total: number;
  limit: number;
  offset: number;
  current_dataset_version: string | null;
}

export interface AnalysisDetail extends AnalysisEntry {
  text: string;
  citations: { fact_ref: string; kind: string; label?: string | null }[];
  usage: Record<string, unknown> | null;
}

/** One record a source *declares* for a publication (B-24).
 *
 * Not a corpus occurrence: `document_patent_number` is the reference the source
 * itself recorded, and nothing here says the compound occurs in a patent.
 */
export interface PatentSourceRow {
  row_id: string;
  compound_id: string;
  inchikey: string;
  canonical_smiles: string;
  molecular_formula: string | null;
  molecular_weight: number | null;
  modality: string | null;
  source_record_id: string;
  source_molecule_id: string | null;
  source_molecule_name: string | null;
  standard_type: string;
  value: number;
  unit: string;
  relation: string;
  raw_value: string | null;
  pchembl_value: number | null;
  /** The source's own duplicate flag; kept rather than resolved away. */
  potential_duplicate: boolean;
  validity_comment: string | null;
  /** Computed on read under the policy named on the response. */
  activity_class: "active" | "weak" | "inactive" | "undecided" | "unknown" | "not_applicable";
  activity_class_rule: string;
  potency_label: string;
  assay_key: string | null;
  assay_type: string | null;
  assay_description: string | null;
  target_key: string | null;
  target_name: string | null;
  species: string | null;
  variant_accession: string | null;
  variant_mutation: string | null;
  document_ref: string | null;
  document_patent_number: string | null;
  document_doi: string | null;
  document_pmid: string | null;
  source_url: string | null;
  provenance_state: string;
  dataset_version: string;
  retrieved_at: string;
}

export interface PatentSourceDocumentRef {
  document_chembl_id: string | null;
  patent_id: string | null;
  doi: string | null;
  pubmed_id: string | null;
  year: number | null;
}

/** A document the body search returned whose number is *not* this publication. */
export interface PatentSourceNearMatch {
  document_chembl_id: string | null;
  patent_id: string | null;
  year: number | null;
  reason: string;
}

export interface PatentSourceResponse {
  publication_number: string;
  requested_number: string;
  source_name: string;
  source_version: string | null;
  dataset_version: string | null;
  /** complete | partial | empty | failed | not_queried.
   * `not_queried` means nothing was asked — not that the source knows nothing. */
  status: "complete" | "partial" | "empty" | "failed" | "not_queried";
  match_rule: string;
  match_rule_text: string | null;
  retrieved_at: string | null;
  /** When the set now shown was retrieved (differs from `retrieved_at` after a failure). */
  rows_retrieved_at: string | null;
  documents: PatentSourceDocumentRef[];
  near_matches: PatentSourceNearMatch[];
  warnings: string[];
  rejection_counts: Record<string, number>;
  bounds: Record<string, number>;
  records_seen: number;
  records_excluded: number;
  row_count: number;
  compound_count: number;
  activity_class_counts: Record<string, number>;
  activity_classes_with_a_class: number;
  reference_threshold_nM: number;
  reference_threshold_label: string;
  reference_policy_version: string;
  not_queried_reason: string | null;
  offset: number;
  limit: number;
  rows: PatentSourceRow[];
}
