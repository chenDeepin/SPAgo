"""Chemistry search services (Milestone 2): exact / substructure / similarity.

Deterministic chemistry only: queries are validated and canonicalized with
RDKit in Python; matching runs against the cartridge-backed `molecule` column
in PostgreSQL (migration 0003). Search is family/document-scoped like every
other interactive query and server-paged.

Stereo policy (design contract 8): stereochemistry is preserved where
specified. Exact matching uses the isomeric InChIKey. Substructure matching
re-checks chirality in RDKit when the query specifies stereo centres (the
cartridge operator matches constitution only).
"""
from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.chemistry import StructureParseError, normalize, parse
from spago_core.services import NotFoundError


class SearchMode(str, enum.Enum):
    EXACT = "exact"
    SUBSTRUCTURE = "substructure"
    SIMILARITY = "similarity"


# Similarity defaults are part of the chemistry service contract; the UI shows
# them and the server enforces bounds.
DEFAULT_SIMILARITY_THRESHOLD = 0.6
MIN_SIMILARITY_THRESHOLD = 0.3
MAX_SIMILARITY_THRESHOLD = 1.0

# Family-scoped stereo re-check is bounded and deterministic; cross-family
# bulk structure search arrives with materialized indices at a later milestone.
MAX_STEREO_RECHECK_ROWS = 5000


@dataclass(frozen=True)
class MoleculeFilters:
    mw_min: float | None = None
    mw_max: float | None = None
    hbd_min: int | None = None
    hbd_max: int | None = None
    hba_min: int | None = None
    hba_max: int | None = None
    logp_min: float | None = None
    logp_max: float | None = None

    def clauses(self, prefix: str) -> tuple[list[str], dict]:
        clauses: list[str] = []
        params: dict = {}

        def bound(col: str, lo, hi) -> None:
            if lo is not None:
                clauses.append(f"c.{col} >= :{prefix}_{col}_lo")
                params[f"{prefix}_{col}_lo"] = lo
            if hi is not None:
                clauses.append(f"c.{col} <= :{prefix}_{col}_hi")
                params[f"{prefix}_{col}_hi"] = hi

        bound("molecular_weight", self.mw_min, self.mw_max)
        bound("hbd", self.hbd_min, self.hbd_max)
        bound("hba", self.hba_min, self.hba_max)
        bound("logp", self.logp_min, self.logp_max)
        return clauses, params


@dataclass(frozen=True)
class StructureSearchResult:
    total: int
    offset: int
    limit: int
    rows: list[dict]  # compound columns for the current page, ordered
    # inchikey -> tanimoto score (similarity mode only)
    scores: dict[str, float]
    query_inchikey: str
    query_canonical_smiles: str
    query_has_stereo: bool
    mode: SearchMode
    threshold: float | None


def validate_query(smiles: str) -> tuple[str, str, bool]:
    """Canonicalize a query structure. Raises StructureParseError with a clear
    reason when the input cannot be used (UI disables execution with this reason)."""
    if not smiles or not smiles.strip():
        raise StructureParseError("Draw or paste a structure first — the query is empty.")
    norm = normalize(smiles)
    return norm.canonical_smiles, norm.inchikey, norm.has_stereo


def _candidate_sql(scope: str, match_clause: str, filter_clauses: list[str]) -> str:
    having = ("AND " + " AND ".join(filter_clauses)) if filter_clauses else ""
    return f"""
        WITH matched AS (
            SELECT DISTINCT c.id
            FROM compounds c
            JOIN compound_mentions m ON m.compound_id = c.id
            JOIN patent_documents d ON d.id = m.document_id
            WHERE d.family_id = :fid {scope} AND {match_clause}
        )
        SELECT c.*, {{score}} AS score
        FROM matched
        JOIN compounds c ON c.id = matched.id
        WHERE 1=1 {having}
    """


