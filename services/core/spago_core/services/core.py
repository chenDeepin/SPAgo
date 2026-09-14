"""Read/query orchestration over PostgreSQL (workloads B+C).

Interactive lookups happen here, server-side and paged (default 100, hard cap
500 per AGENTS.md §21). Nothing returns unbounded result sets.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.domain import (
    Compound,
    CompoundMention,
    EvidenceRecord,
    EvidenceSourceType,
    PatentDocument,
    PatentFamily,
    ProvenanceState,
)


class NotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class FamilyOverview:
    family: PatentFamily
    documents: list[PatentDocument]
    mention_counts: dict[str, int]  # document_id -> mention count


@dataclass(frozen=True)
class CompoundRow:
    compound: Compound
    mentions: list[CompoundMention]


@dataclass(frozen=True)
class CompoundPage:
    total: int
    offset: int
    limit: int
    items: list[CompoundRow]


def clamp_page(offset: int, limit: int, default: int, maximum: int) -> tuple[int, int]:
    offset = max(0, offset)
    limit = max(1, min(limit if limit > 0 else default, maximum))
    return offset, limit


def _row_to_compound(row) -> Compound:
    return Compound(
        id=row.id,
        canonical_smiles=row.canonical_smiles,
        inchikey=row.inchikey,
        inchi=row.inchi,
        molecular_formula=row.molecular_formula,
        molecular_weight=row.molecular_weight,
        hbd=row.hbd,
        hba=row.hba,
        tpsa=row.tpsa,
        logp=row.logp,
        has_stereo=row.has_stereo,
        is_multi_component=row.is_multi_component,
        scaffold=row.scaffold,
        normalization_notes=row.normalization_notes,
    )


def get_family_overview(engine: Engine, family_id: uuid.UUID) -> FamilyOverview:
    with engine.connect() as conn:
        family_row = conn.execute(
            text("SELECT id, family_key, title FROM patent_families WHERE id = :id"),
            {"id": family_id},
        ).mappings().first()
        if family_row is None:
            raise NotFoundError(f"Family {family_id} not found")
        doc_rows = conn.execute(
            text(
                """
                SELECT id, publication_number, family_id, title, abstract, assignee,
                       publication_date, jurisdiction, doc_type
                FROM patent_documents WHERE family_id = :fid ORDER BY publication_date
                """
            ),
            {"fid": family_id},
        ).mappings().all()
        count_rows = conn.execute(
            text(
                """
                SELECT document_id, count(*) AS n
                FROM compound_mentions
                WHERE document_id IN (SELECT id FROM patent_documents WHERE family_id = :fid)
                GROUP BY document_id
                """
            ),
            {"fid": family_id},
        ).all()

    documents = [
        PatentDocument(
            id=r["id"],
            publication_number=r["publication_number"],
            family_id=r["family_id"],
            title=r["title"],
            abstract=r["abstract"],
            assignee=r["assignee"],
            publication_date=r["publication_date"],
            jurisdiction=r["jurisdiction"],
            doc_type=r["doc_type"],
        )
        for r in doc_rows
    ]
    return FamilyOverview(
        family=PatentFamily(id=family_row["id"], family_key=family_row["family_key"], title=family_row["title"]),
        documents=documents,
        mention_counts={str(r[0]): int(r[1]) for r in count_rows},
    )


def find_patent(engine: Engine, publication_number: str) -> tuple[PatentDocument, FamilyOverview]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT family_id FROM patent_documents WHERE publication_number = :pn"),
            {"pn": publication_number},
        ).first()
    if row is None:
        raise NotFoundError(f"Patent {publication_number!r} not found in current dataset")
    overview = get_family_overview(engine, row[0])
    document = next(d for d in overview.documents if d.publication_number == publication_number)
    return document, overview


def list_family_compounds(
    engine: Engine,
    family_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 100,
) -> CompoundPage:
    """Compounds in scope (family-wide or per document), each with its in-scope mentions.

    Family scope deduplicates across member documents; a compound mentioned in
    two documents is one row carrying two mentions.
    """
    scope = "AND m.document_id = :doc" if document_id else ""
    params: dict = {"fid": family_id, "offset": offset, "limit": limit}
    if document_id:
        params["doc"] = document_id

    with engine.connect() as conn:
        total = conn.execute(
            text(
                f"""
                SELECT count(DISTINCT c.id)
                FROM compounds c
                JOIN compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid {scope}
                """
            ),
            params,
        ).scalar_one()

        compound_rows = conn.execute(
            text(
                f"""
                SELECT c.*, min(m.created_at) AS first_seen
                FROM compounds c
                JOIN compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid {scope}
                GROUP BY c.id
                ORDER BY first_seen, c.inchikey
                OFFSET :offset LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

        mentions: dict[uuid.UUID, list[CompoundMention]] = {}
        if compound_rows:
            ids = [r["id"] for r in compound_rows]
            mention_rows = conn.execute(
                text(
                    f"""
                    SELECT m.id, m.compound_id, m.document_id, m.patent_label,
                           d.publication_number
                    FROM compound_mentions m
                    JOIN patent_documents d ON d.id = m.document_id
                    WHERE m.compound_id = ANY(:ids) {"AND m.document_id = :doc" if document_id else ""}
                    ORDER BY d.publication_number, m.patent_label
                    """
                ),
                params | {"ids": ids},
            ).mappings().all()
            for r in mention_rows:
                mentions.setdefault(r["compound_id"], []).append(
                    CompoundMention(
                        id=r["id"],
                        compound_id=r["compound_id"],
                        document_id=r["document_id"],
                        patent_label=r["patent_label"],
                        publication_number=r["publication_number"],
                    )
                )

    items = [
        CompoundRow(compound=_row_to_compound(r), mentions=mentions.get(r["id"], []))
        for r in compound_rows
    ]
    return CompoundPage(total=total, offset=offset, limit=limit, items=items)


