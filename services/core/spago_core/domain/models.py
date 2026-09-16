"""Typed domain models shared across adapters, services, and the API.

These models are the normalized contract: external schemas (SureChEMBL Parquet,
future OPS/ChEMBL payloads) must never leak past the adapters.
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from spago_core.chemistry.activities import ActivityClass
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
    comparable: format, species, variant and source validity flags."""

    assay_key: str
    assay_type: Optional[str] = None
    description: Optional[str] = None
    assay_format: Optional[str] = None
    species: Optional[str] = None
    #: No construct field: no adapter can supply one in this build, so the
    #: contract does not carry it (ONLINE-07 D7; `measurements.construct` is
    #: migrated, written by nothing and read by nothing).
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
    #: ONLINE-06: the strongest class this compound's own potency measurements
    #: support under the deployment policy, plus the as-reported label of the
    #: value that decided it. Recomputed per request, never stored, so a policy
    #: change cannot leave a stale class behind.
    activity_class: ActivityClass = ActivityClass.NOT_APPLICABLE
    activity_rule: Optional[str] = None
    potency_label: Optional[str] = None
    #: Distinct sources that contributed a measurement for this compound.
    sources: list[str] = Field(default_factory=list)
    #: Publication numbers the *source* declares for this compound's records.
    #: Source-declared: not proof that SPAgo's corpus contains the compound.
    source_declared_patents: list[str] = Field(default_factory=list)
    #: True when this row is in the page only because it was asked for by id
    #: (a saved or selected compound) while the current filter excludes it — a
    #: peptide under the small-molecule scope, for example. The row is labelled,
    #: never counted as part of the filtered set (defect D2).
    outside_filter: bool = False


class ActiveCompound(BaseModel):
    """One compound whose reported potency is at or below the threshold."""

    compound_id: uuid.UUID
    inchikey: str
    potency_label: str
    standard_type: str
    value: float
    unit: str
    relation: str
    value_nm: float
    evidence_class: EvidenceClass = EvidenceClass.UNSPECIFIED
    source_name: str
    measurement_id: Optional[uuid.UUID] = None
    potential_duplicate: bool = False


class ReferencePolicy(BaseModel):
    """The stated rule a verdict was computed under (AGENTS.md §10)."""

    version: str
    threshold_nm: float
    threshold_label: str
    min_compounds: int
    #: True when the policy counts every modality the source returned. Reported
    #: explicitly so a reader never has to infer the scope from a label.
    all_modalities: bool = False
    modality_scope: str = "small molecules and unclassified entities"
    scope_note: str = ""


class ReferenceVerdict(BaseModel):
    """Whether a target's retrieved set can serve as a potency reference.

    A deterministic count under a stated policy, not a biological conclusion
    and not a claim about the literature: it says what the stored records
    support, and it separates "nothing retrieved" from "nothing potent".
    """

    target_id: uuid.UUID
    target_key: str
    target_name: Optional[str] = None
    qualifies: bool = False
    reason: str = ""
    policy: ReferencePolicy
    #: Distinct compounds in scope, and how their best measurement classifies.
    compounds: int = 0
    compounds_active: int = 0
    compounds_weak: int = 0
    compounds_unknown: int = 0
    compounds_not_applicable: int = 0
    #: Potency actives that the modality scope excludes (reported, not hidden).
    active_compounds_outside_scope: int = 0
    measurements: int = 0
    class_counts: dict[str, int] = Field(default_factory=dict)
    endpoint_counts: dict[str, int] = Field(default_factory=dict)
    evidence_class_counts: dict[str, int] = Field(default_factory=dict)
    modality_counts: dict[str, int] = Field(default_factory=dict)
    #: The best few actives, most potent first, with as-reported labels.
    actives: list[ActiveCompound] = Field(default_factory=list)
    best_active: Optional[ActiveCompound] = None
    potential_duplicates: int = 0
    #: Source records that carried a value but no public structure (from the
    #: retrieval records), so a thin set is not read as a negative result.
    records_without_structure: int = 0
    #: User-added literature rows that carry a value but no public structure
    #: (ONLINE-07). Counted separately from `records_without_structure`: one is a
    #: source that could not supply a structure, the other is a person who added a
    #: claim without one.
    supplement_remarks: int = 0
    #: ONLINE-08: hand-added rows the user took back, reported next to the counts
    #: instead of an unexplained gap.
    withdrawn_supplements: int = 0
    #: B-25: rows a bundle proposed (an agent or a script) that no person has
    #: confirmed yet. They are stored and readable, and they are *not* in any count
    #: above — a proposal must not move a verdict before a human reads it.
    unreviewed_supplements: int = 0
    source_declared_patents: list[str] = Field(default_factory=list)
    truncated: bool = False


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
    #: B-02: how the source-declared document reference resolved for this
    #: retrieval, over the kept records — a disjoint tally whose sum is
    #: `records_kept`. Empty means "not recorded for this run" (a retrieval stored
    #: before migration 0016), which must not be rendered as zero. Codes are in
    #: `spago_core.domain.document_refs`.
    reference_counts: dict[str, int] = Field(default_factory=dict)
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