def search_family_structures(
    engine: Engine,
    family_id: uuid.UUID,
    query_smiles: str,
    mode: SearchMode,
    document_id: uuid.UUID | None = None,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    filters: MoleculeFilters | None = None,
    offset: int = 0,
    limit: int = 100,
    max_results: int | None = None,
) -> StructureSearchResult:
    """Return a bounded page; when max_results is exceeded, return only total.

    Stereo substructure needs a deterministic candidate re-check; its separate
    candidate cap is enforced before those rows are fetched.
    """
    from spago_core.services import get_family_overview

    get_family_overview(engine, family_id)  # raises NotFoundError

    query_canonical, query_inchikey, query_has_stereo = validate_query(query_smiles)

    scope = "AND m.document_id = :doc" if document_id else ""
    params: dict = {"fid": family_id}
    if document_id:
        params["doc"] = document_id

    filter_clauses, filter_params = (filters or MoleculeFilters()).clauses("f")
    params |= filter_params

    if mode == SearchMode.EXACT:
        # Isomeric InChIKey equality: stereo-specified queries match only the
        # same stereoisomer.
        params["qkey"] = query_inchikey
        sql = _candidate_sql(scope, "c.inchikey = :qkey", filter_clauses).format(score="1.0")
        with engine.connect() as conn:
            total = conn.execute(
                text(f"SELECT count(*) FROM ({sql}) s"), params
            ).scalar_one()
            rows = [] if max_results is not None and total > max_results else conn.execute(
                text(sql + " ORDER BY c.inchikey OFFSET :offset LIMIT :limit"),
                params | {"offset": offset, "limit": limit},
            ).mappings().all()
        return StructureSearchResult(
            total=int(total), offset=offset, limit=limit,
            rows=[dict(r) for r in rows], scores={},
            query_inchikey=query_inchikey, query_canonical_smiles=query_canonical,
            query_has_stereo=query_has_stereo, mode=mode, threshold=None,
        )

    if mode == SearchMode.SUBSTRUCTURE:
        params["qsmiles"] = query_canonical
        sql = _candidate_sql(scope, "c.m @> mol_from_smiles(:qsmiles)", filter_clauses).format(
            score="NULL::double precision"
        )
        with engine.begin() as conn:
            total = int(conn.execute(text(f"SELECT count(*) FROM ({sql}) s"), params).scalar_one())
            if query_has_stereo:
                if total > MAX_STEREO_RECHECK_ROWS:
                    raise ValueError("Candidate set too large for stereo re-check; narrow the scope.")
                rows = conn.execute(text(sql + " ORDER BY c.inchikey"), params).mappings().all()
            elif max_results is not None and total > max_results:
                rows = []
            else:
                rows = conn.execute(
                    text(sql + " ORDER BY c.inchikey OFFSET :offset LIMIT :limit"),
                    params | {"offset": offset, "limit": limit},
                ).mappings().all()
        results = [dict(r) for r in rows]

        # Preserve specified stereo: cartridge @> is chirality-insensitive, so
        # re-check with chirality-aware RDKit matching when the query carries
        # stereo centres. Bounded by the family scope.
        if query_has_stereo:
            from rdkit import Chem

            query_mol = parse(query_canonical)
            kept = []
            for r in results:
                mol = Chem.MolFromSmiles(r["canonical_smiles"])
                if mol is not None and mol.HasSubstructMatch(query_mol, useChirality=True):
                    kept.append(r)
            total = len(kept)
            results = ([] if max_results is not None and total > max_results
                       else kept[offset : offset + limit])

        return StructureSearchResult(
            total=total, offset=offset, limit=limit,
            rows=results, scores={},
            query_inchikey=query_inchikey, query_canonical_smiles=query_canonical,
            query_has_stereo=query_has_stereo, mode=mode, threshold=None,
        )

    # similarity
    threshold = min(max(threshold, MIN_SIMILARITY_THRESHOLD), MAX_SIMILARITY_THRESHOLD)
    params["qsmiles"] = query_canonical
    params["threshold"] = threshold
    # This cartridge's `%` operator applies a fixed 0.5 threshold and ignores
    # rdkit.gin_threshold, which would silently drop results for lower
    # thresholds. Compare tanimoto scores explicitly instead; the GIN
    # fingerprint index becomes relevant again with bulk-scale materialization.
    score_expr = "tanimoto_sml(morganbv_fp(c.m), morganbv_fp(mol_from_smiles(:qsmiles)))"
    match_clause = f"{score_expr} >= :threshold"
    sql = _candidate_sql(scope, match_clause, filter_clauses).format(score=score_expr)
    page_sql = sql + " ORDER BY score DESC, c.inchikey OFFSET :offset LIMIT :limit"

    with engine.begin() as conn:
        total = conn.execute(text(f"SELECT count(*) FROM ({sql}) s"), params).scalar_one()
        rows = [] if max_results is not None and total > max_results else conn.execute(
            text(page_sql), params | {"offset": offset, "limit": limit}
        ).mappings().all()

    return StructureSearchResult(
        total=int(total), offset=offset, limit=limit,
        rows=[dict(r) for r in rows],
        scores={r["inchikey"]: float(r["score"]) for r in rows},
        query_inchikey=query_inchikey, query_canonical_smiles=query_canonical,
        query_has_stereo=query_has_stereo, mode=mode, threshold=threshold,
    )
