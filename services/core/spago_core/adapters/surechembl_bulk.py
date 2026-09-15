"""SureChEMBL bulk-data adapter (real source, PROD-01).

Consumes a local extract package written by `scripts/extract_surechembl.py`
in the official bulk Parquet schema (EMBL-EBI FTP, CC BY 4.0):

    patents.parquet              id, patent_number, country, publication_date,
                                family_id, cpc[], ipcr[], ipc[], ecla[],
                                assignee[], title
    compounds.parquet            id, smiles, inchi, inchi_key, mol_weight
    patent_compound_map.parquet  patent_id, compound_id, field_id
    manifest.json                source/release provenance written by the
                                extractor (release id, remote URLs+sizes,
                                extracted patents/families, retrieval time)

This adapter is the only place that knows that schema. It maps records into
the domain model honestly:

- family_key/doc ids derive from SureChEMBL numeric ids (stable, re-runnable);
- a mention is one (compound, document, patent-field) occurrence — the bulk
  data has no patent-local text labels or page numbers, so the label is the
  SureChEMBL compound id and the page stays "not provided" (never invented);
- evidence excerpts state what the record is; they never fake patent text;
- source URLs point at Espacenet's publication search so users keep their
  normal source-page workflow (a link, not automation);
- structures are re-normalized with RDKit; a disagreement between the source
  InChIKey and the canonical one is recorded as a warning, not overwritten
  silently (normalization decisions are recorded, AGENTS.md §11).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import duckdb
from spago_core.chemistry import StructureParseError, normalize

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

BULK_NAMESPACE = uuid.UUID("c1d4e7a2-5b69-4f8e-9a3b-7e2d1c8f4b20")

EXTRACTION_METHOD = "surechembl_bulk_import"

SOURCE_NAME = "surechembl_bulk"

# fields.parquet (official, release 2026-09-08): 1 desc, 2 clms, 3 abst,
# 4 ttl, 5 image, 6 molattachment.
FIELD_TO_EVIDENCE_TYPE = {
    1: (EvidenceSourceType.DESCRIPTION, "description"),
    2: (EvidenceSourceType.CLAIM, "claims"),
    3: (EvidenceSourceType.ABSTRACT, "abstract"),
    4: (EvidenceSourceType.TITLE, "title"),
    5: (EvidenceSourceType.FIGURE, "image"),
    6: (EvidenceSourceType.MOL_ATTACHMENT, "molattachment"),
}

MANIFEST_REQUIRED_KEYS = ("dataset_version", "synthetic", "retrieved_at")
# This adapter materializes a family extract, never an unrestricted bulk release.
MAX_PACKAGE_ROWS = 100_000


def _uid(kind: str, *parts) -> uuid.UUID:
    return uuid.uuid5(BULK_NAMESPACE, kind + ":" + "|".join(str(p) for p in parts))


def espacenet_link(patent_number: str) -> str:
    """A user-facing source link (opened manually by the user); SPAgo never
    automates or scrapes Espacenet (AGENTS.md §5)."""
    compact = patent_number.replace("-", "")
    return f"https://worldwide.espacenet.com/patent/search?q=pn%3D{compact}"


class SureChemblBulkAdapter:
    """Reads a real SureChEMBL extract package through DuckDB."""

    source_name = SOURCE_NAME

    def __init__(self, package_dir: Path) -> None:
        self.package_dir = Path(package_dir)
        self.patents_path = self.package_dir / "patents.parquet"
        self.compounds_path = self.package_dir / "compounds.parquet"
        self.map_path = self.package_dir / "patent_compound_map.parquet"
        self.manifest_path = self.package_dir / "manifest.json"
        missing = [
            p.name
            for p in (self.patents_path, self.compounds_path, self.map_path)
            if not p.exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"SureChEMBL package under {self.package_dir} is missing: {', '.join(missing)}. "
                "Create one with scripts/extract_surechembl.py."
            )
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"Package manifest not found: {self.manifest_path}")
        manifest = json.loads(self.manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("Package manifest must be an object.")
        for key in MANIFEST_REQUIRED_KEYS:
            if key not in manifest:
                raise ValueError(f"Package manifest is missing required key {key!r}.")
        if type(manifest["synthetic"]) is not bool:
            raise ValueError("Package manifest synthetic must be a boolean.")
        if not isinstance(manifest["dataset_version"], str) or not manifest["dataset_version"].strip():
            raise ValueError("Package manifest dataset_version must be a nonempty string.")
        retrieved_at = datetime.fromisoformat(manifest["retrieved_at"])
        if retrieved_at.tzinfo is None:
            raise ValueError("Package manifest retrieved_at must include a timezone.")

    def load(self) -> AdapterResult:
        warnings: list[str] = []
        issues: list[StructureIssue] = []
        manifest = json.loads(self.manifest_path.read_text())
        dataset_version = manifest["dataset_version"]
        synthetic = manifest["synthetic"]
        retrieved_at = datetime.fromisoformat(manifest["retrieved_at"])

        with duckdb.connect() as con:
            con.execute("SET enable_progress_bar=false")
            for path in (self.patents_path, self.compounds_path, self.map_path):
                count = con.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
                if count > MAX_PACKAGE_ROWS:
                    raise ValueError(f"{path.name} exceeds the family-extract limit of {MAX_PACKAGE_ROWS} rows.")
            if con.execute(
                "SELECT count(*) != count(DISTINCT id) FROM read_parquet(?)",
                [str(self.compounds_path)],
            ).fetchone()[0]:
                raise ValueError("Package contains null or duplicate compound identifiers.")
            patents = con.execute(
                """
                SELECT id, patent_number, country, publication_date, family_id,
                       assignee, title
                FROM read_parquet(?)
                ORDER BY publication_date, patent_number
                """, [str(self.patents_path)]
            ).fetchall()
            compound_rows = con.execute(
                """
                SELECT DISTINCT m.compound_id, c.smiles, c.inchi_key
                FROM read_parquet(?) m
                LEFT JOIN read_parquet(?) c
                  ON c.id = m.compound_id
                ORDER BY m.compound_id
                """, [str(self.map_path), str(self.compounds_path)]
            ).fetchall()
            map_rows = con.execute(
                """
                SELECT m.patent_id, m.compound_id, m.field_id
                FROM read_parquet(?) m
                ORDER BY m.patent_id, m.compound_id, m.field_id
                """, [str(self.map_path)]
            ).fetchall()

        patent_by_id = {r[0]: r for r in patents}
        if len(patent_by_id) != len(patents) or len({r[1] for r in patents}) != len(patents):
            raise ValueError("Package contains duplicate patent identifiers.")
        if any(row[0] is None or not row[1] or row[4] is None for row in patents):
            raise ValueError("Package patent identifiers and family IDs must not be null.")
        families: dict[int, PatentFamily] = {}
        documents: list[PatentDocument] = []
        for row in patents:
            (pid, number, country, pub_date, family_id, assignee, title) = row
            if family_id not in families:
                families[family_id] = PatentFamily(
                    id=_uid("family", family_id),
                    family_key=f"SURECHEMBL-{family_id}",
                    title=(title or f"Patent family {family_id}").strip(),
                )
            documents.append(
                PatentDocument(
                    id=_uid("doc", number),
                    publication_number=number,
                    family_id=families[family_id].id,
                    title=title,
                    abstract=None,  # not included in the bulk extract
                    assignee="; ".join(assignee or []) or None,
                    publication_date=pub_date,
                    jurisdiction=country,
                    doc_type=self._doc_type(number),
                )
            )

        mentions: list[MentionRecord] = []
        evidence: list[EvidenceRecord] = []
        seen_mentions: set[tuple[int, int, int]] = set()
        for patent_id, compound_id, field_id in map_rows:
            patent = patent_by_id.get(patent_id)
            if patent is None:
                raise ValueError(f"Map row references patent id {patent_id} outside the package.")
            key = (patent_id, compound_id, field_id)
            if key in seen_mentions:
                continue
            seen_mentions.add(key)
            field_info = FIELD_TO_EVIDENCE_TYPE.get(field_id)
            if field_info is None:
                warnings.append(f"Unknown patent field id {field_id} (compound {compound_id}); source field preserved without assigning a patent section.")
                field_info = (EvidenceSourceType.EXTERNAL_DATABASE, f"unknown field {field_id}")
            evidence_type, field_name = field_info
            source_record_id = f"SC-{compound_id}"
            # The label carries the patent field: the same compound occurs
            # once per (document, field) and the mention unique key is
            # (compound, document, label) — a bare id would collapse the
            # description and claims occurrences into one row.
            label = f"SC {compound_id} ({field_name})"
            mention_id = _uid("mention", patent_id, compound_id, field_id)
            mentions.append(
                MentionRecord(
                    mention_id=mention_id,
                    source_record_id=source_record_id,
                    document_id=patent[1],
                    patent_label=label,
                    raw_smiles="",  # filled from the compound table below
                    source_field=field_name,
                )
            )
            evidence.append(
                EvidenceRecord(
                    id=_uid("evidence", patent_id, compound_id, field_id),
                    compound_mention_id=mention_id,
                    document_id=_uid("doc", patent[1]),
                    source_type=evidence_type,
                    section=f"{field_name} (SureChEMBL field)",
                    page=None,  # the bulk extract has no page numbers: shown as not provided
                    compound_local_id=source_record_id,
                    raw_excerpt=(
                        f"SureChEMBL record SC-{compound_id}: structure extracted from the "
                        f"{field_name} of {patent[1]}. Source text is not part of the bulk "
                        "extract; open the patent to verify."
                    ),
                    source_url=espacenet_link(patent[1]),
                    extraction_method=EXTRACTION_METHOD,
                    provenance_state=ProvenanceState.MACHINE_EXTRACTED,
                    confidence=0.8,
                    dataset_version=dataset_version,
                    retrieved_at=retrieved_at,
                )
            )

        # Attach structures to mentions; missing ones become recorded issues
        # (never silently dropped). Identity is decided by RDKit at ingest.
        smiles_by_compound: dict[int, str] = {}
        for compound_id, smiles, source_inchikey in compound_rows:
            if compound_id is None or compound_id in smiles_by_compound:
                raise ValueError("Package has null or conflicting compound identifiers.")
            smiles_by_compound[compound_id] = smiles or ""
            if smiles and source_inchikey:
                try:
                    canonical_key = normalize(smiles).inchikey
                except StructureParseError:
                    continue  # ingestion records malformed structures
                if canonical_key != source_inchikey:
                    warnings.append(
                        f"SC-{compound_id}: source InChIKey {source_inchikey} differs from "
                        f"RDKit InChIKey {canonical_key}; RDKit identity used, source retained in package."
                    )
        for mention in mentions:
            compound_id = int(mention.source_record_id.replace("SC-", ""))
            smiles = smiles_by_compound.get(compound_id, "")
            mention.raw_smiles = smiles
            if not smiles:
                issues.append(
                    StructureIssue(
                        source_record_id=mention.source_record_id,
                        document_id=mention.document_id,
                        patent_label=mention.patent_label,
                        raw_smiles="",
                        issue="missing_smiles_in_source_package",
                    )
                )

        dataset_info = DatasetInfo(
            source_name=SOURCE_NAME,
            dataset_version=dataset_version,
            synthetic=synthetic,
            release_label=manifest.get("release"),
            files=manifest.get("files", {}),
            notes=manifest.get("note"),
            retrieved_at=retrieved_at,
        )

        return AdapterResult(
            envelope=SourceEnvelope(
                source_name=SOURCE_NAME,
                source_version=manifest.get("release", "bulk"),
                dataset_version=dataset_version,
                retrieved_at=retrieved_at,
                synthetic=synthetic,
                warnings=warnings,
            ),
            families=list(families.values()),
            documents=documents,
            mentions=mentions,
            evidence=evidence,
            dataset_info=dataset_info,
            issues=issues,
        )

    @staticmethod
    def _doc_type(patent_number: str) -> str | None:
        """Kind code from the publication number (A=application, B=grant)."""
        parts = patent_number.split("-")
        if len(parts) == 3 and parts[2].upper().startswith("A"):
            return "application"
        if len(parts) == 3 and parts[2].upper().startswith("B"):
            return "grant"
        return None
