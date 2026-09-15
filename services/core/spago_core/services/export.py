"""CSV / SDF export with provenance preserved (design doc contract 7).

Exports cover the requested server-side scope — family, document, an explicit
selection, or a structure query re-executed server-side — never silently just
the loaded page. Scope decides which mentions and evidence records are
attributed to a compound: a molecule that also occurs in another family never
exports the other family's documents, labels, or evidence (PROD-02).

The synchronous cap is enforced during the counting phase before export rows
are materialized. Stereo-aware substructure searches separately bound their
candidate set before loading candidates for the deterministic chirality check.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.services import NotFoundError

# Synchronous export cap. Beyond this a persisted background job is required
# (AGENTS.md §22); at current fixture scale synchronous is honest and simple.
MAX_EXPORT_ROWS = 5000

CSV_FIELDS = [
    "inchikey",
    "canonical_smiles",
    "molecular_formula",
    "molecular_weight",
    "hbd",
    "hba",
    "tpsa",
    "logp",
    "patent_numbers",
    "patent_labels",
    "evidence_records",
    "provenance_states",
    "evidence_source_urls",
    "dataset_version",
    "dataset_versions",
]


class ExportScopeError(ValueError):
    """The requested export scope is invalid (unknown ids, out-of-scope
    selection, or an unusable structure query). Maps to HTTP 422."""


class ExportTooLargeError(ValueError):
    """The scope covers more rows than the synchronous export allows; raised
    from the counting phase before any row is loaded. Maps to HTTP 422."""


@dataclass(frozen=True)
class StructureExportQuery:
    """A structure filter re-executed server-side at export time. The exported
    set is every compound matching the query in the family/document scope —
    including matches the browser never loaded."""

    mode: str  # exact | substructure | similarity
    smiles: str
    threshold: float | None = None
    filters: object | None = None  # services.structure_search.MoleculeFilters


@dataclass(frozen=True)
class ExportRow:
    compound_id: uuid.UUID
    inchikey: str
    canonical_smiles: str
    molecular_formula: str | None
    molecular_weight: float | None
    hbd: int | None
    hba: int | None
    tpsa: float | None
    logp: float | None
    patent_numbers: list[str]
    patent_labels: list[str]
    evidence_ids: list[str]
    provenance_states: list[str]
    evidence_source_urls: list[str]
    dataset_version: str
    dataset_versions: list[dict] = field(default_factory=list)


def _base_query(scope_clause: str, doc_clause_tpl: str, doc_params: dict) -> str:
    """Compound rows with mentions/evidence aggregated *within the scope*.

    The lateral aggregations join patent_documents with the same scope filter
    as the main query, so occurrences outside the requested family/document are
    never attributed to the exported compound (PROD-02: no cross-family
    evidence mixing). `doc_clause_tpl` is an alias template like
    '{alias}.family_id = :scope_fid' instantiated per lateral."""
    doc2 = doc_clause_tpl.format(alias="d2")
    doc3 = doc_clause_tpl.format(alias="d3")
    doc_ev = doc_clause_tpl.format(alias="ed")
    return f"""
        SELECT c.id, c.inchikey, c.canonical_smiles, c.molecular_formula,
               c.molecular_weight, c.hbd, c.hba, c.tpsa, c.logp,
               version_agg.versions AS dataset_versions,
               COALESCE(doc_agg.docs, '{{}}') AS docs,
               COALESCE(mention_agg.labels, '{{}}') AS labels,
               COALESCE(ev_agg.evidence, '{{}}') AS evidence,
               COALESCE(ev_agg.states, '{{}}') AS states,
               COALESCE(ev_agg.urls, '{{}}') AS urls
        FROM compounds c
        JOIN compound_mentions m ON m.compound_id = c.id
        JOIN patent_documents d ON d.id = m.document_id
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d2.publication_number) AS docs
            FROM compound_mentions m2
            JOIN patent_documents d2 ON d2.id = m2.document_id
            WHERE m2.compound_id = c.id AND {doc2}
        ) doc_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d3.publication_number || ':' || COALESCE(m3.patent_label, ''))
            AS labels
            FROM compound_mentions m3
            JOIN patent_documents d3 ON d3.id = m3.document_id
            WHERE m3.compound_id = c.id AND {doc3}
        ) mention_agg ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(v ORDER BY v.dataset_version, v.source_name) AS versions
            FROM (
                SELECT DISTINCT m3.source_name, m3.dataset_version
                FROM compound_mentions m3
                JOIN patent_documents d3 ON d3.id = m3.document_id
                WHERE m3.compound_id = c.id AND {doc3}
            ) v
        ) version_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(e.id ORDER BY e.id) AS evidence,
                   array_agg(e.provenance_state ORDER BY e.id) AS states,
                   array_agg(e.source_url ORDER BY e.id) AS urls
            FROM evidence_records e
            JOIN patent_documents ed ON ed.id = e.document_id
            WHERE e.compound_id = c.id AND {doc_ev}
        ) ev_agg ON true
        WHERE {scope_clause}
        GROUP BY c.id, doc_agg.docs, mention_agg.labels, version_agg.versions,
                 ev_agg.evidence, ev_agg.states, ev_agg.urls
        ORDER BY c.inchikey
    """


def _count_sql(scope_clause: str) -> str:
    return f"""
        SELECT count(DISTINCT c.id)
        FROM compounds c
        JOIN compound_mentions m ON m.compound_id = c.id
        JOIN patent_documents d ON d.id = m.document_id
        WHERE {scope_clause}
    """


def _resolve_structure_scope(
    engine: Engine,
    family_id: uuid.UUID,
    document_id: uuid.UUID | None,
    query: StructureExportQuery,
) -> list[uuid.UUID]:
    """Re-run the structure query server-side and return every matching
    compound id (bounded by the export cap). Raises ExportTooLargeError from
    the count when the match set exceeds the synchronous cap."""
    from spago_core.services import structure_search as ss

    try:
        mode = ss.SearchMode(query.mode)
    except ValueError as exc:
        raise ExportScopeError(f"Unknown structure search mode {query.mode!r}.") from exc
    threshold = (
        query.threshold if query.threshold is not None else ss.DEFAULT_SIMILARITY_THRESHOLD
    )
    # The search counts first and skips row loading when the export cap is
    # exceeded (stereo re-check uses its separate bounded candidate contract).
    result = ss.search_family_structures(
        engine,
        family_id,
        query.smiles,
        mode,
        document_id=document_id,
        threshold=threshold,
        filters=query.filters,
        offset=0,
        limit=MAX_EXPORT_ROWS,
        max_results=MAX_EXPORT_ROWS,
    )
    if result.total > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(
            f"Structure query matches {result.total} compounds; the synchronous "
            f"limit is {MAX_EXPORT_ROWS}. Narrow the query or the document scope."
        )
    return [r["id"] for r in result.rows]


def collect_export_rows(
    engine: Engine,
    family_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    compound_ids: list[uuid.UUID] | None = None,
    structure_query: StructureExportQuery | None = None,
) -> list[ExportRow]:
    """Server-side export scope.

    Priority: explicit selection > structure query > document > family. The
    aggregation scope for mentions/evidence always follows the family/document
    scope of the request, so a structure or selection export never pulls in
    occurrences from outside the family being viewed."""
    if family_id is None:
        raise ExportScopeError("export requires a family scope")
    if compound_ids == []:
        return []
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT id FROM patent_families WHERE id = :fid"), {"fid": family_id}
        ).first()
        if exists is None:
            raise NotFoundError(f"Family {family_id} not found")
        if document_id is not None and conn.execute(
            text("SELECT id FROM patent_documents WHERE id = :doc AND family_id = :fid"),
            {"doc": document_id, "fid": family_id},
        ).first() is None:
            raise ExportScopeError("The requested document is outside the family scope.")
    if compound_ids is None and structure_query is not None:
        compound_ids = _resolve_structure_scope(engine, family_id, document_id, structure_query)
        if not compound_ids:
            return []

    params: dict = {"scope_fid": family_id}
    doc_params: dict = {"scope_fid": family_id}
    doc_clause_tpl = "{alias}.family_id = :scope_fid"
    if document_id is not None:
        doc_params = {"scope_doc": document_id}
        doc_clause_tpl = "{alias}.id = :scope_doc"

    if compound_ids:
        # Validate the selection against the requested family/document scope
        # before counting: out-of-scope ids are rejected with their number,
        # never silently dropped or exported.
        valid_sql = """
            SELECT DISTINCT m.compound_id
            FROM compound_mentions m
            JOIN patent_documents d ON d.id = m.document_id
            WHERE m.compound_id = ANY(:ids) AND d.family_id = :fid
        """
        vparams: dict = {"ids": list(compound_ids), "fid": family_id}
        if document_id is not None:
            valid_sql += " AND d.id = :doc"
            vparams["doc"] = document_id
        with engine.connect() as conn:
            valid = set(conn.execute(text(valid_sql), vparams).scalars().all())
        unknown = [cid for cid in compound_ids if cid not in valid]
        if unknown:
            where = "family" if document_id is None else "document"
            raise ExportScopeError(
                f"{len(unknown)} selected compound(s) are outside the requested "
                f"{where} scope; the export was not created."
            )
        scope_clause = "d.family_id = :fid AND c.id = ANY(:ids)"
        params["ids"] = list(compound_ids)
        params["fid"] = family_id
        if document_id is not None:
            scope_clause += " AND d.id = :doc"
            params["doc"] = document_id
    elif document_id is not None:
        scope_clause = "d.family_id = :fid AND d.id = :doc"
        params["fid"] = family_id
        params["doc"] = document_id
    else:
        scope_clause = "d.family_id = :fid"
        params["fid"] = family_id

    # Counting phase: reject oversized scopes before any row is loaded.
    with engine.connect() as conn:
        total = int(conn.execute(text(_count_sql(scope_clause)), params).scalar_one())
    if total > MAX_EXPORT_ROWS:
        raise ExportTooLargeError(
            f"Export scope covers {total} compounds; the synchronous limit is "
            f"{MAX_EXPORT_ROWS}. Narrow the scope (background export arrives with larger datasets)."
        )

    with engine.connect() as conn:
        rows = conn.execute(
            text(_base_query(scope_clause, doc_clause_tpl, doc_params)),
            params | doc_params,
        ).mappings().all()

    if not rows and compound_ids:
        raise NotFoundError("No selected compounds found in the current dataset")

    return [
        ExportRow(
            compound_id=r["id"],
            inchikey=r["inchikey"],
            canonical_smiles=r["canonical_smiles"],
            molecular_formula=r["molecular_formula"],
            molecular_weight=r["molecular_weight"],
            hbd=r["hbd"],
            hba=r["hba"],
            tpsa=r["tpsa"],
            logp=r["logp"],
            patent_numbers=sorted(r["docs"]),
            patent_labels=sorted(r["labels"]),
            evidence_ids=[str(e) for e in (r["evidence"] or [])],
            provenance_states=[s for s in (r["states"] or [])],
            evidence_source_urls=[u for u in (r["urls"] or []) if u],
            dataset_version=(
                next(iter(labels)) if len(labels := {v["dataset_version"] for v in r["dataset_versions"]}) == 1
                else "mixed"
            ),
            dataset_versions=r["dataset_versions"],
        )
        for r in rows
    ]


def render_csv(rows: list[ExportRow]) -> str:
    """CSV with one row per compound; mentions and evidence refs are joined with '|'
    so spreadsheet tools keep them in one cell."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "inchikey": row.inchikey,
                "canonical_smiles": row.canonical_smiles,
                "molecular_formula": row.molecular_formula or "",
                "molecular_weight": row.molecular_weight if row.molecular_weight is not None else "",
                "hbd": row.hbd if row.hbd is not None else "",
                "hba": row.hba if row.hba is not None else "",
                "tpsa": row.tpsa if row.tpsa is not None else "",
                "logp": row.logp if row.logp is not None else "",
                "patent_numbers": "|".join(row.patent_numbers),
                "patent_labels": "|".join(row.patent_labels),
                "evidence_records": "|".join(row.evidence_ids),
                "provenance_states": "|".join(row.provenance_states),
                "evidence_source_urls": "|".join(row.evidence_source_urls),
                "dataset_version": row.dataset_version,
                "dataset_versions": json.dumps(row.dataset_versions, sort_keys=True),
            }
        )
    return buf.getvalue()


