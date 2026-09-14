"""Idempotent fixture seeding: adapter -> RDKit normalization -> PostgreSQL.

Run:  python -m spago_core.seed

Deduplicates compounds by InChIKey, preserves per-document mentions, records
malformed structures as ingestion issues, and never upgrades provenance states.
Safe to run repeatedly (stable ids + upserts).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.adapters import BioactivityFixtureAdapter, SureChemblFixtureAdapter
from spago_core.chemistry import NormalizedStructure, StructureParseError, murcko_scaffold, normalize
from spago_core.config import get_settings
from spago_core.db import make_engine, run_migrations

logger = logging.getLogger(__name__)

# Stable compound id namespace: identity is the InChIKey.
_COMPOUND_NAMESPACE = uuid.UUID("3d2f1a8e-6c05-4d9b-9d3a-1f2e8b7c5a10")


@dataclass
class SeedReport:
    families: int = 0
    documents: int = 0
    compounds: int = 0
    mentions: int = 0
    evidence: int = 0
    measurements: int = 0
    issues: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dataset_version: str = "unknown"

    def summary(self) -> str:
        return (
            f"dataset={self.dataset_version} families={self.families} documents={self.documents} "
            f"compounds={self.compounds} mentions={self.mentions} evidence={self.evidence} "
            f"measurements={self.measurements} "
            f"issues={len(self.issues)} warnings={len(self.warnings)}"
        )


def _compound_id(inchikey: str) -> uuid.UUID:
    return uuid.uuid5(_COMPOUND_NAMESPACE, "compound:" + inchikey)


def seed(
    engine: Engine,
    fixture_dir: Path | None = None,
    migrations_dir: Path | None = None,
) -> SeedReport:
    settings = get_settings()
    fixture_dir = fixture_dir or settings.fixture_dir
    migrations_dir = migrations_dir or settings.migrations_dir

    applied = run_migrations(engine, migrations_dir)
    if applied:
        logger.info("applied migrations: %s", applied)

    adapter = SureChemblFixtureAdapter(fixture_dir)
    result = adapter.load()
    report = SeedReport(
        warnings=list(result.envelope.warnings),
        dataset_version=result.envelope.dataset_version,
    )

    # --- normalize chemistry once per unique raw SMILES -------------------------
    unique_smiles = {m.raw_smiles for m in result.mentions}
    normalized: dict[str, NormalizedStructure] = {}
    for raw in sorted(unique_smiles):
        try:
            normalized[raw] = normalize(raw)
        except StructureParseError as exc:
            for mention in result.mentions:
                if mention.raw_smiles == raw:
                    report.issues.append(
                        {
                            "dataset_version": result.envelope.dataset_version,
                            "source_record_id": mention.source_record_id,
                            "document_id": mention.document_id,
                            "patent_label": mention.patent_label,
                            "raw_smiles": raw,
                            "issue": str(exc),
                        }
                    )
    report.compounds = len({n.inchikey for n in normalized.values()})

    # --- Murcko scaffolds (deterministic, per unique canonical SMILES) ---------
    scaffold_by_smiles: dict[str, str | None] = {}
    for norm in normalized.values():
        if norm.canonical_smiles in scaffold_by_smiles:
            continue
        try:
            scaffold_by_smiles[norm.canonical_smiles] = murcko_scaffold(norm.canonical_smiles)
        except StructureParseError:
            scaffold_by_smiles[norm.canonical_smiles] = None

    with engine.begin() as conn:
        # --- dataset provenance --------------------------------------------------
        if result.dataset_info is not None:
            info = result.dataset_info
            conn.execute(
                text(
                    """
                    INSERT INTO dataset_info (id, source_name, dataset_version, synthetic,
                                              release_label, files, notes, retrieved_at)
                    VALUES (:id, :source_name, :dataset_version, :synthetic,
                            :release_label, CAST(:files AS jsonb), :notes, :retrieved_at)
                    ON CONFLICT (source_name, dataset_version) DO UPDATE
                      SET synthetic = EXCLUDED.synthetic,
                          release_label = EXCLUDED.release_label,
                          files = EXCLUDED.files,
                          notes = EXCLUDED.notes,
                          retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": uuid.uuid5(_COMPOUND_NAMESPACE, f"dataset:{info.source_name}:{info.dataset_version}"),
                    "source_name": info.source_name,
                    "dataset_version": info.dataset_version,
                    "synthetic": info.synthetic,
                    "release_label": info.release_label,
                    "files": json.dumps(info.files),
                    "notes": info.notes,
                    "retrieved_at": info.retrieved_at,
                },
            )

        # --- ingestion issues: replace this dataset's records ---------------------
        conn.execute(
            text("DELETE FROM ingestion_issues WHERE dataset_version = :v"),
            {"v": result.envelope.dataset_version},
        )
        for issue in result.issues:
            report.issues.append(
                {
                    "dataset_version": result.envelope.dataset_version,
                    "source_record_id": issue.source_record_id,
                    "document_id": issue.document_id,
                    "patent_label": issue.patent_label,
                    "raw_smiles": issue.raw_smiles,
                    "issue": issue.issue,
                }
            )
        for issue in report.issues:
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_issues (id, dataset_version, source_record_id,
                                                  document_id, patent_label, raw_smiles, issue)
                    VALUES (:id, :dataset_version, :source_record_id,
                            :document_id, :patent_label, :raw_smiles, :issue)
                    """
                ),
                {"id": uuid.uuid4(), **issue},
            )

        # --- families -------------------------------------------------------------
        for family in result.families:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_families (id, family_key, title, source_name,
                                                 dataset_version, retrieved_at)
                    VALUES (:id, :family_key, :title, :source_name, :dataset_version, :retrieved_at)
                    ON CONFLICT (family_key) DO UPDATE
                      SET title = EXCLUDED.title,
                          source_name = EXCLUDED.source_name,
                          dataset_version = EXCLUDED.dataset_version,
                          retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": family.id,
                    "family_key": family.family_key,
                    "title": family.title,
                    "source_name": result.envelope.source_name,
                    "dataset_version": result.envelope.dataset_version,
                    "retrieved_at": result.envelope.retrieved_at,
                },
            )
            report.families += 1

        # --- documents ------------------------------------------------------------
        for doc in result.documents:
            conn.execute(
                text(
                    """
                    INSERT INTO patent_documents (id, family_id, publication_number, title, abstract,
                                                  assignee, publication_date, jurisdiction, doc_type,
                                                  source_name, dataset_version, retrieved_at)
                    VALUES (:id, :family_id, :publication_number, :title, :abstract,
                            :assignee, :publication_date, :jurisdiction, :doc_type,
                            :source_name, :dataset_version, :retrieved_at)
                    ON CONFLICT (publication_number) DO UPDATE
                      SET title = EXCLUDED.title,
                          abstract = EXCLUDED.abstract,
                          assignee = EXCLUDED.assignee,
                          publication_date = EXCLUDED.publication_date,
                          jurisdiction = EXCLUDED.jurisdiction,
                          doc_type = EXCLUDED.doc_type,
                          dataset_version = EXCLUDED.dataset_version,
                          retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": doc.id,
                    "family_id": doc.family_id,
                    "publication_number": doc.publication_number,
                    "title": doc.title,
                    "abstract": doc.abstract,
                    "assignee": doc.assignee,
                    "publication_date": doc.publication_date,
                    "jurisdiction": doc.jurisdiction,
                    "doc_type": doc.doc_type,
                    "source_name": result.envelope.source_name,
                    "dataset_version": result.envelope.dataset_version,
                    "retrieved_at": result.envelope.retrieved_at,
                },
            )
            report.documents += 1

        # --- compounds (dedup by InChIKey) ----------------------------------------
        for norm in normalized.values():            conn.execute(
                text(
                    """
                    INSERT INTO compounds (id, canonical_smiles, inchikey, inchi, molecular_formula,
                                           molecular_weight, hbd, hba, tpsa, logp,
                                           has_stereo, is_multi_component, dataset_version, m,
                                           scaffold)
                    VALUES (:id, :canonical_smiles, :inchikey, :inchi, :molecular_formula,
                            :molecular_weight, :hbd, :hba, :tpsa, :logp,
                            :has_stereo, :is_multi_component, :dataset_version,
                            mol_from_smiles(:canonical_smiles),
                            :scaffold)
                    ON CONFLICT (inchikey) DO UPDATE
                      SET canonical_smiles = EXCLUDED.canonical_smiles,
                          inchi = EXCLUDED.inchi,
                          molecular_formula = EXCLUDED.molecular_formula,
                          molecular_weight = EXCLUDED.molecular_weight,
                          hbd = EXCLUDED.hbd, hba = EXCLUDED.hba,
                          tpsa = EXCLUDED.tpsa, logp = EXCLUDED.logp,
                          has_stereo = EXCLUDED.has_stereo,
                          is_multi_component = EXCLUDED.is_multi_component,
                          dataset_version = EXCLUDED.dataset_version,
                          m = mol_from_smiles(EXCLUDED.canonical_smiles),
                          scaffold = EXCLUDED.scaffold
                    """
                ),                {
                    "id": _compound_id(norm.inchikey),
                    "canonical_smiles": norm.canonical_smiles,
                    "inchikey": norm.inchikey,
                    "inchi": norm.inchi,
                    "molecular_formula": norm.molecular_formula,
                    "molecular_weight": norm.molecular_weight,
                    "hbd": norm.hbd,
                    "hba": norm.hba,
                    "tpsa": norm.tpsa,
                    "logp": norm.logp,
                    "has_stereo": norm.has_stereo,
                    "is_multi_component": norm.is_multi_component,
                    "dataset_version": result.envelope.dataset_version,
                    "scaffold": scaffold_by_smiles.get(norm.canonical_smiles),
                },
            )

        # --- mentions + evidence ----------------------------------------------------
        doc_id_by_number = {doc.publication_number: doc.id for doc in result.documents}
        for mention in result.mentions:
            norm = normalized.get(mention.raw_smiles)
            if norm is None:
                continue  # malformed structure: recorded as an issue above
            document_id = doc_id_by_number[mention.document_id]
            compound_id = _compound_id(norm.inchikey)
            conn.execute(
                text(
                    """
                    INSERT INTO compound_mentions (id, compound_id, document_id, patent_label,
                                                   source_record_id, source_name, dataset_version,
                                                   retrieved_at)
                    VALUES (:id, :compound_id, :document_id, :patent_label,
                            :source_record_id, :source_name, :dataset_version, :retrieved_at)
                    ON CONFLICT (compound_id, document_id, patent_label) DO UPDATE
                      SET source_record_id = EXCLUDED.source_record_id,
                          dataset_version = EXCLUDED.dataset_version,
                          retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": mention.mention_id,
                    "compound_id": compound_id,
                    "document_id": document_id,
                    "patent_label": mention.patent_label,
                    "source_record_id": mention.source_record_id,
                    "source_name": result.envelope.source_name,
                    "dataset_version": result.envelope.dataset_version,
                    "retrieved_at": result.envelope.retrieved_at,
                },
            )
            report.mentions += 1

        for ev in result.evidence:
            mention = next((m for m in result.mentions if m.mention_id == ev.compound_mention_id), None)
            if mention is None or mention.raw_smiles not in normalized:
                continue
            norm = normalized[mention.raw_smiles]
            conn.execute(
                text(
                    """
                    INSERT INTO evidence_records (id, compound_id, compound_mention_id, document_id,
                                                  source_type, section, page, compound_local_id,
                                                  raw_excerpt, source_url, extraction_method,
                                                  provenance_state, confidence, dataset_version,
                                                  retrieved_at)
                    VALUES (:id, :compound_id, :compound_mention_id, :document_id,
                            :source_type, :section, :page, :compound_local_id,
                            :raw_excerpt, :source_url, :extraction_method,
                            :provenance_state, :confidence, :dataset_version, :retrieved_at)
                    ON CONFLICT (id) DO UPDATE
                      SET compound_id = EXCLUDED.compound_id,
                          compound_mention_id = EXCLUDED.compound_mention_id,
                          document_id = EXCLUDED.document_id,
                          source_type = EXCLUDED.source_type,
                          section = EXCLUDED.section,
                          page = EXCLUDED.page,
                          compound_local_id = EXCLUDED.compound_local_id,
                          raw_excerpt = EXCLUDED.raw_excerpt,
                          source_url = EXCLUDED.source_url,
                          extraction_method = EXCLUDED.extraction_method,
                          provenance_state = EXCLUDED.provenance_state,
                          confidence = EXCLUDED.confidence,
                          dataset_version = EXCLUDED.dataset_version,
                          retrieved_at = EXCLUDED.retrieved_at
                    """
                ),
                {
                    "id": ev.id,
                    "compound_id": _compound_id(norm.inchikey),
                    "compound_mention_id": ev.compound_mention_id,
                    "document_id": ev.document_id,
                    "source_type": ev.source_type.value,
                    "section": ev.section,
                    "page": ev.page,
                    "compound_local_id": ev.compound_local_id,
                    "raw_excerpt": ev.raw_excerpt,
                    "source_url": ev.source_url,
                    "extraction_method": ev.extraction_method,
                    "provenance_state": ev.provenance_state.value,
                    "confidence": ev.confidence,
                    "dataset_version": ev.dataset_version,
                    "retrieved_at": ev.retrieved_at,
                },
            )
            report.evidence += 1

        # --- bioactivity (M3) --------------------------------------------------------
        # Compound mapping goes through the patent-local source record ids from the
        # same dataset; label matches never create measurements.
        compound_by_source_record: dict[str, uuid.UUID] = {}
        for mention in result.mentions:
            norm = normalized.get(mention.raw_smiles)
            if norm is not None:
                compound_by_source_record[mention.source_record_id] = _compound_id(norm.inchikey)

        try:
            activity_result = BioactivityFixtureAdapter(fixture_dir).load()
        except FileNotFoundError:
            activity_result = None
            report.warnings.append("No bioactivity fixture present; measurements not loaded.")

        if activity_result is not None:
            report.warnings.extend(activity_result.envelope.warnings)
            # Runs on the enclosing seed transaction: measurement inserts must see
            # the compounds upserted earlier in this same transaction.
            for rec in activity_result.records:
                compound_id = compound_by_source_record.get(rec.compound_source_id)
                if compound_id is None:
                    report.warnings.append(
                        f"Activity record {rec.source_record_id}: compound "
                        f"{rec.compound_source_id} not in this dataset; skipped"
                    )
                    continue
                target_id = uuid.uuid5(_COMPOUND_NAMESPACE, f"target:{rec.target_key}")
                assay_id = uuid.uuid5(_COMPOUND_NAMESPACE, f"assay:{rec.assay_key}")
                conn.execute(
                    text(
                        """
                        INSERT INTO targets (id, target_key, name, source_name,
                                             dataset_version, retrieved_at)
                        VALUES (:id, :target_key, :name, :source_name,
                                :dataset_version, :retrieved_at)
                        ON CONFLICT (target_key) DO UPDATE
                          SET name = EXCLUDED.name,
                              source_name = EXCLUDED.source_name,
                              dataset_version = EXCLUDED.dataset_version,
                              retrieved_at = EXCLUDED.retrieved_at
                        """
                    ),
                    {
                        "id": target_id,
                        "target_key": rec.target_key,
                        "name": rec.target_name,
                        "source_name": activity_result.envelope.source_name,
                        "dataset_version": activity_result.envelope.dataset_version,
                        "retrieved_at": activity_result.envelope.retrieved_at,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO assays (id, assay_key, target_id, assay_type,
                                            source_name, dataset_version, retrieved_at)
                        VALUES (:id, :assay_key, :target_id, :assay_type,
                                :source_name, :dataset_version, :retrieved_at)
                        ON CONFLICT (assay_key) DO UPDATE
                          SET target_id = EXCLUDED.target_id,
                              assay_type = EXCLUDED.assay_type,
                              source_name = EXCLUDED.source_name,
                              dataset_version = EXCLUDED.dataset_version,
                              retrieved_at = EXCLUDED.retrieved_at
                        """
                    ),
                    {
                        "id": assay_id,
                        "assay_key": rec.assay_key,
                        "target_id": target_id,
                        "assay_type": rec.assay_type,
                        "source_name": activity_result.envelope.source_name,
                        "dataset_version": activity_result.envelope.dataset_version,
                        "retrieved_at": activity_result.envelope.retrieved_at,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO measurements (id, compound_id, assay_id, standard_type,
                                                  value, unit, relation, source_record_id,
                                                  source_name, extraction_method,
                                                  provenance_state, confidence,
                                                  dataset_version, retrieved_at)
                        VALUES (:id, :compound_id, :assay_id, :standard_type,
                                :value, :unit, :relation, :source_record_id,
                                :source_name, :extraction_method,
                                'machine_extracted', :confidence,
                                :dataset_version, :retrieved_at)
                        ON CONFLICT (compound_id, assay_id, standard_type, source_record_id) DO UPDATE
                          SET value = EXCLUDED.value,
                              unit = EXCLUDED.unit,
                              relation = EXCLUDED.relation,
                              dataset_version = EXCLUDED.dataset_version,
                              retrieved_at = EXCLUDED.retrieved_at
                        """
                    ),
                    {
                        "id": uuid.uuid5(_COMPOUND_NAMESPACE, f"measurement:{rec.source_record_id}"),
                        "compound_id": compound_id,
                        "assay_id": assay_id,
                        "standard_type": rec.standard_type,
                        "value": rec.value,
                        "unit": rec.unit,
                        "relation": rec.relation,
                        "source_record_id": rec.source_record_id,
                        "source_name": activity_result.envelope.source_name,
                        "extraction_method": "bioactivity_simplified_fixture_import",
                        "confidence": 1.0 if activity_result.envelope.synthetic else 0.8,
                        "dataset_version": activity_result.envelope.dataset_version,
                        "retrieved_at": activity_result.envelope.retrieved_at,
                    },
                )
                report.measurements += 1

    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = get_settings()
    engine = make_engine()
    try:
        report = seed(engine)
    finally:
        engine.dispose()
    logger.info("seed complete: %s", report.summary())
    if report.issues:
        for issue in report.issues:
            logger.warning(
                "ingestion issue: record=%s document=%s label=%s: %s",
                issue.get("source_record_id"),
                issue.get("document_id"),
                issue.get("patent_label"),
                issue.get("issue"),
            )


if __name__ == "__main__":
    main()