# --- ONLINE-07: manually added literature rows ------------------------------------

#: The `source_name` every user-added row carries. It is part of the contract: the
#: measurement's provenance state is `user_curated`, and nothing may rewrite either
#: to look like a database fact (AGENTS.md §10).
USER_SUPPLEMENT_SOURCE = "user_supplement"

#: Rows one import may carry. The bound is a contract, not a hint: it is refused,
#: never silently truncated.
MAX_SUPPLEMENT_ROWS = 200


class SupplementRow(BaseModel):
    """One literature/patent row a user adds by hand (ONLINE-07).

    Every field is the user's own statement, including the potency as reported. The
    note is what makes the row auditable, so it is *required*: a default note would
    assert a provenance check the user may not have made (AGENTS.md §10). A row with
    no SMILES is kept as a structure-less remark rather than dropped.
    """

    model_config = {"extra": "forbid"}

    #: What the row is called in the source (paper compound number, patent label).
    name: str = Field(min_length=1, max_length=300)
    #: Mandatory provenance: where the reader can check this row.
    note: str = Field(min_length=1, max_length=2000)
    smiles: Optional[str] = Field(default=None, max_length=4000)
    activity_type: Optional[str] = Field(default=None, max_length=40)
    value: Optional[float] = None
    unit: Optional[str] = Field(default=None, max_length=20)
    relation: str = Field(default="=", max_length=3)
    doi: Optional[str] = Field(default=None, max_length=200)
    pmid: Optional[str] = Field(default=None, max_length=20)
    patent_number: Optional[str] = Field(default=None, max_length=40)
    #: Optional identity assertion by the producer (B-25). Checked against the
    #: structure SPAgo computes, never trusted: a disagreement refuses the row,
    #: because a row whose stated identity and drawn structure differ would be a
    #: structure nobody can vouch for (§11).
    inchikey: Optional[str] = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _a_value_states_its_endpoint(self) -> "SupplementRow":
        if self.value is not None and not (self.activity_type and self.unit):
            raise ValueError(
                "a row that carries a value must state its activity_type and unit "
                "(a number without an endpoint cannot be classified or compared)"
            )
        if self.value is None and (self.activity_type or self.unit):
            raise ValueError(
                "activity_type/unit were given without a value; state the value or "
                "drop the endpoint"
            )
        return self


class SupplementRowOutcome(BaseModel):
    """What happened to one submitted row, stated per row and per reason."""

    index: int
    #: `measurement` (stored with a structure), `remark` (stored without a
    #: structure) or `rejected` (not stored, with the reason).
    status: Literal["measurement", "remark", "rejected"]
    name: str = ""
    #: The id the API accepts for `…/supplements/{record_id}/withdraw`, so the
    #: dialog can offer the action for the row it just stored (defect D3).
    record_id: Optional[str] = None
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    activity_class: Optional[ActivityClass] = None
    #: True when the structure was already in the corpus under this identity.
    reused_compound: bool = False
    #: Rejection reasons, or notes about how the row was stored.
    reasons: list[str] = Field(default_factory=list)


class SupplementImport(BaseModel):
    """Result of one import: what was accepted, what was not, and why."""

    target_id: uuid.UUID
    received: int = 0
    measurements: int = 0
    remarks: int = 0
    compounds_created: int = 0
    compounds_reused: int = 0
    #: True when a re-posted identical row updated an existing row instead of
    #: creating a second copy of the same literature claim.
    updated: int = 0
    rows: list[SupplementRowOutcome] = Field(default_factory=list)


