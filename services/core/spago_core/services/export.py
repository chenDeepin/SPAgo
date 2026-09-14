"""CSV / SDF export with provenance preserved (design doc contract 7).

Exports cover the requested server-side scope (family/document or an explicit
selection) — never silently just the loaded page. Patent identifiers, structure
identity, and evidence references stay in the output.
"""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.services import NotFoundError

# Synchronous export cap. Beyond this a persisted background job is required
# (AGENTS.md §22); at M0/M1 fixture scale synchronous is honest and simple.
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
    "dataset_version",
]


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
    dataset_version: str


def _base_query(scope_clause: str) -> str:
    return f"""
        SELECT c.id, c.inchikey, c.canonical_smiles, c.molecular_formula,
               c.molecular_weight, c.hbd, c.hba, c.tpsa, c.logp, c.dataset_version,
               COALESCE(doc_agg.docs, '{{}}') AS docs,
               COALESCE(mention_agg.labels, '{{}}') AS labels,
               COALESCE(ev_agg.evidence, '{{}}') AS evidence,
               COALESCE(ev_agg.states, '{{}}') AS states
        FROM compounds c
        JOIN compound_mentions m ON m.compound_id = c.id
        JOIN patent_documents d ON d.id = m.document_id
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d2.publication_number) AS docs
            FROM compound_mentions m2
            JOIN patent_documents d2 ON d2.id = m2.document_id
            WHERE m2.compound_id = c.id
        ) doc_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d3.publication_number || ':' || COALESCE(m3.patent_label, ''))
            AS labels
            FROM compound_mentions m3
            JOIN patent_documents d3 ON d3.id = m3.document_id
            WHERE m3.compound_id = c.id
        ) mention_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(e.id ORDER BY e.id) AS evidence,
                   array_agg(e.provenance_state ORDER BY e.id) AS states
            FROM evidence_records e
            WHERE e.compound_id = c.id
        ) ev_agg ON true
        WHERE {scope_clause}
        GROUP BY c.id, doc_agg.docs, mention_agg.labels, ev_agg.evidence, ev_agg.states
        ORDER BY c.inchikey
    """


def collect_export_rows(
    engine: Engine,
    family_id: uuid.UUID | None = None,
    document_id: uuid.UUID | None = None,
    compound_ids: list[uuid.UUID] | None = None,
) -> list[ExportRow]:
    """Server-side export scope. Selection wins; otherwise family/document scope."""
    params: dict = {}
    if compound_ids:
        clause = "c.id = ANY(:ids)"
        params["ids"] = compound_ids
    elif document_id is not None:
        clause = "d.family_id = :fid AND d.id = :did"
        params["fid"] = family_id
        params["did"] = document_id
    elif family_id is not None:
        clause = "d.family_id = :fid"
        params["fid"] = family_id
    else:
        raise ValueError("export requires a scope")

    with engine.connect() as conn:
        rows = conn.execute(text(_base_query(clause)), params).mappings().all()

    if len(rows) > MAX_EXPORT_ROWS:
        raise ValueError(
            f"Export scope covers {len(rows)} compounds; the synchronous limit is "
            f"{MAX_EXPORT_ROWS}. Narrow the scope (background export arrives with larger datasets)."
        )
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
            dataset_version=r["dataset_version"],
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
                "dataset_version": row.dataset_version,
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
                # Stored compounds are canonicalized at seed time; skip defensively
                # rather than emit an unparseable record.
                continue
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
            mol.SetProp("dataset_version", row.dataset_version)
            writer.write(mol)
    finally:
        writer.close()
    return sio.getvalue()
