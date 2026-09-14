"""Fixture adapter: simplified SureChEMBL-style Parquet via DuckDB.

Demonstrates the adapter contract end-to-end on small synthetic data. The real
SureChEMBL bulk releases have a different schema; this adapter is the only place
that knows this one.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from spago_core.domain import (
    AdapterResult,
    DatasetInfo,
    EvidenceRecord,
    EvidenceSourceType,
    MentionRecord,
    PatentDocument,
    PatentFamily,
    ProvenanceState,
    SourceEnvelope,
    StructureIssue,
)

# Stable namespace so adapter-produced ids are deterministic across loads and
# seeding stays naturally idempotent.
FIXTURE_NAMESPACE = uuid.UUID("7b6c9a52-2f3e-4a17-9a2f-5e1d3c4b6a01")

EXTRACTION_METHOD = "surechembl_simplified_fixture_import"

_SOURCE_FIELD_TO_EVIDENCE_TYPE = {
    "description": EvidenceSourceType.DESCRIPTION,
    "example": EvidenceSourceType.EXAMPLE,
    "abstract": EvidenceSourceType.ABSTRACT,
    "claims": EvidenceSourceType.CLAIM,
    "title": EvidenceSourceType.TITLE,
    "table": EvidenceSourceType.TABLE,
    "figure": EvidenceSourceType.FIGURE,
}

SCHEMA_COLUMNS = {
    "document_id": "VARCHAR",
    "compound_id": "VARCHAR",
    "patent_label": "VARCHAR",
    "smiles": "VARCHAR",
    "source_field": "VARCHAR",
    "section": "VARCHAR",
    "page": "INTEGER",
}


def _uid(kind: str, *parts: str) -> uuid.UUID:
    return uuid.uuid5(FIXTURE_NAMESPACE, kind + ":" + "|".join(parts))


class SureChemblFixtureAdapter:
    """Reads the synthetic fixture Parquet files through DuckDB.

    Workload A (bulk analytical) and ingestion share this read path; interactive
    serving happens from PostgreSQL after seeding.
    """

    source_name = "surechembl_simplified_fixture"

    def __init__(self, fixture_dir: Path) -> None:
        self.records_path = Path(fixture_dir) / "surechembl" / "surechembl_demo_fixture.parquet"
        self.patents_path = Path(fixture_dir) / "patents" / "patent_documents_demo_fixture.parquet"
        self.manifest_path = Path(fixture_dir) / "manifest.json"
        if not self.records_path.exists() or not self.patents_path.exists():
            raise FileNotFoundError(
                f"Fixture Parquet files not found under {fixture_dir}; "
                "generate them with data/fixtures/scripts/build_fixtures.py"
            )

    def _envelope(self, warnings: list[str]) -> SourceEnvelope:
        manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        return SourceEnvelope(
            source_name=self.source_name,
            source_version="fixture",
            dataset_version=manifest.get("dataset_version", "unknown"),
            retrieved_at=datetime.now(timezone.utc),
            synthetic=bool(manifest.get("synthetic", False)),
            warnings=warnings,
        )

    def load(self) -> AdapterResult:
        warnings: list[str] = []
        issues: list[StructureIssue] = []
        manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        dataset_version = manifest.get("dataset_version", "unknown")

        patents_df = duckdb.sql(
            f"SELECT * FROM read_parquet('{self.patents_path.as_posix()}') ORDER BY publication_number"
        )
        records_df = duckdb.sql(
            f"SELECT * FROM read_parquet('{self.records_path.as_posix()}') ORDER BY document_id, compound_id"
        )

        retrieved_at = datetime.now(timezone.utc)
        families: dict[str, PatentFamily] = {}
        documents: list[PatentDocument] = []
        for row in patents_df.fetchall():
            (
                publication_number, family_key, title, abstract,
                assignee, publication_date, jurisdiction, doc_type,
            ) = row
            family_id = _uid("family", family_key)
            families.setdefault(
                family_key,
                PatentFamily(id=family_id, family_key=family_key, title=f"Illustrative family {family_key}"),
            )
            documents.append(
                PatentDocument(
                    id=_uid("doc", publication_number),
                    publication_number=publication_number,
                    family_id=family_id,
                    title=title,
                    abstract=abstract,
                    assignee=assignee,
                    publication_date=publication_date,
                    jurisdiction=jurisdiction,
                    doc_type=doc_type,
                )
            )

        mentions: list[MentionRecord] = []
        evidence: list[EvidenceRecord] = []

        for row in records_df.fetchall():
            (
                document_id, compound_id, patent_label, smiles,
                source_field, section, page,
            ) = row

            if not smiles or not smiles.strip():
                issues.append(
                    StructureIssue(
                        source_record_id=compound_id,
                        document_id=document_id,
                        patent_label=patent_label,
                        raw_smiles=smiles or "",
                        issue="missing_smiles",
                    )
                )
                continue

            evidence_type = _SOURCE_FIELD_TO_EVIDENCE_TYPE.get(source_field)
            if evidence_type is None:
                warnings.append(
                    f"Record {compound_id}: unknown source_field {source_field!r}; treated as description"
                )
                evidence_type = EvidenceSourceType.DESCRIPTION

            mention_id = _uid("mention", compound_id, document_id, patent_label or "")
            mentions.append(
                MentionRecord(
                    mention_id=mention_id,
                    source_record_id=compound_id,
                    document_id=document_id,
                    patent_label=patent_label,
                    raw_smiles=smiles,
                    source_field=source_field,
                )
            )

            confidence = 1.0 if page is not None else 0.5
            evidence.append(
                EvidenceRecord(
                    id=_uid("evidence", compound_id),
                    compound_mention_id=mention_id,
                    document_id=_uid("doc", document_id),
                    source_type=evidence_type,
                    section=section,
                    page=page,
                    compound_local_id=compound_id,
                    raw_excerpt=(
                        f"Synthetic demo source record {compound_id} "
                        f"({source_field}"
                        + (f", {section}" if section else "")
                        + ")."
                    ),
                    source_url=None,  # fixture points at no external location: UI must not fake a link
                    extraction_method=EXTRACTION_METHOD,
                    provenance_state=ProvenanceState.MACHINE_EXTRACTED,
                    confidence=confidence,
                    dataset_version=dataset_version,
                    retrieved_at=retrieved_at,
                )
            )

        dataset_info = DatasetInfo(
            source_name=self.source_name,
            dataset_version=dataset_version,
            synthetic=bool(manifest.get("synthetic", False)),
            release_label=manifest.get("generated_on"),
            files=manifest.get("files", {}),
            notes=manifest.get("note"),
            retrieved_at=retrieved_at,
        )

        return AdapterResult(
            envelope=self._envelope(warnings),
            families=list(families.values()),
            documents=documents,
            mentions=mentions,
            evidence=evidence,
            dataset_info=dataset_info,
            issues=issues,
        )
