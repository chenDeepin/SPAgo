"""ChEMBL target-led discovery adapter (ONLINE-00 B).

Two responsibilities, both bounded:

1. **Target identity** — map a UniProt accession or a name to ChEMBL target
   ids via `target.json?target_components__accession=...`. Verified against the
   live service on 2026-09-15: Q969D9 → CHEMBL3712931 (single protein) while
   P29965 → CHEMBL3580491 (CD40 ligand) *and* CHEMBL4106122 (CD40-CD40L
   protein–protein interaction). Those are different scientific objects and are
   returned as separate candidates, never merged.

2. **Activities** — fetch every activity for a resolved target id with
   pagination, keeping the assay context and classifying the evidence
   conservatively. Unmapped compounds are *kept*: unlike the M3 adapter, this
   path exists precisely to discover candidates that no patent package has
   mapped yet.

Evidence classification uses structured fields only (assay type, standard type,
target type). No keyword analysis of assay descriptions: the description is
preserved verbatim so a scientist can judge it, and the class recorded is the
weakest reading the structured fields support.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.adapters.http import SourceClient, SourceUnavailableError
from spago_core.domain import (
    EvidenceClass,
    RetrievalStatus,
    SourceEnvelope,
    TargetCandidateEntry,
    TargetLookupResult,
    TargetType,
)
from spago_core.domain.patent_numbers import normalize_patent_number

SOURCE_NAME = "chembl"
SOURCE_VERSION = "chembl-web-services"
EXTRACTION_METHOD = "chembl_webclient"

TARGET_PATH = "/chembl/api/data/target.json"
ACTIVITY_PATH = "/chembl/api/data/activity.json"
DOCUMENT_PATH = "/chembl/api/data/document.json"

PAGE_LIMIT = 200
DEFAULT_MAX_ACTIVITIES = 2000
DEFAULT_MAX_MOLECULE_LOOKUPS = 25
#: Document metadata is fetched for the distinct documents a page of activities
#: cites. Both bounds are hard: a target with thousands of documents cannot turn
#: one investigation into an unbounded crawl (AGENTS.md §16/§21).
DOCUMENT_BATCH = 50
MAX_DOCUMENT_LOOKUPS = 8
#: Only the fields the product uses. A document record carries a full citation;
#: requesting the subset keeps the response small and the stored facts typed.
DOCUMENT_FIELDS = "document_chembl_id,patent_id,doi,pubmed_id,year,doc_type"

#: Only the fields `_to_record` maps. ChEMBL returns 47 keys per activity; the
#: subset cuts the payload, and every field below was verified present in the
#: projected response before this was adopted (2026-09-16, `CHEMBL3712931`,
#: `limit=200`: 216,632 → 127,415 bytes, -41% per page). A field the product
#: starts using must be added here or it will silently read as absent.
ACTIVITY_FIELDS = (
    "activity_id,canonical_smiles,standard_value,standard_type,standard_units,"
    "standard_relation,assay_type,assay_chembl_id,assay_description,bao_label,"
    "assay_variant_accession,assay_variant_mutation,molecule_chembl_id,"
    "document_chembl_id,target_chembl_id,target_pref_name,target_organism,"
    "pchembl_value,potential_duplicate,data_validity_comment,type,modality"
)

#: ChEMBL `target_type` strings → the normalized vocabulary. A
#: protein–protein interaction stays distinct from the single protein it is
#: built from (ONLINE-00 A).
_TARGET_TYPE_MAP = {
    "single protein": TargetType.SINGLE_PROTEIN,
    "protein-protein interaction": TargetType.PROTEIN_PROTEIN_INTERACTION,
    "protein complex": TargetType.PROTEIN_COMPLEX,
    "macromolecule": TargetType.PROTEIN_COMPLEX,
    "protein family": TargetType.PROTEIN_COMPLEX,
    "nucleic acid": TargetType.NUCLEIC_ACID,
    "oligonucleotide": TargetType.NUCLEIC_ACID,
    "cell line": TargetType.OTHER,
    "tissue": TargetType.OTHER,
    "organism": TargetType.OTHER,
}

#: Assay types: B = binding, F = functional, A = ADME, T = toxicity,
#: P = physicochemical, U = unclassified.
_BINDING_ASSAY_TYPES = {"B", "F"}

#: Affinity/kinetic endpoints: these are the values that can support a
#: potency statement *within their own assay*.
_AFFINITY_TYPES = {
    "kd", "ki", "k", "kon", "koff", "k_on", "k_off", "ic50", "ec50", "ac50",
    "potency", "kd_app", "ki_app", "dissociation constant", "inhibition constant",
}
#: Percent/inhibition readouts: a functional or primary-screen endpoint, never
#: by itself evidence of direct binding.
_FUNCTIONAL_TYPES = {
    "inhibition", "activity", "% ctrl", "% inhibition", "% inhibition of control",
    "residual activity", "ratio", "percent effect", "effect",
}


def map_target_type(raw: Optional[str]) -> TargetType:
    return _TARGET_TYPE_MAP.get((raw or "").strip().lower(), TargetType.OTHER)


def classify_evidence(
    assay_type: Optional[str],
    standard_type: Optional[str],
    target_type: Optional[TargetType],
) -> EvidenceClass:
    """Conservative evidence class from structured fields only.

    - An affinity/kinetic endpoint in a binding or functional assay is a
      measured direct interaction, *unless* the resolved target is itself an
      interaction or complex — then the measurement describes that interaction
      being modulated, not a binding site on one partner.
    - A percent/inhibition readout is a functional or primary-screen effect and
      is never upgraded to direct binding.
    - Anything else stays unspecified.
    """
    standard = (standard_type or "").strip().lower()
    assay = (assay_type or "").strip().upper()
    is_interaction_target = target_type in (
        TargetType.PROTEIN_PROTEIN_INTERACTION,
        TargetType.PROTEIN_COMPLEX,
    )

    if standard in _AFFINITY_TYPES and assay in _BINDING_ASSAY_TYPES:
        return (
            EvidenceClass.INTERACTION_DISRUPTION
            if is_interaction_target
            else EvidenceClass.MEASURED_DIRECT_BINDING
        )
    if standard in _FUNCTIONAL_TYPES:
        return (
            EvidenceClass.INTERACTION_DISRUPTION
            if is_interaction_target
            else EvidenceClass.FUNCTIONAL_EFFECT
        )
    return EvidenceClass.UNSPECIFIED


def _relation(value: Optional[str]) -> str:
    text = (value or "").strip()
    return text if text in {"=", "<", ">", "~", "<=", ">="} else "="


class ChEMBLDiscoveryAdapter:
    """Target-led discovery: resolve targets, then fetch their activities."""

    source_name = SOURCE_NAME
    extraction_method = EXTRACTION_METHOD

    def __init__(
        self,
        client: Optional[SourceClient] = None,
        max_activities: int = DEFAULT_MAX_ACTIVITIES,
        max_molecule_lookups: int = DEFAULT_MAX_MOLECULE_LOOKUPS,
        max_document_lookups: int = MAX_DOCUMENT_LOOKUPS,
    ) -> None:
        self.client = client or SourceClient(
            source_name=SOURCE_NAME,
            base_url="https://www.ebi.ac.uk",
            min_interval_s=0.15,
            timeout_s=30.0,
        )
        self.max_activities = max_activities
        self.max_molecule_lookups = max_molecule_lookups
        self.max_document_lookups = max_document_lookups
        self._molecule_cache: dict[str, dict] = {}
        self._document_cache: dict[str, Optional[dict]] = {}

    # -- 1. target identity ---------------------------------------------------

    def targets_for_accession(self, accession: str) -> TargetLookupResult:
        """Every ChEMBL target whose components include this UniProt accession."""
        query = (accession or "").strip()
        retrieved_at = datetime.now(timezone.utc)
        if not query:
            return TargetLookupResult(
                source_name=SOURCE_NAME,
                query=query,
                status=RetrievalStatus.EMPTY,
                retrieved_at=retrieved_at,
                warnings=["Empty accession."],
            )
        try:
            payload = self.client.get_json(
                TARGET_PATH,
                params={"target_components__accession": query, "limit": 50},
            )
        except SourceUnavailableError as exc:
            return TargetLookupResult(
                source_name=SOURCE_NAME,
                query=query,
                status=RetrievalStatus.FAILED,
                retrieved_at=retrieved_at,
                warnings=[str(exc)],
            )

        entries: list[TargetCandidateEntry] = []
        for target in payload.get("targets") or []:
            target_id = target.get("target_chembl_id")
            if not target_id:
                continue
            notes: list[str] = []
            components = []
            for component in target.get("target_components") or []:
                accessions = component.get("accession")
                if isinstance(accessions, str):
                    accessions = [accessions]
                notes.append(
                    "component: "
                    + (component.get("component_description") or component.get("component_id") or "?")
                    + (f" ({accessions[0]})" if accessions else "")
                )
                from spago_core.domain import TargetComponent

                components.append(
                    TargetComponent(
                        accession=accessions[0] if accessions else None,
                        name=component.get("component_description"),
                        organism=component.get("organism"),
                        role="component",
                    )
                )
            entries.append(
                TargetCandidateEntry(
                    identifier=target_id,
                    identifier_kind="chembl_target_id",
                    name=target.get("pref_name"),
                    organism=target.get("organism"),
                    taxon_id=target.get("tax_id"),
                    target_type=map_target_type(target.get("target_type")),
                    components=components,
                    source_name=SOURCE_NAME,
                    source_url=f"https://www.ebi.ac.uk/chembl/target_report_card/{target_id}/",
                    notes=notes,
                )
            )

        total = int((payload.get("page_meta") or {}).get("total_count") or len(entries))
        return TargetLookupResult(
            source_name=SOURCE_NAME,
            query=query,
            status=RetrievalStatus.EMPTY if not entries else RetrievalStatus.COMPLETE,
            entries=entries,
            total_found=total,
            truncated=total > len(entries),
            source_version=SOURCE_VERSION,
            retrieved_at=retrieved_at,
        )

    # -- 2. molecule context --------------------------------------------------

    def molecule(self, molecule_chembl_id: str) -> Optional[dict]:
        """Bounded, cached molecule lookup for source-declared modality.

        Returns None when the lookup is skipped or fails: modality then falls
        back to the deterministic structure rules, and `None` must never be
        read as evidence that a molecule is drug-like.
        """
        if not molecule_chembl_id:
            return None
        if molecule_chembl_id in self._molecule_cache:
            return self._molecule_cache[molecule_chembl_id]
        if len(self._molecule_cache) >= self.max_molecule_lookups:
            return None
        try:
            payload = self.client.get_json(
                f"/chembl/api/data/molecule/{molecule_chembl_id}.json"
            )
        except SourceUnavailableError:
            return None
        self._molecule_cache[molecule_chembl_id] = payload
        return payload

    # -- 3. document references (patent / DOI / PMID) -------------------------

    def documents(self, document_ids: Iterable[str]) -> tuple[dict[str, dict], list[str]]:
        """Bounded, cached document metadata for ChEMBL document ids.

        The activity payload carries `document_chembl_id` only, so without this
        step a discovered compound cannot be connected to the patent it was
        reported in — the relation this product is built around. Requests are
        batched and bounded; a failure returns what was already collected plus a
        warning, never a fabricated identifier.

        Returns ``(metadata_by_id, warnings)``. Only documents that answered are
        present in the mapping: a missing key means "unknown", not "no patent".
        """
        wanted = [str(doc) for doc in document_ids if doc]
        unique: list[str] = []
        seen: set[str] = set()
        for doc in wanted:
            if doc not in seen:
                seen.add(doc)
                unique.append(doc)

        metadata: dict[str, dict] = {}
        missing = [doc for doc in unique if doc not in self._document_cache]
        warnings: list[str] = []
        requests_made = 0

        for start in range(0, len(missing), DOCUMENT_BATCH):
            if requests_made >= self.max_document_lookups:
                warnings.append(
                    f"Document metadata lookup stopped at the configured bound of "
                    f"{self.max_document_lookups} request(s); patent/DOI references for "
                    f"{len(missing) - start} further document(s) were not retrieved."
                )
                break
            batch = missing[start : start + DOCUMENT_BATCH]
            requests_made += 1
            try:
                payload = self.client.get_json(
                    DOCUMENT_PATH,
                    params={
                        "document_chembl_id__in": ",".join(batch),
                        "only": DOCUMENT_FIELDS,
                    },
                )
            except SourceUnavailableError as exc:
                warnings.append(
                    f"Document metadata unavailable ({exc}); patent/DOI references are "
                    "missing for this retrieval, which is not a statement that none exist."
                )
                break
            answered = set()
            for document in payload.get("documents") or []:
                doc_id = document.get("document_chembl_id")
                if not doc_id:
                    continue
                answered.add(doc_id)
                self._document_cache[doc_id] = document
                metadata[doc_id] = document
            # A batch response omits ids it does not know; remember that so the
            # next call in the same investigation does not re-ask for them.
            for doc_id in batch:
                if doc_id not in answered:
                    self._document_cache[doc_id] = None

        for doc_id in unique:
            cached = self._document_cache.get(doc_id)
            if cached:
                metadata[doc_id] = cached
        return metadata, warnings

    def _attach_document_references(
        self, records: list[ActivityRecord], warnings: list[str]
    ) -> None:
        """Fill patent/DOI/PMID on each record from its document's metadata."""
        document_ids = [record.document_ref for record in records if record.document_ref]
        if not document_ids:
            return
        metadata, doc_warnings = self.documents(document_ids)
        warnings.extend(doc_warnings)
        if not metadata:
            return
        for record in records:
            document = metadata.get(record.document_ref or "")
            if not document:
                continue
            record.document_patent_number = (
                normalize_patent_number(document.get("patent_id")) or None
            )
            record.document_doi = document.get("doi") or None
            record.document_pmid = (
                str(document["pubmed_id"]) if document.get("pubmed_id") else None
            )

    # -- 4. activities --------------------------------------------------------

    def activities(
        self,
        target_chembl_id: str,
        target_type: Optional[TargetType] = None,
    ) -> ActivityResult:
        """Fetch activities for one resolved ChEMBL target.

        Every activity is kept when it carries a structure and a numeric
        standard value; nothing is silently dropped. Records excluded for a
        missing structure or value are counted and reported so the caller can
        distinguish "no qualifying small molecules" from "nothing retrieved".
        """
        retrieved_at = datetime.now(timezone.utc)
        dataset_version = f"chembl:{retrieved_at.date().isoformat()}"
        warnings: list[str] = []
        records: list[ActivityRecord] = []
        rejection_counts: dict[str, int] = {}
        seen = 0
        excluded = 0
        pages = 0

        def reject(reason: str) -> None:
            nonlocal excluded
            excluded += 1
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

        status = RetrievalStatus.COMPLETE
        offset = 0
        while len(records) < self.max_activities:
            try:
                payload = self.client.get_json(
                    ACTIVITY_PATH,
                    params={
                        "target_chembl_id": target_chembl_id,
                        "limit": PAGE_LIMIT,
                        "offset": offset,
                        # Projected to the mapped fields; see ACTIVITY_FIELDS.
                        "only": ACTIVITY_FIELDS,
                    },
                )
            except SourceUnavailableError as exc:
                warnings.append(str(exc))
                status = RetrievalStatus.PARTIAL if records or pages else RetrievalStatus.FAILED
                break

            pages += 1
            page_meta = payload.get("page_meta") or {}
            total = int(page_meta.get("total_count") or 0)
            batch = payload.get("activities") or []
            if not batch:
                break

            for activity in batch:
                seen += 1
                if len(records) >= self.max_activities:
                    break
                record = self._to_record(activity, target_type, reject)
                if record is not None:
                    records.append(record)

            offset += PAGE_LIMIT
            if offset >= total:
                break

        if status == RetrievalStatus.COMPLETE and len(records) >= self.max_activities:
            warnings.append(
                f"Activity retrieval stopped at the configured bound of "
                f"{self.max_activities} records for {target_chembl_id}; the target has more."
            )
            status = RetrievalStatus.PARTIAL
        if status == RetrievalStatus.COMPLETE and not records:
            status = RetrievalStatus.EMPTY

        # Patent/DOI/PMID live on the document, not the activity: resolve them
        # once per distinct document so a discovered compound can be linked to
        # the patent it was reported in (ONLINE-06).
        self._attach_document_references(records, warnings)

        # Each record carries the source and release it actually came from, so a
        # stored measurement is never attributed to the resolver's source.
        for record in records:
            record.source_name = SOURCE_NAME
            record.source_dataset_version = dataset_version

        return ActivityResult(
            envelope=SourceEnvelope(
                source_name=SOURCE_NAME,
                source_version=SOURCE_VERSION,
                dataset_version=dataset_version,
                retrieved_at=retrieved_at,
                synthetic=False,
                warnings=warnings,
            ),
            records=records,
            warnings=warnings,
            status=status.value,
            pages_fetched=pages,
            records_seen=seen,
            records_excluded=excluded,
            rejection_counts=rejection_counts,
        )

    def _to_record(self, activity: dict, target_type, reject) -> Optional[ActivityRecord]:
        raw_smiles = (activity.get("canonical_smiles") or "").strip()
        if not raw_smiles:
            reject("missing_structure")
            return None
        value_raw = activity.get("standard_value")
        if value_raw is None:
            reject("missing_standard_value")
            return None
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            reject("unparseable_standard_value")
            return None

        standard_type = activity.get("standard_type") or "activity"
        assay_type = activity.get("assay_type")
        molecule_id = activity.get("molecule_chembl_id") or ""
        document_id = activity.get("document_chembl_id")

        return ActivityRecord(
            source_record_id=str(activity.get("activity_id")),
            # The candidate is the compound itself here; identity resolution
            # happens in the service, keyed by InChIKey.
            compound_source_id=raw_smiles,
            target_key=activity.get("target_chembl_id") or "",
            target_name=activity.get("target_pref_name"),
            assay_key=str(activity.get("assay_chembl_id") or ""),
            assay_type=assay_type,
            standard_type=standard_type,
            value=value,
            unit=activity.get("standard_units") or "",
            relation=_relation(activity.get("standard_relation")),
            evidence_class=classify_evidence(assay_type, standard_type, target_type),
            raw_value=str(value_raw),
            assay_description=activity.get("assay_description"),
            assay_format=activity.get("bao_label"),
            species=activity.get("target_organism"),
            variant_accession=activity.get("assay_variant_accession") or None,
            variant_mutation=activity.get("assay_variant_mutation") or None,
            pchembl_value=(
                float(activity["pchembl_value"])
                if activity.get("pchembl_value") not in (None, "")
                else None
            ),
            potential_duplicate=bool(activity.get("potential_duplicate")),
            validity_comment=activity.get("data_validity_comment") or None,
            document_ref=document_id,
            source_url=(
                f"https://www.ebi.ac.uk/chembl/activity/{activity.get('activity_id')}"
                if activity.get("activity_id")
                else None
            ),
            assay_type_name=activity.get("type"),
            modality_declared=activity.get("modality") or None,
            raw_smiles=raw_smiles,
            source_molecule_id=molecule_id or None,
            target_type_declared=target_type.value if target_type else None,
        )
