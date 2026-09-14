"""Bioactivity read services (Milestone 3)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class ActivityView:
    compound_id: uuid.UUID
    target_name: str | None
    assay_key: str
    assay_type: str | None
    standard_type: str
    value: float
    unit: str
    relation: str
    source_name: str
    extraction_method: str
    provenance_state: str
    dataset_version: str
    retrieved_at: str


def compound_activity(engine: Engine, compound_id: uuid.UUID) -> list[ActivityView]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT m.compound_id, t.name AS target_name, a.assay_key, a.assay_type,
                       m.standard_type, m.value, m.unit, m.relation,
                       m.source_name, m.extraction_method, m.provenance_state,
                       m.dataset_version, m.retrieved_at
                FROM measurements m
                JOIN assays a ON a.id = m.assay_id
                JOIN targets t ON t.id = a.target_id
                WHERE m.compound_id = :cid
                ORDER BY t.name, a.assay_key, m.standard_type
                """
            ),
            {"cid": compound_id},
        ).mappings().all()
    return [_row_to_view(r) for r in rows]


def family_activity(
    engine: Engine,
    family_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
) -> dict[str, list[ActivityView]]:
    """Measurements for every compound in the family (or one document's scope)."""
    scope = "AND m2.document_id = :doc" if document_id else ""
    params: dict = {"fid": family_id}
    if document_id:
        params["doc"] = document_id
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT m.compound_id, t.name AS target_name, a.assay_key, a.assay_type,
                       m.standard_type, m.value, m.unit, m.relation,
                       m.source_name, m.extraction_method, m.provenance_state,
                       m.dataset_version, m.retrieved_at
                FROM measurements m
                JOIN assays a ON a.id = m.assay_id
                JOIN targets t ON t.id = a.target_id
                WHERE m.compound_id IN (
                    SELECT DISTINCT m2.compound_id
                    FROM compound_mentions m2
                    JOIN patent_documents d ON d.id = m2.document_id
                    WHERE d.family_id = :fid {scope}
                )
                ORDER BY t.name, a.assay_key, m.standard_type
                """
            ),
            params,
        ).mappings().all()
    grouped: dict[str, list[ActivityView]] = {}
    for r in rows:
        grouped.setdefault(str(r["compound_id"]), []).append(_row_to_view(r))
    return grouped


def _row_to_view(r) -> ActivityView:
    return ActivityView(
        compound_id=r["compound_id"],
        target_name=r["target_name"],
        assay_key=r["assay_key"],
        assay_type=r["assay_type"],
        standard_type=r["standard_type"],
        value=float(r["value"]),
        unit=r["unit"],
        relation=r["relation"],
        source_name=r["source_name"],
        extraction_method=r["extraction_method"],
        provenance_state=r["provenance_state"],
        dataset_version=r["dataset_version"],
        retrieved_at=r["retrieved_at"].isoformat(),
    )
