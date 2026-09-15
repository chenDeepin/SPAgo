"""Bioactivity source contracts (Milestone 3, extended for ONLINE-00).

A measurement only stays scientifically usable if the context that makes it
comparable travels with it. `ActivityRecord` therefore carries the assay
format, species, construct/mutation, source validity flags and the
conservative evidence class, in addition to the as-reported value.

Values stay as-reported (`standard_type`, unit, relation, and the raw text);
cross-assay ranking and selectivity maths are intentionally absent — assay
conditions must match before values are comparable (ONLINE-00 C).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from spago_core.domain import EvidenceClass, SourceEnvelope


class ActivityRecord(BaseModel):
    """A normalized measurement with its assay context."""

    source_record_id: str
    compound_source_id: str
    target_key: str
    target_name: str | None = None
    assay_key: str
    assay_type: str | None = None
    standard_type: str
    value: float
    unit: str
    relation: str = "="

    # --- ONLINE-00 additions (all optional: legacy adapters stay valid) --------
    #: Conservative evidence class. Never defaulted to direct binding.
    evidence_class: EvidenceClass = EvidenceClass.UNSPECIFIED
    #: As-reported value before relation stripping, for auditability.
    raw_value: str | None = None
    assay_description: str | None = None
    assay_format: str | None = None
    species: str | None = None
    #: Protein construct used in the assay, verbatim from the source.
    target_construct: str | None = None
    variant_accession: str | None = None
    variant_mutation: str | None = None
    #: Normalized potency, only when the source supplies one.
    pchembl_value: float | None = None
    #: Source-declared duplicate/validity information, preserved verbatim.
    potential_duplicate: bool = False
    validity_comment: str | None = None
    source_confidence: float | None = None
    #: DOI / PMID / patent reference supplied by the source.
    document_ref: str | None = None
    #: ONLINE-06: the same reference decomposed, when the source supplies it on
    #: the document rather than on the activity row. `document_patent_number` is
    #: *normalized* (country + digits, kind code and separators dropped) so it
    #: can be matched against a corpus value that formats it differently; it
    #: stays source-declared and never becomes corpus evidence on its own.
    document_patent_number: str | None = None
    document_doi: str | None = None
    document_pmid: str | None = None
    source_url: str | None = None
    assay_type_name: str | None = None
    #: Modality as declared by the source for this ligand, if any.
    modality_declared: str | None = None
    #: Source-declared type of the assayed target (single protein, interaction,
    #: complex). Kept so a measurement against an interaction is never read as a
    #: binding site on one partner (ONLINE-00 A).
    target_type_declared: str | None = None
    #: SMILES as reported by the source (identity resolution happens outside).
    raw_smiles: str | None = None
    #: Stable external molecule identifier (ChEMBL id, CID, BindingDB monomer).
    source_molecule_id: str | None = None
    #: ONLINE-06: the source that produced this record, and the dataset release
    #: it came from. One investigation reads several sources, so recording the
    #: *target's* resolver source on every measurement misattributes the datum
    #: (AGENTS.md §8/§25). Optional so a legacy adapter stays valid; the service
    #: falls back to the target's provenance and never invents a source.
    source_name: str | None = None
    source_dataset_version: str | None = None


class ActivityResult(BaseModel):
    envelope: SourceEnvelope
    records: list[ActivityRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: How the retrieval actually went, so a caller can record partial/empty/
    #: failed honestly instead of inferring from an empty record list.
    status: str = "complete"
    pages_fetched: int = 0
    records_seen: int = 0
    records_excluded: int = 0
    rejection_counts: dict[str, int] = Field(default_factory=dict)


@runtime_checkable
class BioactivitySource(Protocol):
    """A source of compound-target activity measurements."""

    source_name: str

    def load(self) -> ActivityResult:
        """Load available activity measurements as normalized records."""
        ...
