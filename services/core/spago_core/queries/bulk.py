"""Bulk analytical layer: DuckDB over Parquet (workload A).

Kept strictly separate from the PostgreSQL serving store. Large filters,
aggregations, and dataset exploration belong here; interactive lookups belong
to the PostgreSQL services (PROMPT.md §11).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class DocumentRecordCounts:
    document_id: str
    record_count: int


def compound_counts_by_document(fixture_dir: Path) -> list[DocumentRecordCounts]:
    """Raw per-document structure-occurrence counts, straight from Parquet."""
    path = Path(fixture_dir) / "surechembl" / "surechembl_demo_fixture.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Bulk fixture not found: {path}")
    rows = duckdb.sql(
        f"""
        SELECT document_id, count(*) AS record_count
        FROM read_parquet('{path.as_posix()}')
        GROUP BY document_id
        ORDER BY document_id
        """
    ).fetchall()
    return [DocumentRecordCounts(document_id=r[0], record_count=int(r[1])) for r in rows]


def records_for_document(fixture_dir: Path, document_id: str) -> list[tuple]:
    """All raw structure records for one document (bulk read path proof)."""
    path = Path(fixture_dir) / "surechembl" / "surechembl_demo_fixture.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Bulk fixture not found: {path}")
    return duckdb.execute(
        f"""
        SELECT document_id, compound_id, patent_label, smiles, source_field, section, page
        FROM read_parquet('{path.as_posix()}')
        WHERE document_id = ?
        ORDER BY compound_id
        """,
        [document_id],
    ).fetchall()
