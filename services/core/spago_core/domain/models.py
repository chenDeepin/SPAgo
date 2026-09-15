"""Typed domain models shared across adapters, services, and the API.

These models are the normalized contract: external schemas (SureChEMBL Parquet,
future OPS/ChEMBL payloads) must never leak past the adapters.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from spago_core.chemistry.modality import Modality


class ProvenanceState(str, enum.Enum):
    """Where a scientific datum came from. Never upgraded silently."""

    SOURCE_FACT = "source_fact"
    DATABASE_CURATED = "database_curated"
    MACHINE_EXTRACTED = "machine_extracted"
    LLM_INFERRED = "llm_inferred"
    USER_CURATED = "user_curated"


class EvidenceSourceType(str, enum.Enum):
    TITLE = "title"
    ABSTRACT = "abstract"
    CLAIM = "claim"
    DESCRIPTION = "description"
    EXAMPLE = "example"
    TABLE = "table"
    FIGURE = "figure"
    MOL_ATTACHMENT = "mol_attachment"
    EXTERNAL_DATABASE = "external_database"


class SourceEnvelope(BaseModel):
    """Provenance metadata every adapter must expose (AGENTS.md §8)."""

    source_name: str
    source_version: Optional[str] = None
    dataset_version: str
    retrieved_at: datetime
    synthetic: bool = False
    warnings: list[str] = Field(default_factory=list)


class DatasetInfo(BaseModel):
    source_name: str
    dataset_version: str
    synthetic: bool
    release_label: Optional[str] = None
    files: dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    retrieved_at: datetime


class PatentFamily(BaseModel):
    id: uuid.UUID
    family_key: str
    title: Optional[str] = None


class PatentDocument(BaseModel):
    id: uuid.UUID
    publication_number: str
    family_id: uuid.UUID
    title: Optional[str] = None
    abstract: Optional[str] = None
    assignee: Optional[str] = None
    publication_date: Optional[date] = None
    jurisdiction: Optional[str] = None
    doc_type: Optional[str] = None


class Compound(BaseModel):
    """The normalized chemical entity (identity keyed by InChIKey)."""

    id: uuid.UUID
    canonical_smiles: str
    inchikey: str
    inchi: Optional[str] = None
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    hbd: Optional[int] = None
    hba: Optional[int] = None
    tpsa: Optional[float] = None
    logp: Optional[float] = None
    has_stereo: bool = False
    is_multi_component: bool = False
    scaffold: Optional[str] = None
    normalization_notes: Optional[str] = None


class CompoundMention(BaseModel):
    """A specific occurrence of a compound in a patent document.

    Patent-local labels never merge identities (PROMPT.md §2.2).
    """

    id: uuid.UUID
    compound_id: uuid.UUID
    document_id: uuid.UUID
    publication_number: Optional[str] = None
    patent_label: Optional[str] = None


class EvidenceRecord(BaseModel):
    id: uuid.UUID
    compound_id: Optional[uuid.UUID] = None
    compound_mention_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    publication_number: Optional[str] = None
    source_type: EvidenceSourceType
    section: Optional[str] = None
    page: Optional[int] = None
    table_ref: Optional[str] = None
    figure_ref: Optional[str] = None
    paragraph: Optional[str] = None
    compound_local_id: Optional[str] = None
    raw_excerpt: Optional[str] = None
    source_url: Optional[str] = None
    extraction_method: str
    provenance_state: ProvenanceState
    confidence: Optional[float] = None
    dataset_version: str
    retrieved_at: datetime


class StructureIssue(BaseModel):
    """A recorded problem with a source structure row.

    Malformed input is surfaced, never silently dropped or "fixed" into a compound.
    """

    source_record_id: str
    document_id: str
    patent_label: Optional[str] = None
    raw_smiles: str
    issue: str


class MentionRecord(BaseModel):
    """An adapter-level occurrence record before chemistry normalization."""

    mention_id: uuid.UUID
    source_record_id: str
    document_id: str
    patent_label: Optional[str] = None
    raw_smiles: str
    source_field: Optional[str] = None


class AdapterResult(BaseModel):
    """Everything an adapter returns: data + envelope + validation issues."""

    envelope: SourceEnvelope
    families: list[PatentFamily] = Field(default_factory=list)
    documents: list[PatentDocument] = Field(default_factory=list)
    mentions: list[MentionRecord] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    dataset_info: Optional[DatasetInfo] = None
    issues: list[StructureIssue] = Field(default_factory=list)


class Page(BaseModel):
    """Standard paged response envelope."""

    total: int
    offset: int
    limit: int
    items: list[Any]


# --- ONLINE-00: target scope, candidates, retrieval coverage ---------------------


class TargetType(str, enum.Enum):
    """Source-declared target type. Complexes stay distinct from the single
    protein they contain: inhibition of an interaction is not inhibition of a
    subunit binding site (ONLINE-00 A)."""

    SINGLE_PROTEIN = "single_protein"
    PROTEIN_PROTEIN_INTERACTION = "protein_protein_interaction"
    PROTEIN_COMPLEX = "protein_complex"
    NUCLEIC_ACID = "nucleic_acid"
    OTHER = "other"


class ScopeKind(str, enum.Enum):
    """Which member of a ligand/receptor/pathway system the user selected."""

    LIGAND = "ligand"
    RECEPTOR = "receptor"
    COMPLEX = "complex"
    PATHWAY = "pathway"


class EvidenceClass(str, enum.Enum):
    """Conservative evidence strength (ONLINE-00 C).

    A measured affinity is not by itself proof of inhibitory function, and a
    downstream functional readout is not proof of direct engagement; those
    distinctions survive into the stored record.
    """

    MEASURED_DIRECT_BINDING = "measured_direct_binding"
    INTERACTION_DISRUPTION = "interaction_disruption"
    FUNCTIONAL_EFFECT = "functional_effect"
    SCREENING_ASSAY = "screening_assay"
    COMPUTATIONAL_PREDICTION = "computational_prediction"
    UNSPECIFIED = "unspecified"


class RetrievalStatus(str, enum.Enum):
    """Honest per-source outcome. 'empty' never stands in for 'failed'."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    NOT_QUERIED = "not_queried"


