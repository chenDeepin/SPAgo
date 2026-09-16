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
    # ONLINE-00: target-candidate exports carry their biological scope and
    # conservative evidence class instead of patent labels.
    "target_key",
    "target_name",
    "modality",
    "evidence_class",
    # ONLINE-06: what the reported values imply under a stated potency policy,
    # plus the publication numbers the source declared for the compound. Those
    # stay a separate column from `patent_numbers`, which means "occurrence in
    # the loaded corpus": merging them would blur source-declared with
    # corpus-verified (AGENTS.md §10).
    "activity_class",
    "potency_label",
    "source_declared_patents",
    "reference_qualifies",
    "reference_reason",
    "reference_threshold_nM",
    "reference_policy_version",
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
    target_key: str | None = None
    target_name: str | None = None
    modality: str | None = None
    evidence_class: str | None = None
    #: ONLINE-06. The class is a statement about the exported compound under the
    #: policy recorded in `reference_*`; the policy version and threshold travel
    #: with the file so the columns can be read back years later.
    activity_class: str | None = None
    potency_label: str | None = None
    source_declared_patents: list[str] = field(default_factory=list)
    reference_qualifies: bool | None = None
    reference_reason: str | None = None
    reference_threshold_nm: float | None = None
    reference_policy_version: str | None = None


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
        JOIN current_compound_mentions m ON m.compound_id = c.id
        JOIN patent_documents d ON d.id = m.document_id
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d2.publication_number) AS docs
            FROM current_compound_mentions m2
            JOIN patent_documents d2 ON d2.id = m2.document_id
            WHERE m2.compound_id = c.id AND {doc2}
        ) doc_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(DISTINCT d3.publication_number || ':' || COALESCE(m3.patent_label, ''))
            AS labels
            FROM current_compound_mentions m3
            JOIN patent_documents d3 ON d3.id = m3.document_id
            WHERE m3.compound_id = c.id AND {doc3}
        ) mention_agg ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(v ORDER BY v.dataset_version, v.source_name) AS versions
            FROM (
                SELECT DISTINCT m3.source_name, m3.dataset_version
                FROM current_compound_mentions m3
                JOIN patent_documents d3 ON d3.id = m3.document_id
                WHERE m3.compound_id = c.id AND {doc3}
            ) v
        ) version_agg ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(e.id ORDER BY e.id) AS evidence,
                   array_agg(e.provenance_state ORDER BY e.id) AS states,
                   array_agg(e.source_url ORDER BY e.id) AS urls
            FROM current_evidence_records e
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
        JOIN current_compound_mentions m ON m.compound_id = c.id
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
            FROM current_compound_mentions m
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


CANDIDATE_EVIDENCE_ORDER = (
    "measured_direct_binding",
    "interaction_disruption",
    "functional_effect",
    "screening_assay",
    "computational_prediction",
    "unspecified",
)


