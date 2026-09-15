"""Target-led discovery service (ONLINE-00 B/C).

Runs one target investigation:

    resolved target -> per-source bounded retrieval -> RDKit normalization
    -> compounds / assays / measurements / candidates / retrieval records

Design rules this module enforces:

- **Chemistry is deterministic.** Every structure goes through RDKit
  (`normalize`) before it becomes a compound; anything that cannot be parsed is
  recorded as a rejection with a reason and counted, never stored as a
  structure (AGENTS.md §11).
- **A candidate is not a patent occurrence and not a claim.** Candidates are
  stored independently of patent membership so a compound with assay evidence
  and no patent mapping stays usable, filterable and savable (ONLINE-00 C).
- **Nothing is averaged away.** Every measurement keeps its own value,
  relation, unit, assay context and source record id, and measurements that
  share an original document reference are flagged so a duplicated upstream
  record cannot look like independent corroboration (ONLINE-00 C).
- **Failures are recorded, not smoothed.** Each source gets a retrieval row
  whose status distinguishes complete / partial / empty / failed / not_queried.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Collection, Iterable, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.adapters.bindingdb_rest import BindingDBRestAdapter
from spago_core.adapters.bioactivity_base import ActivityRecord, ActivityResult
from spago_core.adapters.chembl_discovery import ChEMBLDiscoveryAdapter
from spago_core.adapters.pubchem import PubChemAdapter
from spago_core.adapters.http import SourceClient
from spago_core.chemistry import (
    Modality,
    NormalizedStructure,
    StructureParseError,
    classify_modality,
    clean_external_smiles,
    murcko_scaffold,
    normalize,
)
from spago_core.chemistry.activities import ActivityClass
from spago_core.chemistry.activities import classify_activity as classify_potency
from spago_core.chemistry.activities import DEFAULT_THRESHOLD_NM
from spago_core.domain import (
    CandidateRecord,
    EvidenceClass,
    ResolvedTarget,
    RetrievalStatus,
    SourceRetrieval,
)
from spago_core.services.compound_store import (
    COMPOUND_NAMESPACE,
    CandidateStructure as _NormalizedCandidate,
)
from spago_core.services.compound_store import (
    compound_id_for_inchikey,  # noqa: F401  (re-exported: callers use discovery's name)
    persist_compounds,  # noqa: F401  (re-exported for callers of this module)
)
from spago_core.services.targets import TARGET_NAMESPACE, target_id_for_key

RETRIEVAL_NAMESPACE = uuid.UUID("c1a5f7b3-4d28-4e91-8f37-6b9c2a5d8e41")
CANDIDATE_NAMESPACE = uuid.UUID("e4b9d2c7-1f58-4a36-b0d9-7c3e8f5a2b16")

EXTERNAL_SOURCES = ("chembl", "bindingdb", "pubchem")

#: Rejection reasons that mean "the source answered, this record simply does
#: not qualify" — as opposed to a transport failure.
QUALITY_REJECTIONS = {
    "missing_structure",
    "missing_standard_value",
    "unparseable_standard_value",
    "unparseable_structure",
    "missing_affinity",
    "unsupported_modality",
}


@dataclass
class DiscoveryReport:
    target_id: uuid.UUID
    target_key: str
    retrievals: list[SourceRetrieval] = field(default_factory=list)
    compounds_stored: int = 0
    compounds_reused: int = 0
    measurements_stored: int = 0
    candidates_stored: int = 0
    rejections: dict[str, int] = field(default_factory=dict)
    modality_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def small_molecule_candidates(self) -> int:
        return self.modality_counts.get(Modality.SMALL_MOLECULE.value, 0) + self.modality_counts.get(
            Modality.UNCLASSIFIED.value, 0
        )

    def summary(self) -> dict:
        return {
            "target_key": self.target_key,
            "sources": [
                {
                    "source_name": r.source_name,
                    "status": r.status.value,
                    "records_seen": r.records_seen,
                    "records_kept": r.records_kept,
                    "records_excluded": r.records_excluded,
                }
                for r in self.retrievals
            ],
            "compounds_stored": self.compounds_stored,
            "compounds_reused": self.compounds_reused,
            "measurements_stored": self.measurements_stored,
            "candidates_stored": self.candidates_stored,
            "small_molecule_candidates": self.small_molecule_candidates,
            "modality_counts": self.modality_counts,
            "rejections": self.rejections,
            "warnings": self.warnings,
        }


class TargetDiscoveryService:
    """Coordinates source adapters for one target investigation."""

    def __init__(
        self,
        chembl: Optional[ChEMBLDiscoveryAdapter] = None,
        bindingdb: Optional[BindingDBRestAdapter] = None,
        pubchem: Optional[PubChemAdapter] = None,
        *,
        max_activities: int = 2000,
        max_molecule_lookups: int = 25,
    ) -> None:
        self.chembl = chembl or ChEMBLDiscoveryAdapter(
            max_activities=max_activities, max_molecule_lookups=max_molecule_lookups
        )
        self.bindingdb = bindingdb or BindingDBRestAdapter()
        self.pubchem = pubchem or PubChemAdapter()
        self.max_molecule_lookups = max_molecule_lookups

    # -- orchestration --------------------------------------------------------

    def investigate(
        self,
        engine: Engine,
        target: ResolvedTarget,
        sources: Iterable[str] = EXTERNAL_SOURCES,
        *,
        target_chembl_id: Optional[str] = None,
        max_activities: int = 2000,
    ) -> DiscoveryReport:
        """Run the requested sources and persist everything they returned.

        `sources` is explicit: a source that is not requested is recorded as
        `not_queried`, which is different from empty.
        """
        source_list = [s for s in sources]
        report = DiscoveryReport(target_id=target.id, target_key=target.target_key)
        accession = target.uniprot_accession

        collected: list[ActivityRecord] = []
        normalized: dict[str, _NormalizedCandidate] = {}
        modality_of: dict[str, Modality] = {}
        source_versions: dict[str, str] = {}
        primary_target_keys: set[str] = set()

        # --- ChEMBL ----------------------------------------------------------
        if "chembl" in source_list and accession:
            started = datetime.now(timezone.utc)
            outcome = self._run_chembl(target, accession, target_chembl_id, max_activities)
            report.retrievals.append(outcome.retrieval)
            collected.extend(outcome.records)
            normalized.update(outcome.normalized)
            modality_of.update(outcome.modality)
            primary_target_keys |= outcome.primary_target_keys
            source_versions["chembl"] = outcome.retrieval.source_version or ""
            report.rejections.update(outcome.retrieval.rejection_counts)
            report.warnings.extend(outcome.retrieval.warnings)
        elif "chembl" in source_list:
            report.retrievals.append(
                self._not_queried(
                    target, "chembl",
                    "The resolved target has no UniProt accession, so no ChEMBL component match was possible.",
                )
            )
        else:
            report.retrievals.append(self._not_queried(target, "chembl", "Not requested."))

        # --- BindingDB -------------------------------------------------------
        if "bindingdb" in source_list and accession:
            outcome = self._run_bindingdb(target, accession)
            report.retrievals.append(outcome.retrieval)
            collected.extend(outcome.records)
            normalized.update(outcome.normalized)
            modality_of.update(outcome.modality)
            source_versions["bindingdb"] = outcome.retrieval.source_version or ""
            report.rejections.update(outcome.retrieval.rejection_counts)
            report.warnings.extend(outcome.retrieval.warnings)
        elif "bindingdb" in source_list:
            report.retrievals.append(
                self._not_queried(target, "bindingdb", "No UniProt accession on the target.")
            )
        else:
            report.retrievals.append(self._not_queried(target, "bindingdb", "Not requested."))

        # --- PubChem (identity + screening context) --------------------------
        if "pubchem" in source_list:
            outcome = self._run_pubchem(target)
            report.retrievals.append(outcome.retrieval)
            report.warnings.extend(outcome.retrieval.warnings)
        else:
            report.retrievals.append(self._not_queried(target, "pubchem", "Not requested."))

        # --- persistence -----------------------------------------------------
        with engine.begin() as conn:
            self._persist_target(conn, target)
            retrieval_ids = {
                r.source_name: self._persist_retrieval(conn, target, r)
                for r in report.retrievals
            }
            for retrieval in report.retrievals:
                retrieval.id = retrieval_ids[retrieval.source_name]

            stored, reused = self._persist_compounds(conn, normalized)
            report.compounds_stored = stored
            report.compounds_reused = reused

            assay_cache: dict[str, uuid.UUID] = {}
            measurement_ids = self._persist_measurements(
                conn, target, collected, normalized, assay_cache, primary_target_keys
            )
            report.measurements_stored = measurement_ids

            report.candidates_stored = self._persist_candidates(
                conn, target, collected, normalized, retrieval_ids
            )

        for candidate in normalized.values():
            report.modality_counts[candidate.modality.value] = (
                report.modality_counts.get(candidate.modality.value, 0) + 1
            )
        return report

    # -- per-source runners ---------------------------------------------------

    @dataclass
    class _SourceOutcome:
        retrieval: SourceRetrieval
        records: list[ActivityRecord] = field(default_factory=list)
        normalized: dict[str, _NormalizedCandidate] = field(default_factory=dict)
        modality: dict[str, Modality] = field(default_factory=dict)
        #: Source target ids that *are* the investigated scope. A measurement
        #: against any other id describes a different object and gets its own
        #: target row (ONLINE-00 A).
        primary_target_keys: set[str] = field(default_factory=set)

    def _run_chembl(
        self,
        target: ResolvedTarget,
        accession: str,
        target_chembl_id: Optional[str],
        max_activities: int,
    ) -> "TargetDiscoveryService._SourceOutcome":
        started_monotonic = _now_ms()
        lookup = self.chembl.targets_for_accession(accession)
        candidates = lookup.entries

        # Which ChEMBL targets describe this accession? The single-protein record
        # is the primary scope; interaction/complex records are retrieved too,
        # because for a ligand–receptor system the interaction is the
        # therapeutic object and its measurements are of a different kind
        # (ONLINE-00 A/B). Each record keeps its own target type, so the
        # evidence class and the assay's owning target stay correct.
        plan = _chembl_query_plan(candidates, accession, target_chembl_id)
        if not plan:
            return self._SourceOutcome(
                retrieval=self._retrieval(
                    target,
                    "chembl",
                    status=RetrievalStatus.EMPTY,
                    query={"accession": accession, "target_chembl_candidates": []},
                    source_version=lookup.source_version,
                    warnings=[
                        "ChEMBL has no target whose components include this accession; "
                        "no activity retrieval was possible for this source.",
                        *lookup.warnings,
                    ],
                    latency_ms=_now_ms() - started_monotonic,
                )
            )

        records: list[ActivityRecord] = []
        by_record_id: dict[str, ActivityRecord] = {}
        record_index: dict[str, int] = {}
        excluded_total = 0
        pages_total = 0
        seen_total = 0
        statuses: list[RetrievalStatus] = []
        rejection_counts: dict[str, int] = {}
        warnings: list[str] = list(lookup.warnings)
        dataset_version: Optional[str] = None

        for chembl_id, target_type, note in plan:
            result = self.chembl.activities(chembl_id, target_type)
            dataset_version = dataset_version or result.envelope.dataset_version
            pages_total += result.pages_fetched
            seen_total += result.records_seen
            excluded_total += result.records_excluded
            for key, value in result.rejection_counts.items():
                rejection_counts[key] = rejection_counts.get(key, 0) + value
            warnings.extend(result.warnings)
            statuses.append(RetrievalStatus(result.status))
            for record in result.records:
                existing = by_record_id.get(record.source_record_id)
                if existing is None:
                    record_index[record.source_record_id] = len(records)
                    by_record_id[record.source_record_id] = record
                    records.append(record)
                    continue
                # The same measurement can be reachable through more than one
                # target definition (a protein and an interaction it takes part
                # in). Keep the *weakest* claim: the stronger one would overstate
                # the evidence, and overstating is the error this workflow exists
                # to avoid (ONLINE-00 C).
                if _evidence_rank(record.evidence_class) > _evidence_rank(
                    existing.evidence_class
                ):
                    by_record_id[record.source_record_id] = record
                    records[record_index[record.source_record_id]] = record
            if note:
                warnings.append(note)

        normalized, modality, norm_rejections = self._normalize_records(records)
        for key, value in norm_rejections.items():
            rejection_counts[key] = rejection_counts.get(key, 0) + value

        status = _combine_status(statuses)
        if status is RetrievalStatus.COMPLETE and not records:
            status = RetrievalStatus.EMPTY
            warnings.append(
                "ChEMBL returned no activity with both a structure and a numeric value "
                "for this target."
            )
        if len(plan) > 1:
            warnings.append(
                "Retrieved from "
                + ", ".join(f"{cid} ({ttype.value})" for cid, ttype, _ in plan)
                + ": single-protein and interaction measurements are kept distinct."
            )
        retrieval = self._retrieval(
            target,
            "chembl",
            status=status,
            query={
                "accession": accession,
                "target_chembl_ids": [cid for cid, _, _ in plan],
                "target_chembl_candidates": [e.identifier for e in candidates],
            },
            dataset_version=dataset_version,
            source_version="chembl-web-services",
            pages=pages_total,
            seen=seen_total,
            kept=len(records),
            excluded=excluded_total,
            rejection_counts=rejection_counts,
            warnings=warnings,
            latency_ms=_now_ms() - started_monotonic,
        )
        return self._SourceOutcome(
            retrieval, records, normalized, modality, primary_target_keys={plan[0][0]}
        )

    def _run_bindingdb(
        self, target: ResolvedTarget, accession: str
    ) -> "TargetDiscoveryService._SourceOutcome":
        started_monotonic = _now_ms()
        result = self.bindingdb.load(accession)
        normalized, modality, rejections = self._normalize_records(result.records)
        status = RetrievalStatus(result.status)
        warnings = list(result.warnings)
        if status is RetrievalStatus.FAILED:
            warnings.append(
                "BindingDB did not answer for this accession. This is a source failure, "
                "not a statement that no measurements exist."
            )
        retrieval = self._retrieval(
            target,
            "bindingdb",
            status=status,
            query={"uniprot": accession},
            dataset_version=result.envelope.dataset_version,
            source_version=result.envelope.source_version,
            pages=result.pages_fetched,
            seen=result.records_seen,
            kept=len(result.records),
            excluded=result.records_excluded,
            rejection_counts={**result.rejection_counts, **rejections},
            warnings=warnings,
            latency_ms=_now_ms() - started_monotonic,
        )
        return self._SourceOutcome(
            retrieval,
            result.records,
            normalized,
            modality,
            # BindingDB labels its records with a source-local key
            # (`bindingdb:<accession>`). The retrieval was for this target's
            # accession, so those measurements belong to the investigated target
            # rather than to a second, pseudo-target row (migration 0015).
            primary_target_keys={f"bindingdb:{accession}"},
        )

    def _run_pubchem(self, target: ResolvedTarget) -> "TargetDiscoveryService._SourceOutcome":
        started_monotonic = _now_ms()
        gene = target.gene_symbol or target.target_key
        context = self.pubchem.screening_assays_for_gene(gene)
        status = RetrievalStatus(context.status)
        warnings = list(context.notes)
        if context.assay_ids:
            warnings.append(
                "PubChem BioAssay identifiers are screening context only; no screening "
                "outcome is presented as a measurement for this target."
            )
        retrieval = self._retrieval(
            target,
            "pubchem",
            status=status,
            query={"gene_symbol": gene},
            source_version="pubchem-pug-rest",
            seen=context.total_reported,
            kept=0,
            excluded=0,
            warnings=warnings,
            latency_ms=_now_ms() - started_monotonic,
            extra={"assay_ids": list(context.assay_ids), "truncated": context.truncated},
        )
        return self._SourceOutcome(retrieval)

    # -- chemistry ------------------------------------------------------------

    def _normalize_records(
        self, records: Iterable[ActivityRecord]
    ) -> tuple[dict[str, _NormalizedCandidate], dict[str, Modality], dict[str, int]]:
        normalized: dict[str, _NormalizedCandidate] = {}
        modality: dict[str, Modality] = {}
        rejections: dict[str, int] = {}
        for record in records:
            raw = (record.raw_smiles or record.compound_source_id or "").strip()
            cleaned, notes = clean_external_smiles(raw)
            key = cleaned
            if key in normalized:
                continue
            if key in rejections:
                continue
            try:
                norm = normalize(cleaned)
            except StructureParseError:
                rejections["unparseable_structure"] = rejections.get("unparseable_structure", 0) + 1
                continue
            verdict = classify_modality(
                norm.canonical_smiles,
                source_declared=record.modality_declared,
            )
            try:
                scaffold = murcko_scaffold(norm.canonical_smiles)
            except StructureParseError:
                scaffold = None
            normalized[key] = _NormalizedCandidate(
                raw_smiles=raw,
                structure=norm,
                modality=verdict.modality,
                modality_rule=verdict.rule + (";" + ";".join(notes) if notes else ""),
                modality_source="source+rdkit" if verdict.source_declared else "rdkit",
                scaffold=scaffold,
            )
            modality[key] = verdict.modality
        return normalized, modality, rejections

    # -- persistence ----------------------------------------------------------

    def _persist_target(self, conn, target: ResolvedTarget) -> None:
        conn.execute(
            text(
                """
                INSERT INTO targets (id, target_key, name, organism, source_name,
                                     dataset_version, retrieved_at, uniprot_accession,
                                     gene_symbol, taxon_id, target_type, scope_kind,
                                     aliases, components)
                VALUES (:id, :target_key, :name, :organism, :source_name,
                        :dataset_version, :retrieved_at, :uniprot_accession,
                        :gene_symbol, :taxon_id, :target_type, :scope_kind,
                        CAST(:aliases AS jsonb), CAST(:components AS jsonb))
                ON CONFLICT (id) DO UPDATE
                  SET name = EXCLUDED.name,
                      target_type = EXCLUDED.target_type,
                      scope_kind = COALESCE(EXCLUDED.scope_kind, targets.scope_kind),
                      aliases = EXCLUDED.aliases,
                      components = EXCLUDED.components
                """
            ),
            {
                "id": target.id,
                "target_key": target.target_key,
                "name": target.name,
                "organism": target.organism,
                "source_name": target.source_name or "uniprot",
                "dataset_version": target.dataset_version or "unknown",
                "retrieved_at": datetime.now(timezone.utc),
                "uniprot_accession": target.uniprot_accession,
                "gene_symbol": target.gene_symbol,
                "taxon_id": target.taxon_id,
                "target_type": target.target_type.value if target.target_type else None,
                "scope_kind": target.scope_kind.value if target.scope_kind else None,
                "aliases": json.dumps(target.aliases),
                "components": json.dumps([c.model_dump() for c in target.components]),
            },
        )

    def _persist_retrieval(self, conn, target: ResolvedTarget, retrieval: SourceRetrieval) -> uuid.UUID:
        conn.execute(
            text(
                """
                INSERT INTO source_retrievals (id, target_id, source_name, query, status,
                                               dataset_version, source_version, pages_fetched,
                                               records_seen, records_kept, records_excluded,
                                               rejection_counts, latency_ms, warnings,
                                               checksum, retrieved_at)
                VALUES (:id, :target_id, :source_name, CAST(:query AS jsonb), :status,
                        :dataset_version, :source_version, :pages_fetched,
                        :records_seen, :records_kept, :records_excluded,
                        CAST(:rejection_counts AS jsonb), :latency_ms,
                        CAST(:warnings AS jsonb), :checksum, :retrieved_at)
                ON CONFLICT (id) DO UPDATE
                  SET status = EXCLUDED.status,
                      records_seen = EXCLUDED.records_seen,
                      records_kept = EXCLUDED.records_kept,
                      records_excluded = EXCLUDED.records_excluded,
                      rejection_counts = EXCLUDED.rejection_counts,
                      warnings = EXCLUDED.warnings,
                      latency_ms = EXCLUDED.latency_ms,
                      retrieved_at = EXCLUDED.retrieved_at
                """
            ),
            {
                "id": retrieval.id,
                "target_id": target.id,
                "source_name": retrieval.source_name,
                "query": json.dumps(retrieval.query),
                "status": retrieval.status.value,
                "dataset_version": retrieval.dataset_version,
                "source_version": retrieval.source_version,
                "pages_fetched": retrieval.pages_fetched,
                "records_seen": retrieval.records_seen,
                "records_kept": retrieval.records_kept,
                "records_excluded": retrieval.records_excluded,
                "rejection_counts": json.dumps(retrieval.rejection_counts),
                "latency_ms": retrieval.latency_ms,
                "warnings": json.dumps(retrieval.warnings),
                "checksum": retrieval.checksum,
                "retrieved_at": retrieval.retrieved_at,
            },
        )
        return retrieval.id

    def _persist_compounds(
        self, conn, normalized: dict[str, _NormalizedCandidate]
    ) -> tuple[int, int]:
        """Compound identity is shared with every other ingest path."""
        return persist_compounds(conn, normalized)

    def _persist_measurements(
        self,
        conn,
        target: ResolvedTarget,
        records: list[ActivityRecord],
        normalized: dict[str, _NormalizedCandidate],
        assay_cache: dict[str, uuid.UUID],
        primary_target_keys: set[str],
    ) -> int:
        if not records:
            return 0
        by_key = {c.raw_smiles: c for c in normalized.values()}
        # Cross-source duplicate detection. Two records are the *same
        # measurement* when they cite the same original document for the same
        # compound, endpoint type, unit and value — that is how one upstream
        # experiment recorded in two databases looks. The second occurrence is
        # flagged, so it cannot read as independent corroboration. Different
        # compounds or different endpoints from the same paper are different
        # experiments and are not flagged (ONLINE-00 C).
        measurement_key_seen: dict[tuple, str] = {}
        stored = 0
        for record in records:
            cleaned, _ = clean_external_smiles(record.raw_smiles or record.compound_source_id or "")
            candidate = by_key.get(record.raw_smiles or "") or _by_cleaned(normalized, cleaned)
            if candidate is None:
                continue
            compound_id = compound_id_for_inchikey(candidate.inchikey)

            # A measurement against an interaction/complex describes a different
            # scientific object than the investigated protein, so it is attached
            # to its own target row and labelled; the candidate still belongs to
            # the user's investigation (ONLINE-00 A).
            target_row_id = self._assay_target_row(conn, target, record, primary_target_keys)

            assay_key = record.assay_key or f"{record.source_molecule_id or 'unknown'}"
            assay_id = assay_cache.get(assay_key)
            if assay_id is None:
                assay_id = uuid.uuid5(COMPOUND_NAMESPACE, f"assay:{assay_key}")
                assay_cache[assay_key] = assay_id
                conn.execute(
                    text(
                        """
                        INSERT INTO assays (id, assay_key, target_id, assay_type,
                                            description, source_name, dataset_version,
                                            retrieved_at)
                        VALUES (:id, :assay_key, :target_id, :assay_type, :description,
                                :source_name, :dataset_version, :retrieved_at)
                        ON CONFLICT (assay_key) DO UPDATE
                          SET target_id = EXCLUDED.target_id,
                              assay_type = EXCLUDED.assay_type,
                              description = EXCLUDED.description,
                              source_name = EXCLUDED.source_name,
                              dataset_version = EXCLUDED.dataset_version,
                              retrieved_at = EXCLUDED.retrieved_at
                        """
                    ),
                    {
                        "id": assay_id,
                        "assay_key": assay_key,
                        "target_id": target_row_id,
                        "assay_type": record.assay_type,
                        "description": record.assay_description,
                        "source_name": record.source_name or target.source_name or "external",
                        "dataset_version": (
                            record.source_dataset_version
                            or target.dataset_version
                            or "external:open-databases"
                        ),
                        "retrieved_at": datetime.now(timezone.utc),
                    },
                )

            duplicate_of = None
            if record.document_ref:
                dedup_key = (
                    record.document_ref,
                    candidate.inchikey,
                    record.standard_type,
                    record.unit,
                    record.value,
                )
                duplicate_of = measurement_key_seen.get(dedup_key)
                measurement_key_seen.setdefault(dedup_key, record.source_record_id)
            potential_duplicate = record.potential_duplicate or duplicate_of is not None
            comment = record.validity_comment
            if duplicate_of is not None:
                comment = (
                    f"{comment + '; ' if comment else ''}"
                    f"same original document/compound/endpoint/value as {duplicate_of}; "
                    "not independent corroboration"
                )

            measurement_id = uuid.uuid5(
                COMPOUND_NAMESPACE,
                f"measurement:{target.target_key}:{record.source_record_id}",
            )
            conn.execute(
                text(
                    """
                    INSERT INTO measurements (id, compound_id, assay_id, standard_type,
                                              value, unit, relation, source_record_id,
                                              source_name, extraction_method,
                                              provenance_state, confidence,
                                              dataset_version, retrieved_at,
                                              evidence_class, raw_value,
                                              assay_description, assay_format, species,
                                              variant_accession,
                                              variant_mutation, pchembl_value,
                                              potential_duplicate, validity_comment,
                                              document_ref, source_url,
                                              source_molecule_id, modality_declared,
                                              document_patent_number, document_doi,
                                              document_pmid)
                    VALUES (:id, :compound_id, :assay_id, :standard_type,
                            :value, :unit, :relation, :source_record_id,
                            :source_name, :extraction_method,
                            'database_curated', :confidence,
                            :dataset_version, :retrieved_at,
                            :evidence_class, :raw_value,
                            :assay_description, :assay_format, :species,
                            :variant_accession,
                            :variant_mutation, :pchembl_value,
                            :potential_duplicate, :validity_comment,
                            :document_ref, :source_url,
                            :source_molecule_id, :modality_declared,
                            :document_patent_number, :document_doi,
                            :document_pmid)
                    ON CONFLICT (compound_id, assay_id, standard_type, source_record_id)
                      DO UPDATE SET
                        value = EXCLUDED.value,
                        unit = EXCLUDED.unit,
                        relation = EXCLUDED.relation,
                        evidence_class = EXCLUDED.evidence_class,
                        -- The reporting source is refreshed too: a row stored before
                        -- the source attribution was fixed (ONLINE-06) must not keep
                        -- naming the resolver as the source of the measurement.
                        source_name = EXCLUDED.source_name,
                        dataset_version = EXCLUDED.dataset_version,
                        raw_value = EXCLUDED.raw_value,
                        assay_description = EXCLUDED.assay_description,
                        assay_format = EXCLUDED.assay_format,
                        species = EXCLUDED.species,
                        variant_accession = EXCLUDED.variant_accession,
                        variant_mutation = EXCLUDED.variant_mutation,
                        pchembl_value = EXCLUDED.pchembl_value,
                        potential_duplicate = EXCLUDED.potential_duplicate,
                        validity_comment = EXCLUDED.validity_comment,
                        document_ref = EXCLUDED.document_ref,
                        source_url = EXCLUDED.source_url,
                        source_molecule_id = EXCLUDED.source_molecule_id,
                        document_patent_number = EXCLUDED.document_patent_number,
                        document_doi = EXCLUDED.document_doi,
                        document_pmid = EXCLUDED.document_pmid,
                        retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": measurement_id,
                    "compound_id": compound_id,
                    "assay_id": assay_id,
                    "standard_type": record.standard_type,
                    "value": record.value,
                    "unit": record.unit,
                    "relation": record.relation,
                    "source_record_id": record.source_record_id,
                    # ONLINE-06: the source that reported this measurement, not the
                    # source that resolved the target (they differ for every ChEMBL
                    # or BindingDB record reached through a UniProt resolution).
                    "source_name": record.source_name or target.source_name or "external",
                    "extraction_method": _extraction_method(record),
                    "confidence": record.source_confidence,
                    "dataset_version": (
                        record.source_dataset_version
                        or target.dataset_version
                        or "external:open-databases"
                    ),
                    "retrieved_at": datetime.now(timezone.utc),
                    "evidence_class": record.evidence_class.value,
                    "raw_value": record.raw_value,
                    "assay_description": record.assay_description,
                    "assay_format": record.assay_format,
                    "species": record.species,
                    "variant_accession": record.variant_accession,
                    "variant_mutation": record.variant_mutation,
                    "pchembl_value": record.pchembl_value,
                    "potential_duplicate": potential_duplicate,
                    "validity_comment": comment,
                    "document_ref": record.document_ref,
                    "source_url": record.source_url,
                    "source_molecule_id": record.source_molecule_id,
                    "modality_declared": record.modality_declared,
                    "document_patent_number": record.document_patent_number,
                    "document_doi": record.document_doi,
                    "document_pmid": record.document_pmid,
                },
            )
            stored += 1
        return stored

    def _persist_candidates(
        self,
        conn,
        target: ResolvedTarget,
        records: list[ActivityRecord],
        normalized: dict[str, _NormalizedCandidate],
        retrieval_ids: dict[str, uuid.UUID],
    ) -> int:
        """One candidate row per (target, source, source record).

        Candidates come from the source's own records, not from the normalized
        compound list, so a source record that failed normalization is visible
        as a rejection count rather than silently changing the candidate count.
        """
        stored = 0
        seen: set[tuple[str, str]] = set()
        for record in records:
            source = _source_of(record)
            key = (source, record.source_record_id)
            if key in seen:
                continue
            seen.add(key)
            cleaned, _ = clean_external_smiles(record.raw_smiles or record.compound_source_id or "")
            candidate = _by_cleaned(normalized, cleaned)
            if candidate is None:
                continue
            conn.execute(
                text(
                    """
                    INSERT INTO target_candidates (id, target_id, compound_id, source_name,
                                                   source_record_id, source_molecule_id,
                                                   evidence_class, modality, retrieval_id,
                                                   dataset_version, retrieved_at)
                    VALUES (:id, :target_id, :compound_id, :source_name,
                            :source_record_id, :source_molecule_id,
                            :evidence_class, :modality, :retrieval_id,
                            :dataset_version, :retrieved_at)
                    ON CONFLICT (target_id, source_name, source_record_id) DO UPDATE
                      SET evidence_class = EXCLUDED.evidence_class,
                          modality = EXCLUDED.modality,
                          retrieval_id = EXCLUDED.retrieval_id,
                          retrieved_at = EXCLUDED.retrieved_at,
                          -- A row a refresh retracted and a later retrieval
                          -- brings back is current again (migration 0015).
                          retracted_at = NULL,
                          retracted_reason = NULL
                    """
                ),
                {
                    "id": uuid.uuid5(
                        CANDIDATE_NAMESPACE, f"candidate:{target.id}:{source}:{record.source_record_id}"
                    ),
                    "target_id": target.id,
                    "compound_id": compound_id_for_inchikey(candidate.inchikey),
                    "source_name": source,
                    "source_record_id": record.source_record_id,
                    "source_molecule_id": record.source_molecule_id,
                    "evidence_class": record.evidence_class.value,
                    "modality": candidate.modality.value,
                    "retrieval_id": retrieval_ids.get(source),
                    "dataset_version": target.dataset_version or "external:open-databases",
                    "retrieved_at": datetime.now(timezone.utc),
                },
            )
            stored += 1
        return stored

    # -- helpers --------------------------------------------------------------

    def _assay_target_row(
        self,
        conn,
        target: ResolvedTarget,
        record: ActivityRecord,
        primary_target_keys: set[str],
    ) -> uuid.UUID:
        """The target row an assay belongs to.

        Measurements retrieved through an interaction/complex target id are
        attached to a row for *that* object, so the record never claims the
        compound was measured against the investigated protein when the source
        measured a protein–protein interaction. Measurements against the
        investigation's primary source target, or against the same key/accession
        as the investigated target, stay attached to it.
        """
        key = record.target_key or ""
        if (
            not key
            or key == target.target_key
            or key == target.uniprot_accession
            or key in primary_target_keys
        ):
            return target.id
        target_type = record.target_type_declared
        row_id = target_id_for_key(key)
        conn.execute(
            text(
                """
                INSERT INTO targets (id, target_key, name, organism, source_name,
                                     dataset_version, retrieved_at, target_type,
                                     uniprot_accession, gene_symbol)
                VALUES (:id, :target_key, :name, :organism, :source_name,
                        :dataset_version, :retrieved_at, :target_type, NULL, NULL)
                ON CONFLICT (id) DO UPDATE
                  SET name = COALESCE(EXCLUDED.name, targets.name),
                      target_type = COALESCE(EXCLUDED.target_type, targets.target_type),
                      retrieved_at = EXCLUDED.retrieved_at
                """
            ),
            {
                "id": row_id,
                "target_key": key,
                "name": record.target_name or key,
                "organism": target.organism,
                "source_name": "chembl",
                "dataset_version": target.dataset_version or "external:open-databases",
                "retrieved_at": datetime.now(timezone.utc),
                "target_type": target_type,
            },
        )
        # The retrieval went through this object, so its measurements belong to
        # the investigation that asked for it — recorded explicitly instead of
        # re-derived by joining every measurement of a candidate compound
        # (migration 0015, AGENTS.md §9).
        conn.execute(
            text(
                """
                INSERT INTO target_relations (target_id, related_target_id, relation,
                                              source_name, source_key, note)
                VALUES (:target_id, :related_target_id, 'interaction_record_of',
                        'chembl', :source_key, :note)
                ON CONFLICT (target_id, related_target_id, relation) DO NOTHING
                """
            ),
            {
                "target_id": target.id,
                "related_target_id": row_id,
                "source_key": key,
                "note": (
                    f"{key} describes an interaction/complex record retrieved while "
                    f"investigating {target.target_key}; its measurements stay labelled "
                    "with that object, not with the investigated protein."
                ),
            },
        )
        return row_id

    def _retrieval(
        self,
        target: ResolvedTarget,
        source_name: str,
        *,
        status: RetrievalStatus,
        query: dict,
        dataset_version: Optional[str] = None,
        source_version: Optional[str] = None,
        pages: int = 0,
        seen: int = 0,
        kept: int = 0,
        excluded: int = 0,
        rejection_counts: Optional[dict[str, int]] = None,
        warnings: Optional[list[str]] = None,
        latency_ms: Optional[int] = None,
        extra: Optional[dict] = None,
    ) -> SourceRetrieval:
        merged_query = dict(query)
        if extra:
            merged_query.update(extra)
        checksum = hashlib.sha256(
            json.dumps(merged_query, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        return SourceRetrieval(
            id=uuid.uuid5(RETRIEVAL_NAMESPACE, f"retrieval:{target.id}:{source_name}"),
            target_id=target.id,
            source_name=source_name,
            query=merged_query,
            status=status,
            dataset_version=dataset_version,
            source_version=source_version,
            pages_fetched=pages,
            records_seen=seen,
            records_kept=kept,
            records_excluded=excluded,
            rejection_counts=rejection_counts or {},
            latency_ms=latency_ms,
            warnings=warnings or [],
            checksum=checksum,
            retrieved_at=datetime.now(timezone.utc),
        )

    def _not_queried(self, target: ResolvedTarget, source_name: str, reason: str) -> SourceRetrieval:
        return self._retrieval(
            target,
            source_name,
            status=RetrievalStatus.NOT_QUERIED,
            query={},
            warnings=[reason],
        )


# --- module helpers ---------------------------------------------------------------


def _now_ms() -> int:
    import time

    return int(time.monotonic() * 1000)


def _by_cleaned(
    normalized: dict[str, _NormalizedCandidate], cleaned: str
) -> Optional[_NormalizedCandidate]:
    direct = normalized.get(cleaned)
    if direct is not None:
        return direct
    for candidate in normalized.values():
        if candidate.canonical_smiles == cleaned:
            return candidate
    return None


def _source_of(record: ActivityRecord) -> str:
    key = record.assay_key or ""
    if ":" in key:
        return key.split(":", 1)[0]
    if record.source_url and "chembl" in record.source_url:
        return "chembl"
    return "unknown"


def _extraction_method(record: ActivityRecord) -> str:
    if "chembl" in (record.source_url or ""):
        return "chembl_webclient_discovery"
    return "bindingdb_rest_uniprot"


def _pick_chembl_target(entries, accession: str):
    """Choose the primary ChEMBL target to query for an accession.

    Preference: the single-protein record for exactly this accession, then a
    protein–protein interaction that includes it, then any record. The chosen
    type travels with the retrieval so the evidence classification knows
    whether the measurement describes a protein or an interaction.
    """
    if not entries:
        return None
    for entry in entries:
        components = [c.accession for c in entry.components]
        if entry.target_type is not None and entry.target_type.value == "single_protein" and (
            not components or accession in components
        ):
            return entry.identifier, entry.target_type
    for entry in entries:
        if entry.target_type is not None and entry.target_type.value == "protein_protein_interaction":
            return entry.identifier, entry.target_type
    return entries[0].identifier, entries[0].target_type


#: At most this many ChEMBL targets are queried for one accession, so a target
#: with many recorded complexes cannot turn one investigation into an unbounded
#: crawl (AGENTS.md §16/§21).
MAX_CHEMBL_TARGETS = 3


def _chembl_query_plan(
    entries: list, accession: str, explicit_id: Optional[str]
) -> list[tuple[str, object, Optional[str]]]:
    """Ordered (target_chembl_id, target_type, note) list to retrieve.

    The single-protein record comes first and is the primary scope. Records
    describing a protein–protein interaction or a complex that includes the
    same accession follow, each carrying the note that its measurements concern
    the interaction rather than a binding site on this protein alone.
    """
    plan: list[tuple[str, object, Optional[str]]] = []
    seen: set[str] = set()

    def add(identifier: str, target_type, note: Optional[str]) -> None:
        if not identifier or identifier in seen or len(plan) >= MAX_CHEMBL_TARGETS:
            return
        seen.add(identifier)
        plan.append((identifier, target_type, note))

    if explicit_id:
        match = next((e for e in entries if e.identifier == explicit_id), None)
        add(explicit_id, match.target_type if match else None, None)

    primary = _pick_chembl_target(entries, accession)
    if primary is None:
        return plan
    add(primary[0], primary[1], None)
    for entry in entries:
        if entry.identifier in seen:
            continue
        if entry.target_type is not None and entry.target_type.value in (
            "protein_protein_interaction",
            "protein_complex",
        ):
            add(
                entry.identifier,
                entry.target_type,
                f"{entry.identifier} ({entry.name}) describes an interaction/complex "
                f"involving {accession}; its measurements are labelled as interaction "
                "evidence, not as a binding site on this protein.",
            )
    return plan


#: Evidence strength, strongest claim first. Used when the same measurement is
#: reachable through more than one target definition: the *weakest* claim is
#: kept (the highest rank), so a record never asserts more than the data
#: supports.
_EVIDENCE_STRENGTH = (
    EvidenceClass.MEASURED_DIRECT_BINDING,
    EvidenceClass.INTERACTION_DISRUPTION,
    EvidenceClass.FUNCTIONAL_EFFECT,
    EvidenceClass.SCREENING_ASSAY,
    EvidenceClass.COMPUTATIONAL_PREDICTION,
    EvidenceClass.UNSPECIFIED,
)


def _evidence_rank(evidence_class: EvidenceClass) -> int:
    try:
        return _EVIDENCE_STRENGTH.index(evidence_class)
    except ValueError:  # pragma: no cover - enum is closed
        return len(_EVIDENCE_STRENGTH)


def _combine_status(statuses: list[RetrievalStatus]) -> RetrievalStatus:
    """Combine per-target outcomes without letting a success hide a failure."""
    if not statuses:
        return RetrievalStatus.EMPTY
    if all(s is RetrievalStatus.FAILED for s in statuses):
        return RetrievalStatus.FAILED
    if any(s is RetrievalStatus.FAILED for s in statuses):
        return RetrievalStatus.PARTIAL
    if any(s is RetrievalStatus.PARTIAL for s in statuses):
        return RetrievalStatus.PARTIAL
    if all(s is RetrievalStatus.EMPTY for s in statuses):
        return RetrievalStatus.EMPTY
    return RetrievalStatus.COMPLETE


def list_source_retrievals(engine: Engine, target_id: uuid.UUID) -> list[SourceRetrieval]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, target_id, source_name, query, status, dataset_version,
                       source_version, pages_fetched, records_seen, records_kept,
                       records_excluded, rejection_counts, latency_ms, warnings,
                       checksum, retrieved_at
                FROM source_retrievals
                WHERE target_id = :tid
                ORDER BY source_name
                """
            ),
            {"tid": target_id},
        ).mappings().all()
    return [
        SourceRetrieval(
            id=r["id"],
            target_id=r["target_id"],
            source_name=r["source_name"],
            query=_json(r["query"]) or {},
            status=RetrievalStatus(r["status"]),
            dataset_version=r["dataset_version"],
            source_version=r["source_version"],
            pages_fetched=r["pages_fetched"],
            records_seen=r["records_seen"],
            records_kept=r["records_kept"],
            records_excluded=r["records_excluded"],
            rejection_counts=_json(r["rejection_counts"]) or {},
            latency_ms=r["latency_ms"],
            warnings=list(_json(r["warnings"]) or []),
            checksum=r["checksum"],
            retrieved_at=r["retrieved_at"],
        )
        for r in rows
    ]


def _json(value):
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def list_candidates(
    engine: Engine,
    target_id: uuid.UUID,
    *,
    modality: Optional[str] = None,
    evidence_class: Optional[str] = None,
    include_all_modalities: bool = False,
    offset: int = 0,
    limit: int = 100,
    pin_compound_id: Optional[uuid.UUID] = None,
    pin_compound_ids: Optional[Collection[uuid.UUID]] = None,
    policy=None,
) -> tuple[int, list[CandidateRecord]]:
    """Candidate compounds for a target, with patent-linkage status.

    The default view is small molecules plus unclassified entities; peptides,
    oligonucleotides and biologics are excluded *by the returned filter* and
    their count is reported separately by the caller, never silently dropped.

    `pin_compound_ids` (or the single `pin_compound_id`) adds those compounds as
    labelled rows (`outside_filter=True`) when the filters exclude them, without
    changing the filter, the counts or the total (defect D2). Every item a reader
    saved has to stay visible under whatever filter they return with.

    When `policy` is given, each row also carries the compound's own potency
    class and as-reported label under that policy, plus the sources and the
    source-declared publication numbers behind it (ONLINE-06).
    """
    clauses = ["tc.target_id = :tid", "tc.retracted_at IS NULL"]
    params: dict = {"tid": target_id, "limit": limit, "offset": offset}
    if not include_all_modalities:
        clauses.append(
            "(c.modality IS NULL OR c.modality IN ('small_molecule','unclassified'))"
        )
    if modality:
        clauses.append("c.modality = :modality")
        params["modality"] = modality
    if evidence_class:
        clauses.append("EXISTS (SELECT 1 FROM measurements m2 WHERE m2.compound_id = c.id "
                       "AND m2.evidence_class = :evidence_class)")
        params["evidence_class"] = evidence_class

    where = " AND ".join(clauses)
    columns = """
                       c.id AS compound_id, c.canonical_smiles, c.inchikey,
                       c.molecular_formula, c.molecular_weight, c.modality,
                       c.modality_rule, c.modality_source,
                       min(tc.source_name) AS source_name,
                       min(tc.source_record_id) AS source_record_id,
                       max(tc.evidence_class) AS evidence_class,
                       (SELECT count(*) FROM current_compound_mentions cm
                         WHERE cm.compound_id = c.id) AS patent_occurrences,
                       (SELECT count(*) FROM investigation_measurements mm
                         WHERE mm.compound_id = c.id AND mm.investigation_target_id = :tid
                         ) AS measurements
                FROM target_candidates tc
                JOIN compounds c ON c.id = tc.compound_id
    """
    grouping = """
                GROUP BY c.id, c.canonical_smiles, c.inchikey, c.molecular_formula,
                         c.molecular_weight, c.modality, c.modality_rule, c.modality_source
                ORDER BY (c.molecular_weight IS NULL), c.molecular_weight, c.inchikey
    """
    with engine.connect() as conn:
        total = conn.execute(
            text(
                f"""
                SELECT count(DISTINCT tc.compound_id)
                FROM target_candidates tc JOIN compounds c ON c.id = tc.compound_id
                WHERE {where}
                """
            ),
            params,
        ).scalar_one()
        rows = conn.execute(
            text(f"SELECT {columns} WHERE {where} {grouping} LIMIT :limit OFFSET :offset"),
            params,
        ).mappings().all()
        # Saved or deep-linked compounds must stay visible even when the current
        # filter excludes them (a peptide under the small-molecule scope, say).
        # They are fetched by id and returned as their own labelled rows — the
        # filter, its counts and the page total are untouched, so the reader sees
        # explicitly marked outsiders instead of a scope that changed under their
        # feet (defect D2).
        wanted = {cid for cid in (pin_compound_ids or ()) if cid is not None}
        if pin_compound_id is not None:
            wanted.add(pin_compound_id)
        pinned_ids: set[uuid.UUID] = set()
        missing = wanted - {row["compound_id"] for row in rows}
        if missing:
            pinned = conn.execute(
                text(
                    f"SELECT {columns} "
                    " WHERE tc.target_id = :tid AND tc.retracted_at IS NULL"
                    "   AND tc.compound_id = ANY(:cids) "
                    f" {grouping}"
                ),
                {"tid": target_id, "cids": sorted(missing)},
            ).mappings().all()
            pinned_ids = {row["compound_id"] for row in pinned}
            rows = list(rows) + list(pinned)
        labels = conn.execute(
            text(
                """
                SELECT cm.compound_id, d.publication_number, cm.patent_label
                FROM current_compound_mentions cm
                JOIN patent_documents d ON d.id = cm.document_id
                WHERE cm.compound_id IN (
                    SELECT tc.compound_id FROM target_candidates tc WHERE tc.target_id = :tid
                )
                ORDER BY d.publication_number
                LIMIT 500
                """
            ),
            {"tid": target_id},
        ).mappings().all()

    label_map: dict[str, list[str]] = {}
    for row in labels:
        label = " · ".join(filter(None, [row["publication_number"], row["patent_label"]]))
        label_map.setdefault(str(row["compound_id"]), []).append(label)

    activity: dict[uuid.UUID, object] = {}
    if policy is not None and rows:
        from spago_core.services.reference import compound_activity_summary

        activity = compound_activity_summary(
            engine, target_id, [row["compound_id"] for row in rows], policy
        )

    items = []
    for row in rows:
        summary = activity.get(row["compound_id"])
        items.append(
            CandidateRecord(
                compound_id=row["compound_id"],
                canonical_smiles=row["canonical_smiles"],
                inchikey=row["inchikey"],
                molecular_formula=row["molecular_formula"],
                molecular_weight=row["molecular_weight"],
                modality=Modality(row["modality"]) if row["modality"] else Modality.UNCLASSIFIED,
                modality_rule=row["modality_rule"],
                modality_source=row["modality_source"],
                source_name=row["source_name"],
                source_record_id=row["source_record_id"],
                evidence_class=EvidenceClass(row["evidence_class"])
                if row["evidence_class"]
                else EvidenceClass.UNSPECIFIED,
                patent_occurrences=int(row["patent_occurrences"] or 0),
                patent_labels=label_map.get(str(row["compound_id"]), [])[:5],
                measurements=int(row["measurements"] or 0),
                activity_class=(
                    summary.activity_class if summary else ActivityClass.NOT_APPLICABLE
                ),
                activity_rule=summary.rule if summary else None,
                potency_label=summary.label if summary else None,
                sources=list(summary.sources) if summary else [],
                source_declared_patents=list(summary.patents) if summary else [],
                outside_filter=row["compound_id"] in pinned_ids,
            )
        )
    return int(total), items


def modality_breakdown(engine: Engine, target_id: uuid.UUID) -> dict[str, int]:
    """How many candidates of each modality exist — the evidence that the
    default small-molecule view is a labelled filter, not a silent drop."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT coalesce(c.modality, 'unclassified') AS modality,
                       count(DISTINCT tc.compound_id) AS n
                FROM target_candidates tc JOIN compounds c ON c.id = tc.compound_id
                WHERE tc.target_id = :tid
                GROUP BY 1 ORDER BY 2 DESC, 1
                """
            ),
            {"tid": target_id},
        ).all()
    return {row[0]: int(row[1]) for row in rows}


def list_target_measurements(
    engine: Engine,
    target_id: uuid.UUID,
    *,
    compound_id: Optional[uuid.UUID] = None,
    evidence_class: Optional[str] = None,
    include_duplicates: bool = True,
    limit: int = 200,
    threshold_nm: float = DEFAULT_THRESHOLD_NM,
) -> list[dict]:
    """Measurements for a target with their full assay context.

    Deliberately unordered by potency: heterogeneous assays must not be
    presented as one ranked list (ONLINE-00 C). `include_duplicates=False`
    hides records flagged as sharing an original document reference, which is
    an explicit user choice rather than a silent deduplication.

    Each row also carries `activity_class` / `activity_class_rule`: what that one
    report implies under `threshold_nm` (ONLINE-06). It is computed here, never
    stored, so the class always matches the threshold the caller displayed.

    Scope comes from `investigation_measurements`: this target plus the
    interaction/complex targets this investigation retrieved through, and never a
    measurement of the same compound against an unrelated target (migration 0015).
    """
    clauses = ["m.investigation_target_id = :tid"]
    params: dict = {"tid": target_id, "limit": limit}
    if compound_id:
        clauses.append("m.compound_id = :compound_id")
        params["compound_id"] = compound_id
    if evidence_class:
        clauses.append("m.evidence_class = :evidence_class")
        params["evidence_class"] = evidence_class
    if not include_duplicates:
        clauses.append("m.potential_duplicate = false")
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT m.id, m.compound_id, c.inchikey, t.name AS target_name,
                       t.target_key AS target_key, t.target_type AS target_type,
                       a.assay_key, a.assay_type, a.description AS assay_description,
                       m.assay_format, m.standard_type, m.value, m.unit, m.relation,
                       m.raw_value, coalesce(m.evidence_class, 'unspecified') AS evidence_class,
                       -- A user-added row's note is its provenance, so it travels to the
                       -- reader as its own field instead of being presented as a source's
                       -- assay text (ONLINE-07, AGENTS.md §10).
                       m.assay_description AS note,
                       m.species, m.variant_accession, m.variant_mutation,
                       m.pchembl_value, m.potential_duplicate, m.validity_comment,
                       m.document_ref, m.source_url, m.source_record_id, m.source_name,
                       m.extraction_method, m.provenance_state, m.dataset_version,
                       m.document_patent_number, m.document_doi, m.document_pmid,
                       m.retrieved_at
                FROM investigation_measurements m
                JOIN assays a ON a.id = m.assay_id
                JOIN targets t ON t.id = a.target_id
                JOIN compounds c ON c.id = m.compound_id
                WHERE {where}
                ORDER BY coalesce(m.evidence_class, 'unspecified'), c.inchikey,
                         m.standard_type, m.value
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    measured = [
        {
            "id": r["id"],
            "compound_id": r["compound_id"],
            "inchikey": r["inchikey"],
            "target_name": r["target_name"],
            "target_key": r["target_key"],
            "target_type": r["target_type"],
            "assay_key": r["assay_key"],
            "assay_type": r["assay_type"],
            "assay_description": r["assay_description"],
            "note": r["note"],
            "assay_format": r["assay_format"],
            "standard_type": r["standard_type"],
            "value": float(r["value"]),
            "unit": r["unit"],
            "relation": r["relation"],
            "raw_value": r["raw_value"],
            "evidence_class": r["evidence_class"],
            "species": r["species"],
            "variant_accession": r["variant_accession"],
            "variant_mutation": r["variant_mutation"],
            "pchembl_value": r["pchembl_value"],
            "potential_duplicate": bool(r["potential_duplicate"]),
            "validity_comment": r["validity_comment"],
            "document_ref": r["document_ref"],
            "document_patent_number": r["document_patent_number"],
            "document_doi": r["document_doi"],
            "document_pmid": r["document_pmid"],
            "source_url": r["source_url"],
            "source_record_id": r["source_record_id"],
            "source_name": r["source_name"],
            "extraction_method": r["extraction_method"],
            "provenance_state": r["provenance_state"],
            "dataset_version": r["dataset_version"],
            "retrieved_at": r["retrieved_at"].isoformat(),
        }
        for r in rows
    ]
    for row in measured:
        activity_class, rule = classify_potency(
            row["value"],
            row["unit"],
            row["relation"],
            row["standard_type"],
            threshold_nm,
        )
        row["activity_class"] = activity_class.value
        row["activity_class_rule"] = rule
    return measured


def coverage_matrix(engine: Engine) -> list[dict]:
    """Dated source-by-target coverage across every resolved target.

    This is the artifact the plan's acceptance criterion asks for: exact query
    identifiers, record counts, outcomes and versions, per source and target.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT t.id AS target_id, t.target_key, t.name AS target_name,
                       coalesce(t.gene_symbol, t.target_key) AS gene_symbol,
                       t.uniprot_accession, t.target_type, t.organism,
                       r.source_name, r.status, r.query, r.records_seen,
                       r.records_kept, r.records_excluded, r.rejection_counts,
                       r.dataset_version, r.source_version, r.latency_ms,
                       r.retrieved_at, r.warnings,
                       (SELECT count(DISTINCT tc.compound_id) FROM target_candidates tc
                         WHERE tc.target_id = t.id AND tc.source_name = r.source_name) AS candidates,
                       (SELECT count(DISTINCT tc.compound_id) FROM target_candidates tc
                         JOIN compounds c ON c.id = tc.compound_id
                         WHERE tc.target_id = t.id AND tc.source_name = r.source_name
                           AND coalesce(c.modality, 'unclassified')
                               IN ('small_molecule','unclassified')) AS small_molecule_candidates
                FROM source_retrievals r
                JOIN targets t ON t.id = r.target_id
                ORDER BY t.target_key, r.source_name
                """
            )
        ).mappings().all()
    return [
        {
            "target_id": r["target_id"],
            "target_key": r["target_key"],
            "target_name": r["target_name"],
            "gene_symbol": r["gene_symbol"],
            "uniprot_accession": r["uniprot_accession"],
            "target_type": r["target_type"],
            "organism": r["organism"],
            "source_name": r["source_name"],
            "status": r["status"],
            "query": _json(r["query"]) or {},
            "records_seen": r["records_seen"],
            "records_kept": r["records_kept"],
            "records_excluded": r["records_excluded"],
            "rejection_counts": _json(r["rejection_counts"]) or {},
            "candidates": int(r["candidates"] or 0),
            "small_molecule_candidates": int(r["small_molecule_candidates"] or 0),
            "dataset_version": r["dataset_version"],
            "source_version": r["source_version"],
            "latency_ms": r["latency_ms"],
            "retrieved_at": r["retrieved_at"].isoformat(),
            "warnings": list(_json(r["warnings"]) or []),
        }
        for r in rows
    ]