class TargetComponent(BaseModel):
    """One protein chain of a resolved target, with its own identifiers."""

    accession: Optional[str] = None
    name: Optional[str] = None
    gene_symbol: Optional[str] = None
    role: Optional[str] = None
    organism: Optional[str] = None


class ResolvedTarget(BaseModel):
    """A stored target with its reviewed biological scope and provenance."""

    id: uuid.UUID
    target_key: str
    name: Optional[str] = None
    organism: Optional[str] = None
    taxon_id: Optional[int] = None
    uniprot_accession: Optional[str] = None
    gene_symbol: Optional[str] = None
    target_type: Optional[TargetType] = None
    scope_kind: Optional[ScopeKind] = None
    aliases: list[str] = Field(default_factory=list)
    components: list[TargetComponent] = Field(default_factory=list)
    source_name: Optional[str] = None
    dataset_version: Optional[str] = None


class ResolutionCandidate(BaseModel):
    """An alternative the resolver surfaced but the user did not select."""

    identifier: str
    name: Optional[str] = None
    organism: Optional[str] = None
    target_type: Optional[TargetType] = None
    source_name: Optional[str] = None
    reason: Optional[str] = None


class TargetResolutionRecord(BaseModel):
    """A persisted resolution run: the query, what it considered, what was
    chosen, and what was excluded with the reason (ONLINE-00 A)."""

    id: uuid.UUID
    query: str
    species: str
    status: str  # resolved | ambiguous | not_found | failed
    chosen_target_id: Optional[uuid.UUID] = None
    chosen_identifier: Optional[str] = None
    candidates: list[ResolutionCandidate] = Field(default_factory=list)
    excluded: list[ResolutionCandidate] = Field(default_factory=list)
    source_name: str
    source_version: Optional[str] = None
    retrieved_at: datetime
    notes: list[str] = Field(default_factory=list)


class AssayContext(BaseModel):
    """Everything that has to travel with a measurement for it to stay
    comparable: format, species, construct, and source validity flags."""

    assay_key: str
    assay_type: Optional[str] = None
    description: Optional[str] = None
    assay_format: Optional[str] = None
    species: Optional[str] = None
    #: Protein construct used in the assay, verbatim from the source.
    target_construct: Optional[str] = None
    variant_accession: Optional[str] = None
    variant_mutation: Optional[str] = None
    target_name: Optional[str] = None
    target_key: Optional[str] = None


class CandidateRecord(BaseModel):
    """A compound proposed for a target by one open source.

    Deliberately not a patent occurrence and not a claim of inhibition: the
    candidate exists so a compound with assay evidence but no patent mapping
    stays usable and savable (ONLINE-00 C)."""

    compound_id: uuid.UUID
    canonical_smiles: str
    inchikey: str
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    modality: Modality = Modality.UNCLASSIFIED
    modality_rule: Optional[str] = None
    modality_source: Optional[str] = None
    source_name: str
    source_record_id: str
    evidence_class: EvidenceClass = EvidenceClass.UNSPECIFIED
    patent_occurrences: int = 0
    patent_labels: list[str] = Field(default_factory=list)
    measurements: int = 0


class SourceRetrieval(BaseModel):
    """One source's outcome for one target investigation (ONLINE-00 C).

    This is the record the coverage matrix is built from: it distinguishes no
    records, no qualifying small molecules, partial retrieval, failure and
    not-queried, and it never reports a failure as an empty success."""

    id: uuid.UUID
    target_id: Optional[uuid.UUID] = None
    source_name: str
    query: dict[str, Any] = Field(default_factory=dict)
    status: RetrievalStatus
    dataset_version: Optional[str] = None
    source_version: Optional[str] = None
    pages_fetched: int = 0
    records_seen: int = 0
    records_kept: int = 0
    records_excluded: int = 0
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    latency_ms: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)
    checksum: Optional[str] = None
    retrieved_at: datetime


class TargetCandidateEntry(BaseModel):
    """One identity a source proposes for a requested target.

    A source-level proposal, before SPAgo decides: the resolver never picks a
    candidate silently, so alternatives and exclusions are returned alongside
    the one that was chosen (ONLINE-00 A)."""

    identifier: str
    identifier_kind: str  # uniprot_accession | chembl_target_id
    name: Optional[str] = None
    gene_symbol: Optional[str] = None
    #: Gene synonyms as reported by the source (recorded identities, not labels).
    synonyms: list[str] = Field(default_factory=list)
    organism: Optional[str] = None
    taxon_id: Optional[int] = None
    target_type: Optional[TargetType] = None
    reviewed: Optional[bool] = None
    components: list[TargetComponent] = Field(default_factory=list)
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class TargetLookupResult(BaseModel):
    """Outcome of one target-identity lookup, including how it went."""

    source_name: str
    query: str
    status: RetrievalStatus
    entries: list[TargetCandidateEntry] = Field(default_factory=list)
    total_found: int = 0
    truncated: bool = False
    source_version: Optional[str] = None
    retrieved_at: datetime
    warnings: list[str] = Field(default_factory=list)
