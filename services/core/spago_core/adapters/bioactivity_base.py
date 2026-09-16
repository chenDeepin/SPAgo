"""Bioactivity source contracts (Milestone 3, extended for ONLINE-00).

A measurement only stays scientifically usable if the context that makes it
comparable travels with it. `ActivityRecord` therefore carries the assay
format, species, variant/mutation, source validity flags and the conservative
evidence class, in addition to the as-reported value.

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
    #: No assay-construct field: no source adapter in this build can map one, so
    #: declaring it here would promise a context the reader never receives
    #: (ONLINE-07 D7). The unused `measurements.construct` column stays as
    #: migrated; nothing writes it and no read surfaces it.
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
    #: ONLINE-06 / B-02: what happened when this record's document reference was
    #: resolved — one of the buckets in `DOCUMENT_REFERENCE_STATUSES`. `None`
    #: means the adapter did not attempt document resolution at all, which is a
    #: third state and must not be read as "no patent". It is an outcome of the
    #: *retrieval*, so it is not stored on the measurement row; the tally is.
    document_reference_status: str | None = None
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
    #: The source's own name for the ligand (ChEMBL `molecule_pref_name`), when the
    #: payload carries it. The target path's measured projection does not request
    #: it; the patent path (B-24) does, so the name is filled there and stays
    #: `None` elsewhere rather than being invented.
    source_molecule_name: str | None = None
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
    #: B-02: how many of the *kept* records carry a source-declared patent, DOI or
    #: PMID, and why the others do not. Disjoint buckets over `records`; the
    #: codes are `DOCUMENT_REFERENCE_STATUSES`. Excluded records (no structure or
    #: no numeric value) never reach document resolution and are counted in
    #: `rejection_counts` instead, so the two tallies describe different sets.
    document_reference_counts: dict[str, int] = Field(default_factory=dict)


@runtime_checkable
class BioactivitySource(Protocol):
    """A source of compound-target activity measurements."""

    source_name: str

    def load(self) -> ActivityResult:
        """Load available activity measurements as normalized records."""
        ...