class WithdrawnSupplement(BaseModel):
    """A hand-added row the user took back, kept readable (defect D3).

    Both kinds are one shape here because a reader asks one question — what did I
    take back, when, and why — and the answer must not depend on whether the row
    carried a structure.
    """

    kind: Literal["measurement", "remark"]
    #: The id the API accepts for a withdrawal (and for re-posting the row).
    record_id: str
    name: str = ""
    note: Optional[str] = None
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    retracted_at: datetime
    retracted_reason: Optional[str] = None
    #: True when the compound also left the investigation's candidate list.
    candidate_retracted: bool = False


class WithdrawalResult(BaseModel):
    """Outcome of one withdrawal: what was taken back, and what stayed."""

    #: "measurement" (a row with a structure) or "remark" (a row without one).
    kind: Literal["measurement", "remark"]
    #: Echoed back so a caller can act on the row it just took back, and so a
    #: re-post of the same row is recognisable as a restore rather than a copy.
    record_id: str
    reason: str
    compound_id: Optional[str] = None
    #: True when the compound also left the investigation's candidate list.
    candidate_retracted: bool = False


class SupplementRemark(BaseModel):
    """A stored structure-less literature row (its own table, not a compound)."""

    id: uuid.UUID
    target_id: uuid.UUID
    source_record_id: str
    name: str
    note: str
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    patent_number: Optional[str] = None
    provenance_state: ProvenanceState = ProvenanceState.USER_CURATED
    created_at: datetime
    #: Set when the user takes the row back. The row stays readable: what was
    #: withdrawn, when and why is part of the record (migration 0015).
    retracted_at: Optional[datetime] = None
    retracted_reason: Optional[str] = None


# --- B-25: a bundle of rows, and the review that admits it -----------------------

#: The bundle schema version. Refused when it does not match, so an old file cannot be
#: read as if it meant something it does not.
SUPPLEMENT_BUNDLE_VERSION = 1


class SupplementBundle(BaseModel):
    """A file of literature rows with the run that produced it (B-25).

    The envelope is the difference between a set of rows and an *artifact*: it states
    who or what produced the rows, what was searched, and when — the note AGENTS.md §12
    requires of agent-assisted retrieval. A bare JSON list is refused on purpose, so a
    producer learns the shape instead of having rows arrive with no provenance.

    ``produced_by_kind`` decides how the rows are stored, and that is the whole point:
    a bundle a person wrote is their own statement (``user_curated``), a bundle an agent
    or a script wrote is a **proposal** that a human confirms as a separate, recorded
    action. Nothing here interprets the rows; classes are computed on read.
    """

    model_config = {"extra": "forbid"}

    bundle_version: int = Field(default=SUPPLEMENT_BUNDLE_VERSION)
    #: Who or what produced these rows (free text: a person, a model, a tool).
    produced_by: str = Field(min_length=1, max_length=300)
    #: `human` — the producer's own reading; `agent` — a model proposed them;
    #: `external` — a script or another tool wrote them.
    produced_by_kind: Literal["human", "agent", "external"]
    #: What was searched, in the producer's own words ("PubMed + Google Patents;
    #: queries: TSLP inhibitor, ..."). Required: a reader must be able to re-find
    #: the rows, and a search that cannot be stated was not a search.
    searched: str = Field(min_length=1, max_length=2000)
    #: As stated by the producer; free text, never parsed into a date the file did
    #: not claim.
    generated_at: Optional[str] = Field(default=None, max_length=100)
    #: Optional identity guard: when given, it must match the endpoint's target, or
    #: the whole bundle is refused. This is how an agent's file for one target cannot
    #: be imported into another by accident.
    uniprot: Optional[str] = Field(default=None, max_length=40)
    #: The rows themselves, in any of the accepted shapes (see the alias table).
    records: list[dict] = Field(default_factory=list, max_length=MAX_SUPPLEMENT_ROWS)

    @model_validator(mode="after")
    def _a_bundle_says_what_it_is(self) -> "SupplementBundle":
        if self.bundle_version != SUPPLEMENT_BUNDLE_VERSION:
            raise ValueError(
                f"bundle_version {self.bundle_version} is not supported "
                f"(this build reads version {SUPPLEMENT_BUNDLE_VERSION})"
            )
        if not self.records:
            raise ValueError("a bundle must carry at least one record")
        return self