def collect_candidate_export_rows(
    engine: Engine,
    target_id: uuid.UUID,
    *,
    compound_ids: list[uuid.UUID] | None = None,
    include_all_modalities: bool = True,
    policy=None,
) -> list[ExportRow]:
    """Export target candidates, including compounds with no patent mapping.

    Scope is the target's candidate set; an explicit selection must be a subset
    of it. Patent numbers/labels are populated only for candidates that also
    occur in the loaded patent corpus, so a patent-free candidate exports as
    patent-free rather than as an empty string that could be misread. Publication
    numbers the *source* declared are a separate column (ONLINE-06).

    `policy` adds the potency class per compound and the target's verdict, both
    computed by :mod:`spago_core.services.reference` with the same rule the API
    reports, so a file and the screen never disagree.
    """
    if compound_ids == []:
        return []
    with engine.connect() as conn:
        target = conn.execute(
            text("SELECT id, target_key, name FROM targets WHERE id = :tid"), {"tid": target_id}
        ).mappings().first()
        if target is None:
            raise NotFoundError(f"Target {target_id} not found")

        scope_clause = "tc.target_id = :tid AND tc.retracted_at IS NULL"
        params: dict = {"tid": target_id}
        if compound_ids:
            params["ids"] = list(compound_ids)
            valid = set(
                conn.execute(
                    text(
                        "SELECT DISTINCT compound_id FROM target_candidates "
                        "WHERE target_id = :tid AND compound_id = ANY(:ids)"
                    ),
                    {"tid": target_id, "ids": list(compound_ids)},
                ).scalars().all()
            )
            unknown = [cid for cid in compound_ids if cid not in valid]
            if unknown:
                raise ExportScopeError(
                    f"{len(unknown)} selected compound(s) are not candidates of this target; "
                    "the export was not created."
                )
            scope_clause += " AND tc.compound_id = ANY(:ids)"
        elif not include_all_modalities:
            scope_clause += " AND (c.modality IS NULL OR c.modality IN ('small_molecule','unclassified'))"

        total = int(
            conn.execute(
                text(
                    f"SELECT count(DISTINCT tc.compound_id) FROM target_candidates tc "
                    f"JOIN compounds c ON c.id = tc.compound_id WHERE {scope_clause}"
                ),
                params,
            ).scalar_one()
        )
        if total > MAX_EXPORT_ROWS:
            raise ExportTooLargeError(
                f"Export scope covers {total} candidates; the synchronous limit is "
                f"{MAX_EXPORT_ROWS}. Narrow the selection."
            )

        rows = conn.execute(
            text(
                f"""
                SELECT c.id, c.inchikey, c.canonical_smiles, c.molecular_formula,
                       c.molecular_weight, c.hbd, c.hba, c.tpsa, c.logp,
                       c.modality,
                       COALESCE(cand.classes, ARRAY[]::text[]) AS classes,
                       COALESCE(prov.states, ARRAY[]::text[]) AS provenance_states,
                       COALESCE(docs.docs, ARRAY[]::text[]) AS docs,
                       COALESCE(ment.labels, ARRAY[]::text[]) AS labels,
                       COALESCE(ver.versions, '[]'::jsonb) AS dataset_versions
                FROM target_candidates tc
                JOIN compounds c ON c.id = tc.compound_id
                LEFT JOIN LATERAL (
                    SELECT array_agg(DISTINCT coalesce(tc2.evidence_class, 'unspecified')) AS classes
                    FROM target_candidates tc2
                    WHERE tc2.target_id = tc.target_id AND tc2.compound_id = c.id
                ) cand ON true
                -- Provenance is read from the compound's stored measurements, never
                -- assumed. The basis matches the class columns: both describe this
                -- compound's stored evidence, so a compound a user added carries
                -- `user_curated` and a file must not present it as a curated database
                -- fact (AGENTS.md §10).
                LEFT JOIN LATERAL (
                    SELECT array_agg(DISTINCT m.provenance_state) AS states
                    FROM investigation_measurements m
                    WHERE m.compound_id = c.id
                      AND m.investigation_target_id = tc.target_id
                ) prov ON true
                LEFT JOIN LATERAL (
                    SELECT array_agg(DISTINCT d.publication_number) AS docs
                    FROM current_compound_mentions m JOIN patent_documents d ON d.id = m.document_id
                    WHERE m.compound_id = c.id
                ) docs ON true
                LEFT JOIN LATERAL (
                    SELECT array_agg(DISTINCT d.publication_number || ':' || COALESCE(m.patent_label, ''))
                    AS labels
                    FROM current_compound_mentions m JOIN patent_documents d ON d.id = m.document_id
                    WHERE m.compound_id = c.id
                ) ment ON true
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(v ORDER BY v.dataset_version, v.source_name) AS versions
                    FROM (
                        SELECT DISTINCT source_name, dataset_version
                        FROM source_retrievals
                        WHERE target_id = tc.target_id AND dataset_version IS NOT NULL
                    ) v
                ) ver ON true
                WHERE {scope_clause}
                GROUP BY c.id, c.modality, cand.classes, prov.states, docs.docs,
                         ment.labels, ver.versions
                ORDER BY c.inchikey
                """
            ),
            params,
        ).mappings().all()

    result: list[ExportRow] = []
    activity: dict = {}
    verdict = None
    if policy is not None and rows:
        from types import SimpleNamespace

        from spago_core.services.reference import (
            compound_activity_summary,
            reference_verdict,
        )

        activity = compound_activity_summary(
            engine, target_id, [r["id"] for r in rows], policy
        )
        verdict = reference_verdict(
            engine,
            SimpleNamespace(id=target_id, target_key=target["target_key"], name=target["name"]),
            policy,
        )
    for r in rows:
        classes = set(r["classes"] or [])
        evidence_class = next(
            (c for c in CANDIDATE_EVIDENCE_ORDER if c in classes), "unspecified"
        )
        versions = list(r["dataset_versions"] or [])
        labels = {v["dataset_version"] for v in versions}
        summary = activity.get(r["id"])
        result.append(
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
                patent_numbers=sorted(r["docs"] or []),
                patent_labels=sorted(r["labels"] or []),
                evidence_ids=[],
                provenance_states=(
                    sorted(r["provenance_states"]) if r["provenance_states"] else ["database_curated"]
                ),
                evidence_source_urls=[],
                dataset_version=(
                    next(iter(labels)) if len(labels) == 1 else ("mixed" if labels else "external:open-databases")
                ),
                dataset_versions=versions,
                target_key=target["target_key"],
                target_name=target["name"],
                modality=r["modality"],
                evidence_class=evidence_class,
                activity_class=(
                    summary.activity_class.value
                    if summary
                    else ("not_applicable" if policy is None else None)
                ),
                potency_label=summary.label if summary else None,
                source_declared_patents=list(summary.patents) if summary else [],
                reference_qualifies=verdict.qualifies if verdict else None,
                reference_reason=verdict.reason if verdict else None,
                reference_threshold_nm=verdict.policy.threshold_nm if verdict else None,
                reference_policy_version=verdict.policy.version if verdict else None,
            )
        )
    return result


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
                "target_key": row.target_key or "",
                "target_name": row.target_name or "",
                "modality": row.modality or "",
                "evidence_class": row.evidence_class or "",
                "activity_class": row.activity_class or "",
                "potency_label": row.potency_label or "",
                "source_declared_patents": "|".join(row.source_declared_patents),
                "reference_qualifies": (
                    "" if row.reference_qualifies is None else str(row.reference_qualifies).lower()
                ),
                "reference_reason": row.reference_reason or "",
                # Same rendering as the SDF property, so one policy reads back the
                # same way in both artifacts.
                "reference_threshold_nM": (
                    f"{row.reference_threshold_nm:g}"
                    if row.reference_threshold_nm is not None
                    else ""
                ),
                "reference_policy_version": row.reference_policy_version or "",
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
            if row.target_key:
                mol.SetProp("target_key", row.target_key)
            if row.target_name:
                mol.SetProp("target_name", row.target_name)
            if row.modality:
                mol.SetProp("modality", row.modality)
            if row.evidence_class:
                mol.SetProp("evidence_class", row.evidence_class)
            if row.activity_class:
                mol.SetProp("activity_class", row.activity_class)
            if row.potency_label:
                mol.SetProp("potency_label", row.potency_label)
            if row.source_declared_patents:
                mol.SetProp("source_declared_patents", "|".join(row.source_declared_patents))
            if row.reference_qualifies is not None:
                mol.SetProp(
                    "reference_qualifies", str(row.reference_qualifies).lower()
                )
            if row.reference_reason:
                mol.SetProp("reference_reason", row.reference_reason)
            if row.reference_threshold_nm is not None:
                mol.SetProp("reference_threshold_nM", f"{row.reference_threshold_nm:g}")
            if row.reference_policy_version:
                mol.SetProp("reference_policy_version", row.reference_policy_version)
            writer.write(mol)
    finally:
        writer.close()
    return sio.getvalue()


