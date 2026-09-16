"""Read/query orchestration over PostgreSQL (workloads B+C).

Interactive lookups happen here, server-side and paged (default 100, hard cap
500 per AGENTS.md §21). Nothing returns unbounded result sets.
"""
from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

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
                FROM current_compound_mentions
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
                JOIN current_compound_mentions m ON m.compound_id = c.id
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
                JOIN current_compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid {scope}
                GROUP BY c.id
                ORDER BY first_seen, c.inchikey
                OFFSET :offset LIMIT :limit
                """
            ),
            params,
        ).mappings().all()

    mentions = list_compound_mentions(
        engine, [r["id"] for r in compound_rows], family_id, document_id
    )

    items = [
        CompoundRow(compound=_row_to_compound(r), mentions=mentions.get(r["id"], []))
        for r in compound_rows
    ]
    return CompoundPage(total=total, offset=offset, limit=limit, items=items)


def list_compound_mentions(
    engine: Engine,
    compound_ids: list[uuid.UUID],
    family_id: uuid.UUID,
    document_id: uuid.UUID | None = None,
) -> dict[uuid.UUID, list[CompoundMention]]:
    """Hydrate a bounded result page with occurrences inside its query scope."""
    if not compound_ids:
        return {}
    scope = "AND m.document_id = :doc" if document_id else ""
    params = {"ids": compound_ids, "fid": family_id, "doc": document_id}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT m.id, m.compound_id, m.document_id, m.patent_label,
                       d.publication_number
                FROM current_compound_mentions m
                JOIN patent_documents d ON d.id = m.document_id
                WHERE m.compound_id = ANY(:ids) AND d.family_id = :fid {scope}
                ORDER BY d.publication_number, m.patent_label
                """
            ),
            params,
        ).mappings().all()
    mentions: dict[uuid.UUID, list[CompoundMention]] = {}
    for r in rows:
        mentions.setdefault(r["compound_id"], []).append(
            CompoundMention(
                id=r["id"], compound_id=r["compound_id"], document_id=r["document_id"],
                patent_label=r["patent_label"], publication_number=r["publication_number"],
            )
        )
    return mentions


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
                FROM current_compound_mentions m
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
                FROM current_evidence_records e
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


def list_dataset_infos(engine: Engine) -> list[dict]:
    """All loaded datasets (demo fixture and imported packages alike): the UI
    shows the real source inventory instead of a hardcoded demo label."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT source_name, dataset_version, synthetic, release_label,
                       files, notes, retrieved_at
                FROM dataset_info
                ORDER BY retrieved_at DESC
                """
            )
        ).mappings().all()
    out = []
    for r in rows:
        item = dict(r)
        item["retrieved_at"] = item["retrieved_at"].isoformat()
        out.append(item)
    return out


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


#: The versioned patent-corpus tables, as `kind: table`. Every one of them carries
#: `dataset_version`; a corpus surface that counted only some of them would
#: understate what a search can reach (B-01).
_CORPUS_KINDS = {
    "families": "patent_families",
    "documents": "patent_documents",
    "compounds": "compounds",
    "mentions": "compound_mentions",
    "evidence": "evidence_records",
    "measurements": "measurements",
}

#: Tables that also carry `source_name`, used to name a version whose source is
#: not registered in `dataset_info` (target investigations record it per row).
_VERSION_SOURCE_TABLES = ("measurements", "assays", "targets")


def read_publication_list(path: Path, column: str | None = None) -> list[str]:
    """Publication numbers from an operator's list file, in order, deduplicated.

    One number per line, or a CSV/TSV export with `column` naming the field. A
    `#` comment and a blank line are ignored. Values are kept exactly as written:
    normalizing a number here would hide a wrong number from a coverage report,
    which is the one thing this list is used for (B-01).
    """
    lines = [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else ("," if "," in lines[0] else None)
    numbers: list[str] = []
    if delimiter is None:
        # A single-column export has no delimiter to detect; its label row, if
        # any, must not be checked as if it were a publication number.
        if _looks_like_header(lines[0:1]):
            lines = lines[1:]
        numbers = [ln.strip() for ln in lines]
    else:
        rows = list(csv.reader(lines, delimiter=delimiter))
        header = rows[0]
        header_is_label = _looks_like_header(header)
        index = 0
        if column is not None:
            if column.isdigit():
                index = int(column)
            elif column in header:
                index = header.index(column)
            else:
                raise ValueError(
                    f"column {column!r} is not in {path.name} (header: {', '.join(header)})"
                )
        elif len(header) > 1:
            raise ValueError(
                f"{path.name} has {len(header)} columns; name the one holding publication "
                f"numbers with --column (header: {', '.join(header)})"
            )
        start = 1 if (header_is_label or column is not None) else 0
        for row in rows[start:]:
            if index < len(row) and row[index].strip():
                numbers.append(row[index].strip())
    seen: set[str] = set()
    unique: list[str] = []
    for number in numbers:
        if number in seen:
            continue
        seen.add(number)
        unique.append(number)
    return unique


#: Header labels an exported patent list uses; a first row matching one is a
#: label, not a publication number, and is skipped.
_PUBLICATION_HEADERS = {
    "patent", "patents", "patent_number", "patent number", "pn", "publication",
    "publication_number", "publication number", "number", "publicationnumber",
}


def _looks_like_header(fields: list[str]) -> bool:
    return any(field.strip().lower().replace("_", " ") in _PUBLICATION_HEADERS for field in fields[:2])


def publications_in_corpus(engine: Engine, numbers: Sequence[str]) -> set[str]:
    """Which of these publication numbers the loaded corpus actually holds.

    Exact and read-only: a number absent from the result was never imported, which
    is the fact an operator needs before concluding anything about a patent (B-01).
    """
    if not numbers:
        return set()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT publication_number FROM patent_documents "
                "WHERE publication_number = ANY(:numbers)"
            ),
            {"numbers": list(numbers)},
        ).all()
    return {r[0] for r in rows}


