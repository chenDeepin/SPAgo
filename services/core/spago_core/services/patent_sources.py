"""B-24 — patent-led compound discovery: what a source declares for a publication.

The product's first promise is "enter a patent, see its compounds". The corpus
answers that for imported families; for a publication SPAgo does not hold — or
holds thinly — this service asks a source what it declares for that number, under
a stated and versioned match rule, and keeps the answer apart from the corpus:

- **A declaration is not an occurrence.** No `compound_mentions` row is written,
  nothing enters a potency reference verdict, and the family's counts do not move
  (AGENTS.md §11). The declared set lives in its own tables with its own labels.
- **Identity is shared.** Declared structures go through `persist_compounds`, so a
  molecule declared by ChEMBL and seen in a patent is one compound row with one
  depiction — the difference is which *relations* it has, not which structure.
- **The rule travels.** `match_rule` + the bounds + the retrieval time are stored
  with the set and returned with every read, so a stored set can be read back
  years later with the rule that produced it.
- **A failed lookup is stored as failed** (the previous set is kept, not thrown
  away), so "we asked and the source failed" never reads as "not queried" — the
  distinction the patent coverage audit needs (B-26).
- **Classes are computed on read**, by the same deterministic code as the
  screening-reference verdict, never persisted (AGENTS.md §11).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.adapters.chembl_discovery import (
    DEFAULT_MAX_DECLARED_ACTIVITIES,
    DECLARED_DOCUMENT_LIMIT,
    MATCH_RULE,
    MATCH_RULE_TEXT,
    ChEMBLDiscoveryAdapter,
    DeclaredCompounds,
)
from spago_core.chemistry import clean_external_smiles
from spago_core.chemistry.activities import ActivityClass, classify_activity, potency_label
from spago_core.config import get_settings
from spago_core.domain.patent_numbers import normalize_patent_number
from spago_core.services.compound_store import (
    COMPOUND_NAMESPACE,
    compound_id_for_inchikey,
    persist_compounds,
)
from spago_core.services.discovery import normalize_external_records
from spago_core.services.reference import policy_from_settings

SOURCE_NAME = "chembl"
EXTRACTION_METHOD = "chembl_webclient_patent"

#: One page of declared rows by default; the cap matches the API row cap (§13).
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500

#: `database_curated`: the same state the target-led path stores for the same
#: source. A ChEMBL record is that database's curated assertion, not the original
#: document's text (AGENTS.md §10).
PROVENANCE_STATE = "database_curated"


class PatentSourceError(ValueError):
    """The requested publication number is not one SPAgo can query."""


def _lookup_id(publication_number: str, source_name: str) -> uuid.UUID:
    return uuid.uuid5(COMPOUND_NAMESPACE, f"patent_source_lookup:{source_name}:{publication_number}")


def _row_id(lookup_id: uuid.UUID, source_record_id: str) -> uuid.UUID:
    return uuid.uuid5(COMPOUND_NAMESPACE, f"patent_source_compound:{lookup_id}:{source_record_id}")


def _json(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


class PatentSourceService:
    """Coordinates the patent-led lookup and its stored form."""

    def __init__(self, chembl: Optional[ChEMBLDiscoveryAdapter] = None) -> None:
        self.chembl = chembl or ChEMBLDiscoveryAdapter()

    # -- write path -----------------------------------------------------------

    def lookup(
        self,
        engine: Engine,
        publication_number: str,
        *,
        max_activities: int = DEFAULT_MAX_DECLARED_ACTIVITIES,
        max_documents: int = DECLARED_DOCUMENT_LIMIT,
    ) -> dict:
        """Ask the source what it declares for this publication and store it.

        Runs the bounded lookup, normalizes the structures through the shared
        compound identity, and replaces this lookup's rows in one transaction. A
        failed lookup updates the status and warnings but keeps the rows of the
        last successful attempt, so a transient source outage does not destroy a
        set the user already has.
        """
        requested = (publication_number or "").strip()
        token = normalize_patent_number(requested)
        if not token:
            raise PatentSourceError(
                "A source lookup needs a publication number (country code plus at "
                f"least six digits); '{requested}' is not one."
            )

        result = self.chembl.declared_compounds(
            requested, max_documents=max_documents, max_activities=max_activities
        )
        return self._store(engine, result)

    @staticmethod
    def _write_lookup(conn, result: DeclaredCompounds, rejections: dict[str, int]) -> None:
        """Insert or update this publication+source's lookup row (one current row)."""
        conn.execute(
            text(
                """
                INSERT INTO patent_source_lookups (
                    id, publication_number, requested_number, source_name,
                    source_version, dataset_version, match_rule, status,
                    documents, near_matches, warnings, rejection_counts,
                    records_seen, records_excluded, bounds, retrieved_at)
                VALUES (
                    :id, :publication_number, :requested_number, :source_name,
                    :source_version, :dataset_version, :match_rule, :status,
                    :documents, :near_matches, :warnings, :rejection_counts,
                    :records_seen, :records_excluded, :bounds, :retrieved_at)
                ON CONFLICT (publication_number, source_name) DO UPDATE SET
                    requested_number = EXCLUDED.requested_number,
                    source_version = EXCLUDED.source_version,
                    dataset_version = EXCLUDED.dataset_version,
                    match_rule = EXCLUDED.match_rule,
                    status = EXCLUDED.status,
                    documents = EXCLUDED.documents,
                    near_matches = EXCLUDED.near_matches,
                    warnings = EXCLUDED.warnings,
                    rejection_counts = EXCLUDED.rejection_counts,
                    records_seen = EXCLUDED.records_seen,
                    records_excluded = EXCLUDED.records_excluded,
                    bounds = EXCLUDED.bounds,
                    retrieved_at = EXCLUDED.retrieved_at
                """
            ),
            {
                "id": _lookup_id(result.publication_number, SOURCE_NAME),
                "publication_number": result.publication_number,
                "requested_number": result.requested_number,
                "source_name": SOURCE_NAME,
                "source_version": result.envelope.source_version,
                "dataset_version": result.envelope.dataset_version,
                "match_rule": result.match_rule,
                "status": result.status,
                "documents": json.dumps(result.documents),
                "near_matches": json.dumps(result.near_matches),
                "warnings": json.dumps(result.warnings),
                "rejection_counts": json.dumps(rejections),
                "records_seen": result.records_seen,
                "records_excluded": result.records_excluded,
                "bounds": json.dumps(result.bounds),
                "retrieved_at": result.envelope.retrieved_at,
            },
        )

    def _store(self, engine: Engine, result: DeclaredCompounds) -> dict:
        lookup_id = _lookup_id(result.publication_number, SOURCE_NAME)

        if result.status == "failed":
            # Keep whatever the last successful attempt stored: the reader is told
            # both times, and a source outage cannot delete a set.
            with engine.begin() as conn:
                self._write_lookup(conn, result, result.rejection_counts)
            return self.read(engine, result.publication_number)

        normalized, _modality, norm_rejections = normalize_external_records(result.records)
        rejections = dict(result.rejection_counts)
        for reason, count in norm_rejections.items():
            rejections[reason] = rejections.get(reason, 0) + count

        with engine.begin() as conn:
            persist_compounds(conn, normalized)
            self._write_lookup(conn, result, rejections)
            # This attempt's set replaces the previous one; a stored lookup is the
            # latest answer, not an accumulating history (a diff would be its own
            # item).
            conn.execute(
                text("DELETE FROM patent_source_compounds WHERE lookup_id = :id"),
                {"id": lookup_id},
            )
            for record in result.records:
                cleaned, _notes = clean_external_smiles(
                    record.raw_smiles or record.compound_source_id or ""
                )
                candidate = normalized.get(cleaned)
                if candidate is None:
                    # Normalization refused the structure (already counted as an
                    # ingestion issue): never stored as a compound.
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO patent_source_compounds (
                            id, lookup_id, compound_id, source_record_id,
                            source_molecule_id, source_molecule_name, standard_type,
                            value, unit, relation, raw_value, pchembl_value,
                            potential_duplicate, validity_comment, assay_key,
                            assay_type, assay_description, target_key, target_name,
                            species, variant_accession, variant_mutation, document_ref,
                            document_patent_number, document_doi, document_pmid,
                            source_url, provenance_state, dataset_version, retrieved_at)
                        VALUES (
                            :id, :lookup_id, :compound_id, :source_record_id,
                            :source_molecule_id, :source_molecule_name, :standard_type,
                            :value, :unit, :relation, :raw_value, :pchembl_value,
                            :potential_duplicate, :validity_comment, :assay_key,
                            :assay_type, :assay_description, :target_key, :target_name,
                            :species, :variant_accession, :variant_mutation, :document_ref,
                            :document_patent_number, :document_doi, :document_pmid,
                            :source_url, :provenance_state, :dataset_version, :retrieved_at)
                        ON CONFLICT (lookup_id, source_record_id) DO UPDATE SET
                            compound_id = EXCLUDED.compound_id,
                            value = EXCLUDED.value,
                            unit = EXCLUDED.unit,
                            relation = EXCLUDED.relation,
                            raw_value = EXCLUDED.raw_value,
                            pchembl_value = EXCLUDED.pchembl_value,
                            potential_duplicate = EXCLUDED.potential_duplicate,
                            validity_comment = EXCLUDED.validity_comment,
                            assay_type = EXCLUDED.assay_type,
                            assay_description = EXCLUDED.assay_description,
                            target_key = EXCLUDED.target_key,
                            target_name = EXCLUDED.target_name,
                            species = EXCLUDED.species,
                            document_ref = EXCLUDED.document_ref,
                            document_patent_number = EXCLUDED.document_patent_number,
                            document_doi = EXCLUDED.document_doi,
                            document_pmid = EXCLUDED.document_pmid,
                            source_url = EXCLUDED.source_url,
                            dataset_version = EXCLUDED.dataset_version,
                            retrieved_at = EXCLUDED.retrieved_at
                        """
                    ),
                    {
                        "id": _row_id(lookup_id, record.source_record_id),
                        "lookup_id": lookup_id,
                        "compound_id": compound_id_for_inchikey(candidate.inchikey),
                        "source_record_id": record.source_record_id,
                        "source_molecule_id": record.source_molecule_id,
                        "source_molecule_name": record.source_molecule_name,
                        "standard_type": record.standard_type,
                        "value": record.value,
                        "unit": record.unit,
                        "relation": record.relation,
                        "raw_value": record.raw_value,
                        "pchembl_value": record.pchembl_value,
                        "potential_duplicate": record.potential_duplicate,
                        "validity_comment": record.validity_comment,
                        "assay_key": record.assay_key or None,
                        "assay_type": record.assay_type,
                        "assay_description": record.assay_description,
                        "target_key": record.target_key or None,
                        "target_name": record.target_name,
                        "species": record.species,
                        "variant_accession": record.variant_accession,
                        "variant_mutation": record.variant_mutation,
                        "document_ref": record.document_ref,
                        "document_patent_number": record.document_patent_number,
                        "document_doi": record.document_doi,
                        "document_pmid": record.document_pmid,
                        "source_url": record.source_url,
                        "provenance_state": PROVENANCE_STATE,
                        "dataset_version": record.source_dataset_version
                        or result.envelope.dataset_version,
                        "retrieved_at": result.envelope.retrieved_at,
                    },
                )

        return self.read(engine, result.publication_number)

    # -- read path ------------------------------------------------------------

    def read(
        self,
        engine: Engine,
        publication_number: str,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """The stored declared set for a publication, or `not_queried`."""
        requested = (publication_number or "").strip()
        token = normalize_patent_number(requested) or requested
        limit = max(1, min(int(limit), MAX_PAGE_SIZE))
        offset = max(0, int(offset))
        policy = policy_from_settings(get_settings())

        with engine.connect() as conn:
            lookup = (
                conn.execute(
                    text(
                        """
                        SELECT id, publication_number, requested_number, source_name,
                               source_version, dataset_version, match_rule, status,
                               documents, near_matches, warnings, rejection_counts,
                               records_seen, records_excluded, bounds, retrieved_at
                          FROM patent_source_lookups
                         WHERE publication_number = :token AND source_name = :source
                        """
                    ),
                    {"token": token, "source": SOURCE_NAME},
                )
                .mappings()
                .first()
            )
            if lookup is None:
                return self._not_queried(token, requested, policy)

            rows = (
                conn.execute(
                    text(
                        """
                        SELECT c.id AS row_id, c.compound_id, c.source_record_id,
                               c.source_molecule_id, c.source_molecule_name,
                               c.standard_type, c.value, c.unit, c.relation,
                               c.raw_value, c.pchembl_value, c.potential_duplicate,
                               c.validity_comment, c.assay_key, c.assay_type,
                               c.assay_description, c.target_key, c.target_name,
                               c.species, c.variant_accession, c.variant_mutation,
                               c.document_ref, c.document_patent_number,
                               c.document_doi, c.document_pmid, c.source_url,
                               c.provenance_state, c.dataset_version,
                               c.retrieved_at,
                               cmp.inchikey, cmp.canonical_smiles,
                               cmp.molecular_formula, cmp.molecular_weight,
                               cmp.modality
                          FROM patent_source_compounds c
                          JOIN compounds cmp ON cmp.id = c.compound_id
                         WHERE c.lookup_id = :id
                         ORDER BY c.standard_type, c.value, c.compound_id
                        """
                    ),
                    {"id": lookup["id"]},
                )
                .mappings()
                .all()
            )

        classes: list[dict] = []
        for row in rows:
            activity_class, rule = classify_activity(
                row["value"],
                row["unit"],
                row["relation"],
                row["standard_type"],
                policy.threshold_nm,
            )
            classes.append(
                {
                    **dict(row),
                    "activity_class": activity_class.value,
                    "activity_class_rule": rule,
                    "potency_label": potency_label(
                        row["standard_type"], row["value"], row["unit"], row["relation"]
                    ),
                }
            )

        counts: dict[str, int] = {member.value: 0 for member in ActivityClass}
        compounds: set[str] = set()
        for row in classes:
            counts[row["activity_class"]] += 1
            compounds.add(str(row["compound_id"]))

        page = classes[offset : offset + limit]
        rows_retrieved_at = None
        if rows:
            rows_retrieved_at = max(row["retrieved_at"] for row in rows).isoformat()

        return {
            "publication_number": lookup["publication_number"],
            "requested_number": lookup["requested_number"],
            "source_name": lookup["source_name"],
            "source_version": lookup["source_version"],
            "dataset_version": lookup["dataset_version"],
            "status": lookup["status"],
            "match_rule": lookup["match_rule"],
            "match_rule_text": MATCH_RULE_TEXT if lookup["match_rule"] == MATCH_RULE else None,
            "retrieved_at": lookup["retrieved_at"].isoformat(),
            "rows_retrieved_at": rows_retrieved_at,
            "documents": _json(lookup["documents"]),
            "near_matches": _json(lookup["near_matches"]),
            "warnings": _json(lookup["warnings"]),
            "rejection_counts": _json(lookup["rejection_counts"]),
            "bounds": _json(lookup["bounds"]),
            "records_seen": lookup["records_seen"],
            "records_excluded": lookup["records_excluded"],
            "row_count": len(rows),
            "compound_count": len(compounds),
            "activity_class_counts": counts,
            "activity_classes_with_a_class": sum(
                counts[member.value]
                for member in ActivityClass
                if member is not ActivityClass.NOT_APPLICABLE
            ),
            "reference_threshold_nM": policy.threshold_nm,
            "reference_threshold_label": policy.threshold_label,
            "reference_policy_version": policy.version,
            "offset": offset,
            "limit": limit,
            "rows": [self._row(row) for row in page],
        }

    def read_all(self, engine: Engine, publication_number: str) -> dict:
        """The whole stored set, for an export that must not be a loaded page.

        An export covers the requested scope server-side (§ export contract); the
        declared set is bounded at 500 records per lookup, so this is a paged read
        rather than a background job.
        """
        view = self.read(engine, publication_number, limit=MAX_PAGE_SIZE)
        while len(view["rows"]) < view["row_count"]:
            page = self.read(
                engine,
                publication_number,
                offset=len(view["rows"]),
                limit=MAX_PAGE_SIZE,
            )
            if not page["rows"]:
                break
            view["rows"].extend(page["rows"])
        return view

    def export(self, engine: Engine, publication_number: str, *, fmt: str = "csv"):
        """`(filename, text)` for the declared set, or an error explaining why not."""
        from spago_core.services.export import (
            ExportScopeError,
            render_declared_compounds_csv,
            render_declared_compounds_sdf,
        )

        if fmt not in {"csv", "sdf"}:
            raise PatentSourceError(f"Unsupported export format '{fmt}'.")
        view = self.read_all(engine, publication_number)
        if view["status"] == "not_queried":
            raise ExportScopeError(
                f"No source lookup is stored for {view['publication_number']}; run the "
                "lookup first, so the file states which set it holds."
            )
        if not view["rows"]:
            raise ExportScopeError(
                f"The stored lookup for {view['publication_number']} holds no declared "
                f"records (status: {view['status']}), so there is nothing to export."
            )
        text = (
            render_declared_compounds_csv(view)
            if fmt == "csv"
            else render_declared_compounds_sdf(view)
        )
        filename = (
            f"spago-{view['publication_number']}-source-declared-{view['source_name']}.{fmt}"
        )
        return filename, text

    def _not_queried(self, token: str, requested: str, policy) -> dict:
        return {
            "publication_number": token,
            "requested_number": requested,
            "source_name": SOURCE_NAME,
            "source_version": None,
            "dataset_version": None,
            "status": "not_queried",
            "match_rule": MATCH_RULE,
            "match_rule_text": MATCH_RULE_TEXT,
            "retrieved_at": None,
            "rows_retrieved_at": None,
            "documents": [],
            "near_matches": [],
            "warnings": [],
            "rejection_counts": {},
            "bounds": {
                "max_documents": DECLARED_DOCUMENT_LIMIT,
                "max_activities": DEFAULT_MAX_DECLARED_ACTIVITIES,
            },
            "records_seen": 0,
            "records_excluded": 0,
            "row_count": 0,
            "compound_count": 0,
            "activity_class_counts": {member.value: 0 for member in ActivityClass},
            "activity_classes_with_a_class": 0,
            "reference_threshold_nM": policy.threshold_nm,
            "reference_threshold_label": policy.threshold_label,
            "reference_policy_version": policy.version,
            "not_queried_reason": (
                "No source lookup has been run for this publication. That is not "
                "'the source knows nothing': nothing was asked."
            ),
            "offset": 0,
            "limit": DEFAULT_PAGE_SIZE,
            "rows": [],
        }

    @staticmethod
    def _row(row: Any) -> dict:
        return {
            "row_id": str(row["row_id"]),
            "compound_id": str(row["compound_id"]),
            "inchikey": row["inchikey"],
            "canonical_smiles": row["canonical_smiles"],
            "molecular_formula": row["molecular_formula"],
            "molecular_weight": row["molecular_weight"],
            "modality": row["modality"],
            "source_record_id": row["source_record_id"],
            "source_molecule_id": row["source_molecule_id"],
            "source_molecule_name": row["source_molecule_name"],
            "standard_type": row["standard_type"],
            "value": row["value"],
            "unit": row["unit"],
            "relation": row["relation"],
            "raw_value": row["raw_value"],
            "pchembl_value": row["pchembl_value"],
            "potential_duplicate": row["potential_duplicate"],
            "validity_comment": row["validity_comment"],
            "activity_class": row["activity_class"],
            "activity_class_rule": row["activity_class_rule"],
            "potency_label": row["potency_label"],
            "assay_key": row["assay_key"],
            "assay_type": row["assay_type"],
            "assay_description": row["assay_description"],
            "target_key": row["target_key"],
            "target_name": row["target_name"],
            "species": row["species"],
            "variant_accession": row["variant_accession"],
            "variant_mutation": row["variant_mutation"],
            "document_ref": row["document_ref"],
            "document_patent_number": row["document_patent_number"],
            "document_doi": row["document_doi"],
            "document_pmid": row["document_pmid"],
            "source_url": row["source_url"],
            "provenance_state": row["provenance_state"],
            "dataset_version": row["dataset_version"],
            "retrieved_at": row["retrieved_at"].isoformat(),
        }


def _row_retrieved_at(rows) -> Optional[str]:  # pragma: no cover - small helper
    return max(row["retrieved_at"] for row in rows).isoformat() if rows else None
