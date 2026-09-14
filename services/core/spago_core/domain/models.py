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