# --- B-24: the source-declared set ------------------------------------------------
#
# A different *kind* of row from everything above: those files export compounds
# SPAgo holds, one row per compound aggregated over its corpus mentions. These
# export what a source *declares* for a publication — one row per declared record —
# and the two must never be merged or read as each other (AGENTS.md §11). Both
# renderers therefore carry the source, the versioned match rule, the retrieval
# time, the policy behind `activity_class`, and a `record_kind` column that says
# which of the two relations the file holds.

DECLARED_COMPOUND_CSV_FIELDS = [
    "record_kind",
    "publication_number",
    "match_rule",
    "source_name",
    "source_version",
    "source_dataset_version",
    "retrieved_at",
    "inchikey",
    "canonical_smiles",
    "molecular_formula",
    "molecular_weight",
    "source_molecule_id",
    "source_molecule_name",
    "standard_type",
    "value",
    "unit",
    "relation",
    "activity_class",
    "potency_label",
    "reference_threshold_nM",
    "reference_policy_version",
    "pchembl_value",
    "source_flagged_duplicate",
    "assay_ref",
    "assay_type",
    "assay_description",
    "target_ref",
    "target_name",
    "species",
    "document_ref",
    "document_patent_number",
    "document_doi",
    "document_pmid",
    "source_url",
    "provenance_state",
]

#: What every row in these files is. A reader who finds the file out of context
#: must not have to guess whether `document_patent_number` means "occurs in the
#: corpus" or "the source declared it".
DECLARED_RECORD_KIND = "source_declared_compound"