class SupplementImportReport(BaseModel):
    """The stored record of one import: the run, what it refused, and its review state.

    ``provenance_state`` is what the rows were stored with. Anything but
    ``user_curated`` means the rows are proposals: stored, readable, counted
    separately, and **not part of the investigation** until ``confirmed_at`` is set.
    """

    id: uuid.UUID
    target_id: uuid.UUID
    bundle_hash: str
    bundle_version: int
    produced_by: str
    produced_by_kind: Literal["human", "agent", "external"]
    searched: str
    generated_at: Optional[str] = None
    received: int = 0
    measurements: int = 0
    remarks: int = 0
    rejected: int = 0
    compounds_created: int = 0
    compounds_reused: int = 0
    updated_rows: int = 0
    record_ids: list[str] = Field(default_factory=list)
    outcomes: list[SupplementRowOutcome] = Field(default_factory=list)
    provenance_state: ProvenanceState
    submitted_by: Optional[str] = None
    created_at: datetime
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    #: Set when this exact bundle (same hash) was imported for this target before,
    #: so a repeated import is visibly a repeat rather than a surprise.
    repeated_of: Optional[uuid.UUID] = None
    #: The current stored state of this import's rows. Read back rather than
    #: remembered: a row may have been withdrawn since, and the report must show that.
    stored: list["SuppliedRowState"] = Field(default_factory=list)


class SuppliedRowState(BaseModel):
    """One stored row of an import, as it stands now.

    Both kinds (measurement / remark) share this shape because the reviewer's question
    is one question — what is stored, under which provenance, and is it still live —
    and it must not depend on whether the row carried a structure.
    """

    kind: Literal["measurement", "remark"]
    record_id: str
    name: str = ""
    note: Optional[str] = None
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    patent_number: Optional[str] = None
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    #: The row's class under the deployment policy, computed on read — never stored.
    activity_class: Optional[ActivityClass] = None
    activity_class_rule: Optional[str] = None
    #: False once the row has been taken back (it stays readable).
    live: bool = True
    retracted_at: Optional[datetime] = None
    retracted_reason: Optional[str] = None


class SupplementBundleImport(BaseModel):
    """What one bundle import did: the run's report plus the per-row answers."""

    report: SupplementImportReport
    #: True when the report's rows are proposals that no human has confirmed yet.
    awaiting_review: bool = False


class SupplementConfirmation(BaseModel):
    """The recorded act of a human admitting an import's rows to the investigation."""

    import_id: uuid.UUID
    target_id: uuid.UUID
    #: How many stored rows this confirmation covered (measurements + remarks).
    rows: int = 0
    #: Candidates created by this confirmation (one per live compound of the import).
    candidates_created: int = 0
    confirmed_at: datetime
    confirmed_by: Optional[str] = None
    #: True when the import had already been confirmed: answering "already confirmed"
    #: is not the same as writing a second confirmation (AGENTS.md §22).
    already_confirmed: bool = False


# --- B-26: what is stored for a publication, and what nobody asked ---------------

#: Version of the coverage rule. It travels with every row, report and export, so a
#: changed precedence is visible in the artifact rather than hidden in a session.
COVERAGE_RULE = "patent-coverage-v1"

#: How many publications one audit request may carry (§13: bounded work per request).
MAX_COVERAGE_PUBLICATIONS = 50

#: What one leg of the audit can say. `has_records` is the only state that means
#: "SPAgo holds something here"; `asked_empty` and `failed` are different answers, and
#: `not_queried` is not an answer at all (AGENTS.md §11).
CoverageLegState = Literal["has_records", "unconfirmed", "asked_empty", "failed", "not_queried"]

#: The headline for a publication. The first four name the strongest stored answer and
#: its leg; the last three are the absence of an answer, kept apart.
CoverageStatus = Literal[
    "corpus", "declared", "supplement", "proposed", "empty", "failed", "not_queried"
]


