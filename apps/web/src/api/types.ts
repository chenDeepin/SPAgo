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

export interface PatentResponse {
  document: PatentDocument;
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
  family_id: string;
  family_key: string;
  compound_id: string | null;
  inchikey: string | null;
  canonical_smiles: string | null;
  dataset_version: string;
  added_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  items: ProjectItem[];
}

export interface SaveScopeResult {
  created_rows: number;
  already_present_rows: number;
  scope_family: boolean;
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

/* --- M5: evidence-grounded AI --- */

export interface FamilySummaryResponse {
  analysis_id: string;
  provider: string;
  provenance_state: string;
  text: string;
  citations: { evidence_id: string; inchikey: string }[];
  dataset_version: string;
  created_at: string;
}