def render_declared_compounds_csv(view: dict) -> str:
    """One row per declared record, with the rule and the policy in the columns."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=DECLARED_COMPOUND_CSV_FIELDS)
    writer.writeheader()
    for row in view["rows"]:
        writer.writerow(
            {
                "record_kind": DECLARED_RECORD_KIND,
                "publication_number": view["publication_number"],
                "match_rule": view["match_rule"],
                "source_name": view["source_name"],
                "source_version": view["source_version"] or "",
                "source_dataset_version": view["dataset_version"] or "",
                "retrieved_at": view["retrieved_at"] or "",
                "inchikey": row["inchikey"],
                "canonical_smiles": row["canonical_smiles"],
                "molecular_formula": row["molecular_formula"] or "",
                "molecular_weight": (
                    row["molecular_weight"] if row["molecular_weight"] is not None else ""
                ),
                "source_molecule_id": row["source_molecule_id"] or "",
                "source_molecule_name": row["source_molecule_name"] or "",
                "standard_type": row["standard_type"],
                "value": row["value"],
                "unit": row["unit"],
                "relation": row["relation"],
                "activity_class": row["activity_class"],
                "potency_label": row["potency_label"],
                "reference_threshold_nM": (
                    f"{view['reference_threshold_nM']:g}"
                    if view.get("reference_threshold_nM") is not None
                    else ""
                ),
                "reference_policy_version": view.get("reference_policy_version") or "",
                "pchembl_value": row["pchembl_value"] if row["pchembl_value"] is not None else "",
                "source_flagged_duplicate": str(row["potential_duplicate"]).lower(),
                "assay_ref": row["assay_key"] or "",
                "assay_type": row["assay_type"] or "",
                "assay_description": row["assay_description"] or "",
                "target_ref": row["target_key"] or "",
                "target_name": row["target_name"] or "",
                "species": row["species"] or "",
                "document_ref": row["document_ref"] or "",
                "document_patent_number": row["document_patent_number"] or "",
                "document_doi": row["document_doi"] or "",
                "document_pmid": row["document_pmid"] or "",
                "source_url": row["source_url"] or "",
                "provenance_state": row["provenance_state"],
            }
        )
    return buf.getvalue()


def render_declared_compounds_sdf(view: dict) -> str:
    """SDF of the declared set; every record repeats the rule and the source."""
    from rdkit import Chem

    sio = io.StringIO()
    writer = Chem.SDWriter(sio)
    try:
        for row in view["rows"]:
            mol = Chem.MolFromSmiles(row["canonical_smiles"])
            if mol is None:
                raise ExportScopeError(
                    f"Stored structure {row['inchikey']} cannot be parsed; the SDF "
                    "export was not created."
                )
            mol.SetProp("_Name", row["source_molecule_name"] or row["inchikey"])
            mol.SetProp("record_kind", DECLARED_RECORD_KIND)
            mol.SetProp("inchikey", row["inchikey"])
            mol.SetProp("canonical_smiles", row["canonical_smiles"])
            if row["molecular_formula"]:
                mol.SetProp("molecular_formula", row["molecular_formula"])
            mol.SetProp("publication_number", view["publication_number"])
            mol.SetProp("match_rule", view["match_rule"])
            mol.SetProp("source_name", view["source_name"])
            if view["source_version"]:
                mol.SetProp("source_version", view["source_version"])
            if view["dataset_version"]:
                mol.SetProp("source_dataset_version", view["dataset_version"])
            if view["retrieved_at"]:
                mol.SetProp("retrieved_at", view["retrieved_at"])
            if row["source_molecule_id"]:
                mol.SetProp("source_molecule_id", row["source_molecule_id"])
            if row["source_molecule_name"]:
                mol.SetProp("source_molecule_name", row["source_molecule_name"])
            mol.SetProp("standard_type", row["standard_type"])
            mol.SetProp("value", f"{row['value']:g}")
            mol.SetProp("unit", row["unit"] or "")
            mol.SetProp("relation", row["relation"])
            mol.SetProp("activity_class", row["activity_class"])
            mol.SetProp("potency_label", row["potency_label"])
            if view.get("reference_threshold_nM") is not None:
                mol.SetProp("reference_threshold_nM", f"{view['reference_threshold_nM']:g}")
            if view.get("reference_policy_version"):
                mol.SetProp("reference_policy_version", view["reference_policy_version"])
            if row["pchembl_value"] is not None:
                mol.SetProp("pchembl_value", f"{row['pchembl_value']:g}")
            mol.SetProp("source_flagged_duplicate", str(row["potential_duplicate"]).lower())
            if row["assay_key"]:
                mol.SetProp("assay_ref", row["assay_key"])
            if row["assay_type"]:
                mol.SetProp("assay_type", row["assay_type"])
            if row["target_key"]:
                mol.SetProp("target_ref", row["target_key"])
            if row["target_name"]:
                mol.SetProp("target_name", row["target_name"])
            if row["document_ref"]:
                mol.SetProp("document_ref", row["document_ref"])
            if row["document_patent_number"]:
                mol.SetProp("document_patent_number", row["document_patent_number"])
            if row["document_doi"]:
                mol.SetProp("document_doi", row["document_doi"])
            if row["document_pmid"]:
                mol.SetProp("document_pmid", row["document_pmid"])
            if row["source_url"]:
                mol.SetProp("source_url", row["source_url"])
            mol.SetProp("provenance_state", row["provenance_state"])
            writer.write(mol)
    finally:
        writer.close()
    return sio.getvalue()