def corpus_summary(engine: Engine) -> dict:
    """What is actually loaded, by dataset version: the surface that makes
    "search real patents" mean "search this corpus, with these versions" (B-01).

    Counts are read from the tables themselves — never from a cached counter —
    so the surface cannot disagree with the data it describes. Each metric is one
    grouped scan, which is proportionate while the patent corpus lives in
    PostgreSQL (AGENTS.md §7: bulk datasets stay in DuckDB/Parquet); a corpus
    large enough for that to hurt is a measured problem with an obvious fix
    (maintained counters), not a reason to guess the numbers now.
    """
    kinds_sql = " UNION ALL ".join(
        f"SELECT '{kind}' AS kind, dataset_version, count(*) AS n, "
        f"count(*) FILTER (WHERE "
        + (
            "retracted_at IS NOT NULL"
            if table in ("compound_mentions", "evidence_records")
            else "false"
        )
        + f") AS retracted FROM {table} GROUP BY dataset_version"
        for kind, table in _CORPUS_KINDS.items()
    )
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT * FROM ({kinds_sql}) t")
        ).mappings().all()
        registered = conn.execute(
            text(
                """
                SELECT source_name, dataset_version, synthetic, release_label,
                       retrieved_at, files, notes
                  FROM dataset_info
                """
            )
        ).mappings().all()
        per_version_source: dict[str, str] = {}
        for table in _VERSION_SOURCE_TABLES:
            for r in conn.execute(
                text(f"SELECT DISTINCT dataset_version, source_name FROM {table}")
            ).mappings():
                per_version_source.setdefault(r["dataset_version"], r["source_name"])
        issues = conn.execute(
            text(
                "SELECT dataset_version, count(*) AS n FROM ingestion_issues "
                "GROUP BY dataset_version"
            )
        ).mappings().all()
        imports = conn.execute(
            text(
                """
                SELECT status, count(*) AS n, max(finished_at) AS last_finished_at
                  FROM import_jobs GROUP BY status
                """
            )
        ).mappings().all()
        last_error = conn.execute(
            text(
                """
                SELECT error, source_name, dataset_version, finished_at
                  FROM import_jobs
                 WHERE status = 'failed'
                 ORDER BY finished_at DESC NULLS LAST
                 LIMIT 1
                """
            )
        ).mappings().first()

    by_version: dict[str, dict] = {}
    for r in rows:
        entry = by_version.setdefault(
            r["dataset_version"],
            {"dataset_version": r["dataset_version"], **{k: 0 for k in _CORPUS_KINDS}},
        )
        entry[r["kind"]] = int(r["n"])
    for r in issues:
        entry = by_version.setdefault(
            r["dataset_version"],
            {"dataset_version": r["dataset_version"], **{k: 0 for k in _CORPUS_KINDS}},
        )
        entry["issues"] = int(r["n"])

    registry = {r["dataset_version"]: dict(r) for r in registered}
    sources = []
    for version, entry in by_version.items():
        info = registry.get(version) or {}
        files = info.get("files") or {}
        sources.append(
            {
                **{k: entry.get(k, 0) for k in _CORPUS_KINDS},
                "issues": entry.get("issues", 0),
                "dataset_version": version,
                "source_name": info.get("source_name") or per_version_source.get(version),
                "synthetic": bool(info.get("synthetic", False)),
                "release_label": info.get("release_label"),
                "retrieved_at": (
                    info["retrieved_at"].isoformat()
                    if info.get("retrieved_at") is not None
                    else None
                ),
                "notes": info.get("notes"),
                "files": len(files) if isinstance(files, dict) else 0,
                "registered": version in registry,
            }
        )
    # Registered sources first, then by size: an operator scanning this reads the
    # packages they imported before the per-row versions of a target investigation.
    sources.sort(
        key=lambda s: (
            not s["registered"],
            -(s["families"] + s["documents"] + s["compounds"]),
            s["dataset_version"],
        )
    )

    totals = {k: sum(int(s[k]) for s in sources) for k in _CORPUS_KINDS}
    totals["issues"] = sum(int(s["issues"]) for s in sources)
    status_counts = {r["status"]: int(r["n"]) for r in imports}
    last_finished = [r["last_finished_at"] for r in imports if r["last_finished_at"] is not None]
    notes = []
    unregistered = [s["dataset_version"] for s in sources if not s["registered"]]
    if unregistered:
        notes.append(
            "Not a registered import package (recorded per row by a source lookup): "
            + ", ".join(sorted(unregistered))
        )
    if status_counts.get("interrupted"):
        notes.append(
            f"{status_counts['interrupted']} import job(s) were interrupted; "
            "`python -m spago_core.import_package --status` lists them."
        )
    return {
        "sources": sources,
        "totals": totals,
        "imports": {
            "queued": status_counts.get("queued", 0),
            "running": status_counts.get("running", 0),
            "completed": status_counts.get("completed", 0),
            "failed": status_counts.get("failed", 0),
            "interrupted": status_counts.get("interrupted", 0),
            "last_finished_at": (
                max(last_finished).isoformat() if last_finished else None
            ),
            "last_error": (
                {
                    "source_name": last_error["source_name"],
                    "dataset_version": last_error["dataset_version"],
                    "error": last_error["error"],
                    "finished_at": (
                        last_error["finished_at"].isoformat()
                        if last_error["finished_at"] is not None
                        else None
                    ),
                }
                if last_error is not None
                else None
            ),
        },
        "notes": notes,
    }