def render_sdf(rows: list[ExportRow]) -> str:
    """SDF via RDKit; every record carries identity, patent, and evidence properties."""
    from rdkit import Chem

    sio = io.StringIO()
    writer = Chem.SDWriter(sio)
    try:
        for row in rows:
            mol = Chem.MolFromSmiles(row.canonical_smiles)
            if mol is None:
                raise ExportScopeError(
                    f"Stored structure {row.inchikey} cannot be parsed; the SDF export was not created."
                )
            mol.SetProp("_Name", row.inchikey)
            mol.SetProp("inchikey", row.inchikey)
            mol.SetProp("canonical_smiles", row.canonical_smiles)
            if row.molecular_formula:
                mol.SetProp("molecular_formula", row.molecular_formula)
            mol.SetProp("patent_numbers", "|".join(row.patent_numbers))
            if row.patent_labels:
                mol.SetProp("patent_labels", "|".join(row.patent_labels))
            mol.SetProp("evidence_records", "|".join(row.evidence_ids))
            mol.SetProp("provenance_states", "|".join(row.provenance_states))
            if row.evidence_source_urls:
                mol.SetProp("evidence_source_urls", "|".join(row.evidence_source_urls))
            mol.SetProp("dataset_version", row.dataset_version)
            mol.SetProp("dataset_versions", json.dumps(row.dataset_versions, sort_keys=True))
            writer.write(mol)
    finally:
        writer.close()
    return sio.getvalue()