class CoverageAnswer(BaseModel):
    """One stored answer inside a leg, labelled by the path that stored it.

    Answers are kept per path and per source rather than merged into one status:
    a source-declared set reached from the publication (B-24), a row a source
    already declared for a target (B-02), and a person's own addition (B-25) are
    three different facts (AGENTS.md §10/§11), and a merged status would hide a
    failed ask behind a word like "covered".
    """

    #: Which stored path answered: the corpus read, a per-publication source
    #: lookup, a target-led retrieval, or the hand-added rows.
    kind: Literal["corpus", "patent_source_lookup", "target_led_source", "hand_added"]
    #: The external source, where the path has one (`chembl`); the corpus and the
    #: hand-added rows are not a source's answer and leave it empty.
    source_name: Optional[str] = None
    state: CoverageLegState
    #: The stored status word of the underlying record (`complete` / `partial` /
    #: `empty` / `failed`, or a short corpus/hand-added label), never a new one.
    status: str
    records: int = 0
    compounds: int = 0
    #: Stored rows no person has confirmed (B-25 proposals) — readable, not coverage.
    unconfirmed_records: int = 0
    match_rule: Optional[str] = None
    source_version: Optional[str] = None
    dataset_version: Optional[str] = None
    #: When the ask happened (for a failed lookup: when the failed attempt was stored).
    retrieved_at: Optional[datetime] = None
    #: When the shown rows were retrieved — different from `retrieved_at` after a
    #: failed ask, because a failed lookup keeps the last successful set.
    rows_retrieved_at: Optional[datetime] = None
    #: One sentence naming what this answer read, recheckable against the tables.
    detail: str


class CoverageLeg(BaseModel):
    """What one path holds for one publication, with its own state and counts.

    Legs are never summed: a corpus occurrence, a source-declared compound and a
    hand-added row are three different facts (AGENTS.md §10/§11), and the report
    keeps them in separate fields, columns and labels. A leg's state is the
    strongest state among its answers (`has_records` > `failed` > `unconfirmed` >
    `asked_empty` > `not_queried`), so a leg that was asked and failed never reads
    as one that was never asked.
    """

    leg: Literal["corpus", "declared", "supplement"]
    state: CoverageLegState
    #: Live rows stored under this leg for this publication, across its answers.
    records: int = 0
    #: Distinct compounds, where the leg's rows carry a structure.
    compounds: int = 0
    #: Stored rows no person has confirmed (B-25 proposals). Only the supplement
    #: leg can have them.
    unconfirmed_records: int = 0
    #: Distinct targets whose investigation the rows belong to (supplement leg).
    targets: int = 0
    #: One sentence naming what this leg read, recheckable against the tables.
    detail: str
    answers: list[CoverageAnswer] = Field(default_factory=list)


class PublicationCoverage(BaseModel):
    """One publication's audit row: three legs and the headline they add up to."""

    #: Exactly what the caller asked for.
    requested: str
    #: The identifier the corpus stores for the same publication, when it holds one.
    matched: Optional[str] = None
    #: The normalized tokens the declared and supplement legs compare on.
    normalized: list[str] = Field(default_factory=list)
    in_corpus: bool = False
    family_id: Optional[uuid.UUID] = None
    family_key: Optional[str] = None
    doc_type: Optional[str] = None
    #: Other stored identifiers the request also matches: reported, never chosen
    #: between (the same rule `find_patent` follows).
    ambiguous: list[str] = Field(default_factory=list)
    status: CoverageStatus
    status_rule: str
    #: Why the headline is what it is, in the legs' own terms.
    status_reason: str
    #: Legs that were never asked and could still add records — so `empty` is never
    #: read as "nothing exists".
    unqueried: list[Literal["corpus", "declared", "supplement"]] = Field(default_factory=list)
    legs: list[CoverageLeg] = Field(default_factory=list)


class CoverageReport(BaseModel):
    """The audit for a bounded set of publications, computed on read (never stored)."""

    rule: str
    rule_text: str
    generated_at: datetime
    publications: list[PublicationCoverage] = Field(default_factory=list)
    #: Headline status → how many publications, plus this report's own counts
    #: (`publications`, `not_fully_asked`, `failed_legs`, `ambiguous`).
    totals: dict[str, int] = Field(default_factory=dict)
    #: Report-level statements a reader needs: what this audit cannot see, and any leg
    #: whose ask did not complete.
    notes: list[str] = Field(default_factory=list)