def get_compound(engine: Engine, compound_id: uuid.UUID) -> CompoundRow:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM compounds WHERE id = :id"),
            {"id": compound_id},
        ).mappings().first()
        if row is None:
            raise NotFoundError(f"Compound {compound_id} not found")
        mention_rows = conn.execute(
            text(
                """
                SELECT m.id, m.compound_id, m.document_id, m.patent_label, d.publication_number
                FROM compound_mentions m
                JOIN patent_documents d ON d.id = m.document_id
                WHERE m.compound_id = :id
                ORDER BY d.publication_number, m.patent_label
                """
            ),
            {"id": compound_id},
        ).mappings().all()

    mentions = [
        CompoundMention(
            id=r["id"],
            compound_id=r["compound_id"],
            document_id=r["document_id"],
            patent_label=r["patent_label"],
            publication_number=r["publication_number"],
        )
        for r in mention_rows
    ]
    return CompoundRow(compound=_row_to_compound(row), mentions=mentions)


def list_compound_evidence(engine: Engine, compound_id: uuid.UUID) -> list[EvidenceRecord]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT e.*, d.publication_number
                FROM evidence_records e
                LEFT JOIN patent_documents d ON d.id = e.document_id
                WHERE e.compound_id = :id
                ORDER BY e.retrieved_at, e.id
                """
            ),
            {"id": compound_id},
        ).mappings().all()
    return [
        EvidenceRecord(
            id=r["id"],
            compound_id=r["compound_id"],
            compound_mention_id=r["compound_mention_id"],
            document_id=r["document_id"],
            publication_number=r["publication_number"],
            source_type=EvidenceSourceType(r["source_type"]),
            section=r["section"],
            page=r["page"],
            table_ref=r["table_ref"],
            figure_ref=r["figure_ref"],
            paragraph=r["paragraph"],
            compound_local_id=r["compound_local_id"],
            raw_excerpt=r["raw_excerpt"],
            source_url=r["source_url"],
            extraction_method=r["extraction_method"],
            provenance_state=ProvenanceState(r["provenance_state"]),
            confidence=r["confidence"],
            dataset_version=r["dataset_version"],
            retrieved_at=r["retrieved_at"],
        )
        for r in rows
    ]


def get_compound_smiles(engine: Engine, compound_id: uuid.UUID) -> str:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT canonical_smiles FROM compounds WHERE id = :id"),
            {"id": compound_id},
        ).first()
    if row is None:
        raise NotFoundError(f"Compound {compound_id} not found")
    return row[0]


def get_dataset_info(engine: Engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT source_name, dataset_version, synthetic, release_label, files, notes, retrieved_at
                FROM dataset_info
                ORDER BY retrieved_at DESC LIMIT 1
                """
            )
        ).mappings().first()
        if row is None:
            return None
        return dict(row)


def count_ingestion_issues(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM ingestion_issues")).scalar_one())


def list_ingestion_issues(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT dataset_version, source_record_id, document_id, patent_label, raw_smiles, issue
                FROM ingestion_issues ORDER BY created_at
                """
            )
        ).mappings().all()
    return [dict(r) for r in rows]
