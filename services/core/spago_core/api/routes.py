"""HTTP API for SPAgo M0.

Serving rules: server-side paging (default 100, cap 500), lazy cached depictions,
explicit missing-source and not-found states. UI never sees adapter schemas.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from spago_core import services
from spago_core.api.auth_routes import current_user
from spago_core.services import auth as auth_svc
from spago_core.services import bioactivity as services_bioactivity
from spago_core.adapters import SureChemblFixtureAdapter
from spago_core.chemistry import StructureParseError, depict_svg
from spago_core.config import Settings, get_settings
from spago_core.domain import (
    MAX_COVERAGE_PUBLICATIONS,
    MAX_SUPPLEMENT_ROWS,
    PatentDocument,
    PatentFamily,
    SupplementBundle,
)
from spago_core.queries import compound_counts_by_document
from spago_core.services import AmbiguousError, NotFoundError

router = APIRouter(prefix="/api/v1")

# Import-time constants: function-parameter defaults cannot read settings.
_DEFAULT_PAGE = 100


def get_engine(request: Request):
    return request.app.state.engine


# --- health -------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    database: str
    chemistry: str
    rdkit_cartridge: str
    dataset_version: Optional[str] = None
    ingestion_issues: int = 0
    api_version: str


def health_payload(app) -> HealthResponse:
    from spago_core.chemistry import chemistry_ok
    from spago_core.db import database_available

    db_state = "up" if database_available(app.state.engine) else "down"
    chem_state = "ok" if chemistry_ok() else "failed"
    cartridge = "unknown"
    dataset_version = None
    issues = 0
    if db_state == "up":
        try:
            with app.state.engine.connect() as conn:
                from sqlalchemy import text

                row = conn.execute(
                    text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'rdkit')")
                ).scalar()
                cartridge = "installed" if row else "missing"
            info = services.get_dataset_info(app.state.engine)
            dataset_version = info["dataset_version"] if info else None
            issues = services.count_ingestion_issues(app.state.engine)
        except Exception:
            cartridge = cartridge if cartridge != "unknown" else "error"
    status = "ok" if db_state == "up" and chem_state == "ok" else "degraded"
    return HealthResponse(
        status=status,
        database=db_state,
        chemistry=chem_state,
        rdkit_cartridge=cartridge,
        dataset_version=dataset_version,
        ingestion_issues=issues,
        api_version=app.state.version,
    )


# --- datasets / provenance ------------------------------------------------------


class DatasetInfoResponse(BaseModel):
    source_name: str
    dataset_version: str
    synthetic: bool
    release_label: Optional[str] = None
    files: dict = {}
    notes: Optional[str] = None
    ingestion_issues: list[dict] = []
    # Every loaded dataset (demo + imported packages), newest first (PROD-01:
    # the UI shows the real source inventory, not a hardcoded demo label).
    datasets: list[dict] = []


@router.get("/datasets/info", response_model=DatasetInfoResponse)
def datasets_info(engine=Depends(get_engine)):
    info = services.get_dataset_info(engine)
    if info is None:
        raise HTTPException(status_code=404, detail="No dataset loaded; run the seed step first.")
    return DatasetInfoResponse(
        source_name=info["source_name"],
        dataset_version=info["dataset_version"],
        synthetic=bool(info["synthetic"]),
        release_label=info["release_label"],
        files=info["files"] or {},
        notes=info["notes"],
        ingestion_issues=services.list_ingestion_issues(engine),
        datasets=services.list_dataset_infos(engine),
    )


class CorpusSourceRow(BaseModel):
    """One dataset version as it exists in the corpus tables right now."""

    dataset_version: str
    source_name: Optional[str] = None
    synthetic: bool = False
    registered: bool = False
    release_label: Optional[str] = None
    retrieved_at: Optional[str] = None
    notes: Optional[str] = None
    files: int = 0
    families: int = 0
    documents: int = 0
    compounds: int = 0
    mentions: int = 0
    evidence: int = 0
    measurements: int = 0
    issues: int = 0


class CorpusImports(BaseModel):
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    interrupted: int = 0
    last_finished_at: Optional[str] = None
    last_error: Optional[dict] = None


class CorpusResponse(BaseModel):
    generated_at: str
    sources: list[CorpusSourceRow]
    totals: dict
    imports: CorpusImports
    notes: list[str] = []


@router.get("/corpus", response_model=CorpusResponse)
def corpus(engine=Depends(get_engine)):
    """What the loaded corpus actually covers, per dataset version (B-01).

    Read-only and exact: every number is a count over the corpus tables, so a
    publication that was never imported stays an explicit not-found rather than
    looking like "this patent has no chemistry".
    """
    summary = services.corpus_summary(engine)
    return CorpusResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        sources=[CorpusSourceRow(**row) for row in summary["sources"]],
        totals=summary["totals"],
        imports=CorpusImports(**summary["imports"]),
        notes=summary["notes"],
    )


# --- patents / families ----------------------------------------------------------


class FamilyOverviewResponse(BaseModel):
    family: PatentFamily
    documents: list[PatentDocument]
    mention_counts: dict[str, int]


class PatentMatch(BaseModel):
    """How the requested number reached the stored row (B-03).

    ``matched`` is the stored ``publication_number`` verbatim — the corpus value is
    never rewritten to look like the request, or the other way round.
    """

    requested: str
    matched: str
    exact: bool
    rule: str


class PatentResponse(BaseModel):
    document: PatentDocument
    family: PatentFamily
    documents: list[PatentDocument]
    mention_counts: dict[str, int]
    match: PatentMatch


@router.get("/patents/{publication_number}", response_model=PatentResponse)
def get_patent(publication_number: str, engine=Depends(get_engine)):
    try:
        lookup = services.find_patent(engine, publication_number)
    except AmbiguousError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    document, overview = lookup.document, lookup.overview
    return PatentResponse(
        document=document,
        family=overview.family,
        documents=overview.documents,
        mention_counts=overview.mention_counts,
        match=PatentMatch(
            requested=lookup.requested,
            matched=lookup.matched,
            exact=lookup.exact,
            rule=lookup.rule,
        ),
    )


@router.get("/families/{family_id}", response_model=FamilyOverviewResponse)
def get_family(family_id: uuid.UUID, engine=Depends(get_engine)):
    try:
        overview = services.get_family_overview(engine, family_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FamilyOverviewResponse(
        family=overview.family,
        documents=overview.documents,
        mention_counts=overview.mention_counts,
    )


# --- patent-led source compounds (B-24) --------------------------------------------


class PatentSourceDocument(BaseModel):
    document_chembl_id: Optional[str] = None
    patent_id: Optional[str] = None
    doi: Optional[str] = None
    pubmed_id: Optional[str] = None
    year: Optional[int] = None


class PatentSourceNearMatch(BaseModel):
    document_chembl_id: Optional[str] = None
    patent_id: Optional[str] = None
    year: Optional[int] = None
    reason: str


class PatentSourceRow(BaseModel):
    """One declared record. `activity_class` is computed on read under the policy
    named in the response; nothing here is an occurrence in SPAgo's corpus."""

    row_id: uuid.UUID
    compound_id: uuid.UUID
    inchikey: str
    canonical_smiles: str
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    modality: Optional[str] = None
    source_record_id: str
    source_molecule_id: Optional[str] = None
    source_molecule_name: Optional[str] = None
    standard_type: str
    value: float
    unit: str
    relation: str
    raw_value: Optional[str] = None
    pchembl_value: Optional[float] = None
    potential_duplicate: bool = False
    validity_comment: Optional[str] = None
    activity_class: str
    activity_class_rule: str
    potency_label: str
    assay_key: Optional[str] = None
    assay_type: Optional[str] = None
    assay_description: Optional[str] = None
    target_key: Optional[str] = None
    target_name: Optional[str] = None
    species: Optional[str] = None
    variant_accession: Optional[str] = None
    variant_mutation: Optional[str] = None
    document_ref: Optional[str] = None
    document_patent_number: Optional[str] = None
    document_doi: Optional[str] = None
    document_pmid: Optional[str] = None
    source_url: Optional[str] = None
    provenance_state: str
    dataset_version: str
    retrieved_at: str


class PatentSourceResponse(BaseModel):
    publication_number: str
    requested_number: str
    source_name: str
    source_version: Optional[str] = None
    dataset_version: Optional[str] = None
    #: complete | partial | empty | failed | not_queried. `not_queried` means
    #: nothing was asked, which is not "the source knows nothing".
    status: str
    match_rule: str
    match_rule_text: Optional[str] = None
    retrieved_at: Optional[str] = None
    rows_retrieved_at: Optional[str] = None
    documents: list[PatentSourceDocument]
    near_matches: list[PatentSourceNearMatch]
    warnings: list[str]
    rejection_counts: dict[str, int]
    bounds: dict[str, int]
    records_seen: int
    records_excluded: int
    row_count: int
    compound_count: int
    activity_class_counts: dict[str, int]
    activity_classes_with_a_class: int
    reference_threshold_nM: float
    reference_threshold_label: str
    reference_policy_version: str
    not_queried_reason: Optional[str] = None
    offset: int
    limit: int
    rows: list[PatentSourceRow]


def _patent_source_response(view: dict) -> PatentSourceResponse:
    return PatentSourceResponse(
        **{
            **view,
            "documents": [PatentSourceDocument(**d) for d in view["documents"]],
            "near_matches": [PatentSourceNearMatch(**n) for n in view["near_matches"]],
            "rows": [PatentSourceRow(**row) for row in view["rows"]],
        }
    )


def _patent_source_service():
    """The patent-led lookup service, injectable so a test can drive a stub source.

    FastAPI dependency (not a module-level singleton): the adapter holds a
    rate-limited, TTL-cached HTTP client, and a request-scoped instance is what
    the target-led path uses too.
    """
    from spago_core.services.patent_sources import PatentSourceService

    return PatentSourceService()


@router.post(
    "/patents/{publication_number}/source-compounds",
    response_model=PatentSourceResponse,
)
def lookup_patent_source_compounds(
    publication_number: str,
    engine=Depends(get_engine),
    service=Depends(_patent_source_service),
):
    """Ask the source what it declares for this publication (B-24).

    An explicit, bounded, human-initiated action — the patent-led counterpart of
    `POST /targets/discover`. The publication does not have to be in the corpus:
    that is the case this exists for. The declared set is stored separately from
    the corpus and is never merged into it (AGENTS.md §11).
    """
    from spago_core.services import patent_sources as patent_sources_svc

    try:
        view = service.lookup(engine, publication_number)
    except patent_sources_svc.PatentSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _patent_source_response(view)


@router.get(
    "/patents/{publication_number}/source-compounds",
    response_model=PatentSourceResponse,
)
def get_patent_source_compounds(
    publication_number: str,
    offset: int = 0,
    limit: int = 100,
    engine=Depends(get_engine),
    service=Depends(_patent_source_service),
):
    """The stored declared set, or `not_queried` when nothing was asked yet."""
    view = service.read(engine, publication_number, offset=offset, limit=limit)
    return _patent_source_response(view)


@router.get("/patents/{publication_number}/source-compounds/export")
def export_patent_source_compounds(
    publication_number: str,
    format: str = "csv",
    engine=Depends(get_engine),
    service=Depends(_patent_source_service),
):
    """The whole declared set, with the source, the rule and the policy in the file."""
    from spago_core.services import patent_sources as patent_sources_svc
    from spago_core.services.export import ExportScopeError

    try:
        filename, text = service.export(engine, publication_number, fmt=format)
    except (ExportScopeError, patent_sources_svc.PatentSourceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    media_type = "text/csv; charset=utf-8" if format == "csv" else "chemical/x-mdl-sdfile"
    return Response(
        content=text.encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Lets a caller confirm which set the file holds without parsing it.
            "X-Spago-Source-Set": "source_declared",
        },
    )


# --- coverage (B-26) ---------------------------------------------------------------


class CoverageRequest(BaseModel):
    """The publications to audit. Bounded by the rule's own limit, not by a page."""

    publications: list[str] = Field(default_factory=list)


class CoverageAnswerResponse(BaseModel):
    kind: str
    source_name: Optional[str] = None
    state: str
    status: str
    records: int
    compounds: int
    unconfirmed_records: int
    match_rule: Optional[str] = None
    source_version: Optional[str] = None
    dataset_version: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    rows_retrieved_at: Optional[datetime] = None
    detail: str


class CoverageLegResponse(BaseModel):
    leg: str
    state: str
    records: int
    compounds: int
    unconfirmed_records: int
    targets: int
    detail: str
    answers: list[CoverageAnswerResponse]


class PublicationCoverageResponse(BaseModel):
    requested: str
    matched: Optional[str] = None
    normalized: list[str]
    in_corpus: bool
    family_id: Optional[uuid.UUID] = None
    family_key: Optional[str] = None
    doc_type: Optional[str] = None
    ambiguous: list[str]
    status: str
    status_rule: str
    status_reason: str
    unqueried: list[str]
    legs: list[CoverageLegResponse]


class CoverageReportResponse(BaseModel):
    rule: str
    rule_text: str
    generated_at: datetime
    publications: list[PublicationCoverageResponse]
    totals: dict[str, int]
    notes: list[str]


@router.post("/patents/coverage", response_model=CoverageReportResponse)
def audit_patent_coverage(payload: CoverageRequest, engine=Depends(get_engine)):
    """What SPAgo holds for each publication, from where, and what nobody asked (B-26).

    A read of stored rows only — no source is called, so this needs no user action and
    changes nothing (AGENTS.md §16). Legs are never summed, and a leg nobody asked is
    reported as `not_queried` **with the leg named in `unqueried`**, so an empty row is
    never read as "this publication has no compounds" (AGENTS.md §11).
    """
    from spago_core.services import coverage as coverage_svc

    try:
        report = coverage_svc.audit_publications(engine, payload.publications)
    except coverage_svc.CoverageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return report


@router.post("/patents/coverage/export")
def export_patent_coverage(
    payload: CoverageRequest,
    format: str = "markdown",
    engine=Depends(get_engine),
):
    """The same audit as a file: the rule, every leg's counts and the reason per row.

    `json` is the report itself; `csv` is long form (one row per publication-leg),
    which is what an operator re-derives from; `markdown` is the readable audit.
    """
    from fastapi.responses import JSONResponse

    from spago_core.services import coverage as coverage_svc

    if format not in {"json", "csv", "markdown"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported export format '{format}'. Use json, csv or markdown.",
        )
    try:
        report = coverage_svc.audit_publications(engine, payload.publications)
    except coverage_svc.CoverageError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = coverage_svc.coverage_filename(report, format)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        # Lets a caller confirm which rule produced the file without parsing it.
        "X-Spago-Coverage-Rule": report.rule,
        "X-Spago-Coverage-Publications": str(len(report.publications)),
    }
    if format == "json":
        return JSONResponse(content=report.model_dump(mode="json"), headers=headers)
    text = (
        coverage_svc.render_coverage_csv(report)
        if format == "csv"
        else coverage_svc.render_coverage_markdown(report)
    )
    media_type = (
        "text/csv; charset=utf-8" if format == "csv" else "text/markdown; charset=utf-8"
    )
    return Response(content=text.encode("utf-8"), media_type=media_type, headers=headers)


# --- compounds ---------------------------------------------------------------------


class MentionResponse(BaseModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    document_id: uuid.UUID
    publication_number: Optional[str] = None
    patent_label: Optional[str] = None


class CompoundResponse(BaseModel):
    id: uuid.UUID
    canonical_smiles: str
    inchikey: str
    inchi: Optional[str] = None
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    hbd: Optional[int] = None
    hba: Optional[int] = None
    tpsa: Optional[float] = None
    logp: Optional[float] = None
    has_stereo: bool = False
    is_multi_component: bool = False
    scaffold: Optional[str] = None
    normalization_notes: Optional[str] = None


class ActivitySummaryResponse(BaseModel):
    target_name: Optional[str] = None
    assay_key: str
    assay_type: Optional[str] = None
    standard_type: str
    value: float
    unit: str
    relation: str
    provenance_state: str
    dataset_version: str


class CompoundRowResponse(BaseModel):
    compound: CompoundResponse
    mentions: list[MentionResponse]
    activity: list[ActivitySummaryResponse] = []


class CompoundPageResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CompoundRowResponse]


@router.get("/families/{family_id}/compounds", response_model=CompoundPageResponse)
def list_family_compounds(
    family_id: uuid.UUID,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    document_id: Optional[uuid.UUID] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(_DEFAULT_PAGE, ge=1),
):
    offset, limit = services.clamp_page(offset, limit, settings.default_page_size, settings.max_page_size)
    try:
        services.get_family_overview(engine, family_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    page = services.list_family_compounds(engine, family_id, document_id, offset, limit)
    activity_map = services_bioactivity.family_activity(engine, family_id, document_id)
    return CompoundPageResponse(
        total=page.total,
        offset=page.offset,
        limit=page.limit,
        items=[
            CompoundRowResponse(
                compound=CompoundResponse(**r.compound.model_dump()),
                mentions=[MentionResponse(**m.model_dump()) for m in r.mentions],
                activity=[
                    ActivitySummaryResponse(
                        target_name=a.target_name,
                        assay_key=a.assay_key,
                        assay_type=a.assay_type,
                        standard_type=a.standard_type,
                        value=a.value,
                        unit=a.unit,
                        relation=a.relation,
                        provenance_state=a.provenance_state,
                        dataset_version=a.dataset_version,
                    )
                    for a in activity_map.get(str(r.compound.id), [])
                ],
            )
            for r in page.items
        ],
    )


@router.get("/compounds/{compound_id}", response_model=CompoundRowResponse)
def get_compound(compound_id: uuid.UUID, engine=Depends(get_engine)):
    try:
        row = services.get_compound(engine, compound_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CompoundRowResponse(
        compound=CompoundResponse(**row.compound.model_dump()),
        mentions=[MentionResponse(**m.model_dump()) for m in row.mentions],
    )


@router.get("/compounds/{compound_id}/depiction")
def get_depiction(
    compound_id: uuid.UUID,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    w: int = Query(280, ge=80, le=800),
    h: int = Query(160, ge=60, le=600),
):
    try:
        smiles = services.get_compound_smiles(engine, compound_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    cache_dir = settings.depiction_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{compound_id}-{w}x{h}.svg"
    if not cache_path.exists():
        try:
            svg = depict_svg(smiles, width=w, height=h)
        except StructureParseError as exc:
            # Stored structures are canonicalized at seed time; this indicates real trouble.
            raise HTTPException(status_code=500, detail="Depiction failed; see server logs") from exc
        cache_path.write_text(svg)

    return FileResponse(
        cache_path,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


class EvidenceResponse(BaseModel):
    id: uuid.UUID
    compound_id: Optional[uuid.UUID] = None
    compound_mention_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    publication_number: Optional[str] = None
    source_type: str
    section: Optional[str] = None
    page: Optional[int] = None
    table_ref: Optional[str] = None
    figure_ref: Optional[str] = None
    paragraph: Optional[str] = None
    compound_local_id: Optional[str] = None
    raw_excerpt: Optional[str] = None
    source_url: Optional[str] = None
    extraction_method: str
    provenance_state: str
    confidence: Optional[float] = None
    dataset_version: str
    retrieved_at: str


@router.get("/compounds/{compound_id}/evidence", response_model=list[EvidenceResponse])
def get_compound_evidence(compound_id: uuid.UUID, engine=Depends(get_engine)):
    records = services.list_compound_evidence(engine, compound_id)
    return [
        EvidenceResponse(
            **r.model_dump(mode="json"),
        )
        for r in records
    ]


# --- structure search (M2) ----------------------------------------------------------


class MoleculeFiltersBody(BaseModel):
    mw_min: Optional[float] = None
    mw_max: Optional[float] = None
    hbd_min: Optional[int] = None
    hbd_max: Optional[int] = None
    hba_min: Optional[int] = None
    hba_max: Optional[int] = None
    logp_min: Optional[float] = None
    logp_max: Optional[float] = None


class StructureSearchRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    mode: str = Field(pattern="^(exact|substructure|similarity)$")
    smiles: str = Field(min_length=1, max_length=2000)
    threshold: Optional[float] = Field(default=None, ge=0.3, le=1.0)
    document_id: Optional[uuid.UUID] = None
    filters: Optional[MoleculeFiltersBody] = None
    offset: int = Query(0, ge=0)
    limit: int = Query(100, ge=1)


class StructureSearchHit(BaseModel):
    compound: CompoundResponse
    mentions: list[MentionResponse]
    score: Optional[float] = None


class StructureSearchResponse(BaseModel):
    mode: str
    total: int
    offset: int
    limit: int
    query_canonical_smiles: str
    query_inchikey: str
    query_has_stereo: bool
    threshold: Optional[float] = None
    items: list[StructureSearchHit]


@router.post("/families/{family_id}/structure-search", response_model=StructureSearchResponse)
def structure_search(
    family_id: uuid.UUID,
    body: StructureSearchRequest,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    from spago_core.services import structure_search as ss

    offset, limit = services.clamp_page(
        body.offset, body.limit, settings.default_page_size, settings.max_page_size
    )
    try:
        result = ss.search_family_structures(
            engine,
            family_id,
            body.smiles,
            ss.SearchMode(body.mode),
            document_id=body.document_id,
            threshold=body.threshold if body.threshold is not None else ss.DEFAULT_SIMILARITY_THRESHOLD,
            filters=ss.MoleculeFilters(**(body.filters.model_dump() if body.filters else {})),
            offset=offset,
            limit=limit,
        )
    except ss.StructureParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Hydrate only this search page, with the same family/document scope.
    mention_map = services.list_compound_mentions(
        engine, [r["id"] for r in result.rows], family_id, body.document_id
    )

    hits = []
    for r in result.rows:
        compound = CompoundResponse(
            id=r["id"],
            canonical_smiles=r["canonical_smiles"],
            inchikey=r["inchikey"],
            inchi=r["inchi"],
            molecular_formula=r["molecular_formula"],
            molecular_weight=r["molecular_weight"],
            hbd=r["hbd"],
            hba=r["hba"],
            tpsa=r["tpsa"],
            logp=r["logp"],
            has_stereo=r["has_stereo"],
            is_multi_component=r["is_multi_component"],
            scaffold=r["scaffold"],
            normalization_notes=r["normalization_notes"],
        )
        mentions = [MentionResponse(**m.model_dump()) for m in mention_map.get(r["id"], [])]
        hits.append(
            StructureSearchHit(
                compound=compound,
                mentions=mentions,
                score=result.scores.get(r["inchikey"]),
            )
        )

    return StructureSearchResponse(
        mode=result.mode.value,
        total=result.total,
        offset=result.offset,
        limit=result.limit,
        query_canonical_smiles=result.query_canonical_smiles,
        query_inchikey=result.query_inchikey,
        query_has_stereo=result.query_has_stereo,
        threshold=result.threshold,
        items=hits,
    )


@router.get("/compounds/{compound_id}/activity", response_model=list[ActivitySummaryResponse])
def get_compound_activity(compound_id: uuid.UUID, engine=Depends(get_engine)):
    views = services_bioactivity.compound_activity(engine, compound_id)
    return [
        ActivitySummaryResponse(
            target_name=v.target_name,
            assay_key=v.assay_key,
            assay_type=v.assay_type,
            standard_type=v.standard_type,
            value=v.value,
            unit=v.unit,
            relation=v.relation,
            provenance_state=v.provenance_state,
            dataset_version=v.dataset_version,
        )
        for v in views
    ]


# --- evidence-grounded AI (M5) ------------------------------------------------------


class FamilySummaryResponse(BaseModel):
    analysis_id: uuid.UUID
    provider: str
    provenance_state: str
    text: str
    citations: list[dict]
    dataset_version: str
    created_at: str
    # Additive LLM-interface fields; offline calls leave them at defaults.
    mode: str = "offline"
    #: family | document | target — the scope this analysis actually covers.
    scope: str = "family"
    model: Optional[str] = None
    cached: bool = False
    usage: Optional[dict] = None
    coverage: list[dict] = []


class PlanQueryRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    query: str = Field(min_length=1, max_length=2000)
    #: Context the planner may use, all of it already authorized: the open family
    #: or document and any explicit selection. Never a whole project dataset.
    family_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    selected_compound_id: Optional[uuid.UUID] = None
    #: Explicit opt-in to the configured model. Offline planning happens first
    #: and never requires this.
    use_llm: bool = False


class PlanStepResponse(BaseModel):
    op: str
    description: str
    parameters: dict = {}
    expensive: bool = False


class SearchPlanResponse(BaseModel):
    plan_version: str
    query: str
    producer: str
    steps: list[PlanStepResponse] = []
    unresolved: list[str] = []
    clarification_required: bool = False
    note: str = ""
    model: Optional[str] = None
    mode: str = "offline"


class PlanExecuteRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    plan: dict


class PlanStepResultResponse(BaseModel):
    op: str
    status: str
    detail: str = ""
    data: dict = {}


class PlanExecuteResponse(BaseModel):
    query: str
    producer: str
    steps: list[PlanStepResultResponse] = []
    unresolved: list[str] = []


def _plan_payload(plan, mode: str) -> SearchPlanResponse:
    from spago_core.services.planner import OPERATION_SPECS, Operation

    steps = []
    for raw in plan.steps:
        op = Operation(raw["op"])
        parameters = {k: v for k, v in raw.items() if k not in ("op", "limit")}
        if "limit" in raw:
            parameters["limit"] = raw["limit"]
        steps.append(
            PlanStepResponse(
                op=op.value,
                description=OPERATION_SPECS[op]["description"],
                parameters=parameters,
                expensive=bool(OPERATION_SPECS[op]["expensive"]),
            )
        )
    return SearchPlanResponse(
        plan_version=plan.plan_version,
        query=plan.query,
        producer=plan.producer,
        steps=steps,
        unresolved=list(plan.unresolved),
        clarification_required=plan.clarification_required,
        note=plan.note,
        model=plan.model,
        mode=mode,
    )


def _run_summary(
    request: Request,
    engine,
    settings,
    scope: str,
    scope_id: uuid.UUID,
    mode: str,
    response_scope_label: str,
    include_all_modalities: bool = False,
    owner_id: uuid.UUID | None = None,
):
    """Shared summary execution + error mapping for every scope.

    One implementation means the status codes, timeout/auth/rate-limit mapping
    and provenance labelling cannot drift between scopes (ONLINE-01).
    """
    from spago_core.adapters.llm import LLMConfigProblem, OpenAICompatibleSummaryProvider, parse_endpoint
    from spago_core.services import ai as ai_svc

    llm_provider = None
    if mode == "llm":
        try:
            endpoint = parse_endpoint(settings)
        except LLMConfigProblem as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        llm_provider = OpenAICompatibleSummaryProvider(
            endpoint,
            client=getattr(request.app.state, "llm_client", None),
            scope=scope,
            prompt_version=ai_svc.PROMPT_VERSION_BY_SCOPE.get(scope, ai_svc.PROMPT_VERSION),
        )

    # Dispatch through the scope's named service entry point, resolved at call
    # time so tests and deployments can substitute it.
    entry_name = ai_svc.SUMMARY_ENTRY_POINTS.get(scope)
    if entry_name is None:
        raise HTTPException(status_code=422, detail=f"Unsupported summary scope {scope!r}.")
    entry = getattr(ai_svc, entry_name)
    kwargs = {"owner_id": owner_id}
    if scope == "target":
        kwargs["include_all_modalities"] = include_all_modalities

    try:
        result = entry(engine, scope_id, mode=mode, llm_provider=llm_provider, **kwargs)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ai_svc.ContentInFlightError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.ProviderBusyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMConfigError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMUpstreamRateLimitError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    except ai_svc.LLMAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMTimeoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.SnapshotBudgetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    result["mode"] = mode
    result["scope"] = response_scope_label
    return result


def _ai_status_response(settings) -> dict:
    from spago_core.adapters.llm import LLMConfigProblem, parse_endpoint

    has_base = bool((settings.llm_base_url or "").strip())
    has_model = bool((settings.llm_model or "").strip())
    if not has_base and not has_model:
        return {
            "state": "offline",
            "model": None,
            "target": None,
            "reason": "No LLM endpoint configured; summaries use the offline extractive provider.",
        }
    try:
        endpoint = parse_endpoint(settings)
    except LLMConfigProblem as exc:
        return {
            "state": "config_invalid",
            "model": settings.llm_model or None,
            "target": None,
            "reason": str(exc),
        }
    parts = urlsplit(endpoint.base_url)
    target = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return {
        "state": "configured",
        "model": endpoint.model,
        "target": target,  # sanitized: scheme + host + path, never the key
        "reason": "Configured endpoints are verified on first use, not by this status call.",
    }


@router.get("/ai/status")
def ai_status(settings: Settings = Depends(get_settings)):
    from spago_core.adapters.llm import LLMConfigProblem

    return _ai_status_response(settings)


class SummaryRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    mode: str = Field(default="offline", pattern="^(offline|llm)$")


@router.post("/families/{family_id}/summary", response_model=FamilySummaryResponse)
def family_summary(
    family_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    body: SummaryRequest | None = None,
    user: auth_svc.AuthUser = Depends(current_user),
):
    owner_id = auth_svc.owner_id_for(user)
    """Family summary. Without a body (legacy callers) this stays offline; an
    explicit {"mode": "llm"} is required before any paid model call is made.

    Error mapping: 502 upstream/validation, 504 timeout, 503 not configured,
    409 identical content in flight, 429 busy or upstream rate limited
    (Retry-After forwarded only when the endpoint provided a usable value),
    500 unrepresentable bounded input."""
    return _run_summary(
        request,
        engine,
        settings,
        "family",
        family_id,
        body.mode if body else "offline",
        "family",
        owner_id=owner_id,
    )


class DocumentSummaryRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    mode: str = Field(default="offline", pattern="^(offline|llm)$")


@router.post("/documents/{document_id}/summary", response_model=FamilySummaryResponse)
def document_summary(
    document_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    body: DocumentSummaryRequest | None = None,
    user: auth_svc.AuthUser = Depends(current_user),
):
    owner_id = auth_svc.owner_id_for(user)
    """Summary of exactly one patent document.

    Distinct from the family summary and labelled as such: the fact set, the
    prompt and the cache key all cover this document alone, so it can never be
    presented as an analysis of the whole family."""
    return _run_summary(
        request,
        engine,
        settings,
        "document",
        document_id,
        body.mode if body else "offline",
        "document",
        owner_id=owner_id,
    )


class TargetSummaryRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    mode: str = Field(default="offline", pattern="^(offline|llm)$")
    include_all_modalities: bool = False


@router.post("/targets/{target_id}/summary", response_model=FamilySummaryResponse)
def target_summary(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    body: TargetSummaryRequest | None = None,
    user: auth_svc.AuthUser = Depends(current_user),
):
    owner_id = auth_svc.owner_id_for(user)
    """Summary of a target investigation, with its per-source coverage.

    The coverage travels into the fact set, so the summary states what was
    retrieved, what failed and what was not queried instead of implying that a
    thin result means no inhibitors exist."""
    return _run_summary(
        request,
        engine,
        settings,
        "target",
        target_id,
        body.mode if body else "offline",
        "target",
        include_all_modalities=body.include_all_modalities if body else False,
        owner_id=owner_id,
    )


class AnalysisEntry(BaseModel):
    """One stored analysis as the history list shows it."""

    analysis_id: uuid.UUID
    scope: str
    analysis_kind: str
    scope_label: str
    #: What to submit to the search box to reopen this scope; null when the
    #: scope entity is gone, so the UI never offers a dead navigation.
    scope_query: Optional[str] = None
    scope_id: Optional[uuid.UUID] = None
    provider: str
    model: Optional[str] = None
    mode: str
    provenance_state: str
    prompt_version: Optional[str] = None
    dataset_version: str
    created_at: str
    citation_count: int
    total_tokens: Optional[str] = None
    stale: bool = False
    stale_reasons: list[str] = []
    exact_check: Optional[dict] = None


class AnalysisListResponse(BaseModel):
    items: list[AnalysisEntry]
    total: int
    limit: int
    offset: int
    #: The deployment's current dataset version, so the list can say what its
    #: own staleness comparison used.
    current_dataset_version: Optional[str] = None


class AnalysisDetailResponse(AnalysisEntry):
    text: str
    citations: list[dict]
    usage: Optional[dict] = None


@router.get("/analyses", response_model=AnalysisListResponse)
def list_analyses(
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
    scope: Optional[str] = Query(default=None, pattern="^(family|document|target)$"),
    search: Optional[str] = Query(default=None, max_length=200),
    offset: int = 0,
    limit: int = 50,
):
    """Stored summaries this owner can reopen (B-10).

    Read-only: no provider is called, nothing is regenerated. Each entry states
    its scope, its model, its prompt/policy version and whether anything cheap
    says the data has moved since; the full check happens when one is opened.
    """
    from spago_core.services import analyses as analyses_svc

    try:
        items, total = analyses_svc.list_analyses(
            engine,
            auth_svc.owner_id_for(user),
            scope=scope,
            search=search,
            offset=offset,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    dataset = services.get_dataset_info(engine)
    return AnalysisListResponse(
        items=[AnalysisEntry(**item) for item in items],
        total=total,
        limit=max(1, min(limit, analyses_svc.MAX_PAGE)),
        offset=max(0, offset),
        current_dataset_version=dataset["dataset_version"] if dataset else None,
    )


@router.get("/analyses/{analysis_id}", response_model=AnalysisDetailResponse)
def get_analysis(
    analysis_id: uuid.UUID,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """One stored analysis with its text, citations and exact input check."""
    from spago_core.services import analyses as analyses_svc

    try:
        entry = analyses_svc.get_analysis(engine, analysis_id, auth_svc.owner_id_for(user))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnalysisDetailResponse(**entry)


@router.get("/analyses/{analysis_id}/export")
def export_analysis(
    analysis_id: uuid.UUID,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Download one analysis as a self-describing Markdown file.

    The header carries scope, provider, model, prompt version, policy version,
    data version and the staleness verdict, so the file stands on its own after
    it leaves the app (AGENTS.md §9, §25).
    """
    from spago_core.services import analyses as analyses_svc

    try:
        entry = analyses_svc.get_analysis(engine, analysis_id, auth_svc.owner_id_for(user))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    info = services.get_dataset_info(engine)
    content = analyses_svc.render_analysis_markdown(
        entry, current_dataset=info["dataset_version"] if info else None
    )
    filename = f"spago-{entry['scope']}-analysis-{str(analysis_id)[:8]}.md"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Lets a caller confirm what the file says without parsing it.
            "X-Spago-Analysis-Stale": "true" if entry["stale"] else "false",
        },
    )


@router.post("/ai/plan", response_model=SearchPlanResponse)
def ai_plan(
    body: PlanQueryRequest,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """Interpret a request into a validated, reviewable plan.

    The offline planner runs first and always succeeds for deterministic
    identifiers. `use_llm` opts in to the configured model for language
    interpretation; without it, free text is reported unresolved rather than
    guessed. The plan is not executed here — the caller reviews it and posts it
    to `/ai/plan/execute`.
    """
    from spago_core.services import planner as planner_svc

    context = _plan_context(engine, body)
    plan = planner_svc.offline_plan(body.query, context)
    mode = "offline"

    if body.use_llm and not plan.steps:
        from spago_core.adapters.llm import (
            LLMConfigProblem,
            OpenAICompatibleSummaryProvider,
            parse_endpoint,
        )

        if not (settings.llm_base_url or "").strip() or not (settings.llm_model or "").strip():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Language interpretation is not available: no model endpoint is configured. "
                    "Identifier requests and manual search still work."
                ),
            )
        try:
            endpoint = parse_endpoint(settings)
        except LLMConfigProblem as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        provider = OpenAICompatibleSummaryProvider(
            endpoint, client=getattr(request.app.state, "llm_client", None), scope="family"
        )
        proposer = planner_svc.OpenAICompatiblePlanProvider(provider)
        try:
            proposal = proposer.propose(body.query, context)
        except ai_svc.LLMTimeoutError as exc:
            raise HTTPException(status_code=504, detail=exc.detail) from exc
        except ai_svc.LLMAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except ai_svc.LLMUpstreamRateLimitError as exc:
            headers = (
                {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
            )
            raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
        except ai_svc.AIError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"The model response could not be read as a plan ({type(exc).__name__}).",
            ) from exc
        plan = planner_svc.plan_from_proposal(body.query, proposal, model=proposer.model)
        mode = "llm"

    return _plan_payload(plan, mode)


def _plan_context(engine, body: PlanQueryRequest) -> dict:
    """The authorized context a plan may use: the open family/document and an
    explicit selection — resolved server-side, never a project dataset."""
    from spago_core.services import find_patent, get_family_overview

    context: dict = {}
    if body.family_id is not None:
        try:
            overview = get_family_overview(engine, body.family_id)
            context["family_id"] = str(body.family_id)
            context["family_key"] = overview.family.family_key
            context["document_ids"] = [str(d.id) for d in overview.documents]
        except NotFoundError:
            context["family_scope_error"] = "the requested family scope does not exist"
    if body.document_id is not None:
        context["document_id"] = str(body.document_id)
    if body.selected_compound_id is not None:
        context["selected_compound_id"] = str(body.selected_compound_id)
    return context


@router.post("/ai/plan/execute", response_model=PlanExecuteResponse)
def ai_plan_execute(
    body: PlanExecuteRequest,
    engine=Depends(get_engine),
):
    """Execute a reviewed plan through the deterministic services.

    The posted plan is re-validated against the operation allowlist before
    anything runs, so a hand-written body cannot introduce an operation, an
    out-of-range parameter or an invented argument.
    """
    from spago_core.services import plan_execution
    from spago_core.services.planner import UnsupportedRequest

    try:
        result = plan_execution.execute_plan(engine, body.plan)
    except UnsupportedRequest as exc:
        detail = exc.reason + (f" {exc.suggestion}" if exc.suggestion else "")
        raise HTTPException(status_code=422, detail=detail) from exc
    return PlanExecuteResponse(
        query=result.query,
        producer=result.producer,
        steps=[PlanStepResultResponse(**s.to_dict()) for s in result.steps],
        unresolved=result.unresolved,
    )


# --- bulk layer proof (workload A) ---------------------------------------------------


class BulkCountsResponse(BaseModel):
    source: str
    dataset_version: str
    items: list[dict]


@router.get("/bulk/compound-counts", response_model=BulkCountsResponse)
def bulk_compound_counts(settings: Settings = Depends(get_settings)):
    adapter = SureChemblFixtureAdapter(settings.fixture_dir)
    result = adapter.load()
    counts = compound_counts_by_document(settings.fixture_dir)
    return BulkCountsResponse(
        source=result.envelope.source_name,
        dataset_version=result.envelope.dataset_version,
        items=[{"document_id": c.document_id, "record_count": c.record_count} for c in counts],
    )


# --- ONLINE-04: usage accounting and health ----------------------------------------


class UsageReportResponse(BaseModel):
    window: str
    user_tokens: int
    user_limit: int
    deployment_tokens: int
    deployment_limit: int
    requests: int
    failures: int
    estimated_cost: Optional[float] = None
    currency: Optional[str] = None
    cost_note: str = ""


@router.get("/usage", response_model=UsageReportResponse)
def usage_report(
    user: auth_svc.AuthUser = Depends(current_user),
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """The caller's own usage and the deployment's aggregate.

    A user sees their own consumption and the remaining deployment budget, but
    not another user's breakdown: the aggregate is the operator's, the detail is
    private.
    """
    from spago_core.services import usage as usage_svc

    report = usage_svc.report(
        engine,
        window=settings.llm_quota_window,
        user_limit=settings.llm_user_token_limit,
        deployment_limit=settings.llm_deployment_token_limit,
        owner_id=auth_svc.owner_id_for(user),
        price_per_million_tokens=settings.llm_price_per_million_tokens,
        currency=settings.llm_price_currency,
    )
    return UsageReportResponse(**report.to_dict())


class UsageEventResponse(BaseModel):
    id: str
    owner: Optional[str] = None
    provider: str
    model: Optional[str] = None
    scope: str
    outcome: str
    reserved_tokens: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    error: Optional[str] = None
    created_at: str
    settled_at: Optional[str] = None


@router.get("/usage/events", response_model=list[UsageEventResponse])
def usage_events(
    user: auth_svc.AuthUser = Depends(current_user),
    engine=Depends(get_engine),
    limit: int = Query(50, ge=1, le=500),
):
    """The operator's usage log. Administrator-only: it spans all owners."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="This operation requires an administrator.")
    from spago_core.services import usage as usage_svc

    return [UsageEventResponse(**row) for row in usage_svc.recent_usage(engine, limit)]


class ReadinessResponse(BaseModel):
    status: str
    checks: dict
    notes: list[str] = []


@router.get("/readyz", response_model=ReadinessResponse)
def readiness(engine=Depends(get_engine), settings: Settings = Depends(get_settings)):
    """Readiness for a hosted deployment: what must be true before serving users.

    Reports each check rather than a single boolean, so a failing deployment can
    be diagnosed from the response and a passing one is not assumed.
    """
    from sqlalchemy import text

    from spago_core.chemistry import chemistry_ok
    from spago_core.db import database_available

    checks: dict = {}
    notes: list[str] = []

    checks["database"] = database_available(engine)
    checks["chemistry"] = chemistry_ok()
    checks["auth_mode_configured"] = settings.auth_required or settings.seed_mode == "demo"
    checks["cookie_secure_for_https"] = (not settings.auth_required) or settings.cookie_secure
    checks["model_quota_configured"] = (
        settings.llm_user_token_limit > 0 and settings.llm_deployment_token_limit > 0
    )

    if checks["database"]:
        with engine.connect() as conn:
            checks["migrations_applied"] = conn.execute(
                text("SELECT count(*) > 0 FROM information_schema.tables WHERE table_name = 'schema_migrations'")
            ).scalar()
            checks["rdkit_cartridge"] = conn.execute(
                text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'rdkit')")
            ).scalar()
    else:
        checks["migrations_applied"] = False
        checks["rdkit_cartridge"] = False

    if settings.auth_required and not settings.cookie_secure:
        notes.append(
            "SPAGO_AUTH_MODE=required with SPAGO_COOKIE_SECURE=false: session cookies are sent "
            "without the Secure flag. Set it once the deployment is served over HTTPS."
        )
    if settings.seed_mode == "demo" and settings.auth_required:
        notes.append(
            "This hosted deployment is loading the synthetic demo fixture (SPAGO_SEED_MODE=demo). "
            "Set it to none for real data."
        )
    if settings.llm_user_token_limit <= 0 or settings.llm_deployment_token_limit <= 0:
        notes.append(
            "A model token limit is disabled (0): paid usage is not bounded by the service layer."
        )

    ok = all(
        checks[key]
        for key in ("database", "chemistry", "migrations_applied", "rdkit_cartridge")
    )
    return ReadinessResponse(
        status="ready" if ok else "not_ready",
        checks=checks,
        notes=notes,
    )


# --- ONLINE-00: target-led investigation ----------------------------------------


class TargetScopeRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    query: str = Field(min_length=1, max_length=200)
    species: str = Field(default="human", max_length=60)
    #: Offer receptor/partner/pathway expansion. The response always labels
    #: which members are related rather than the requested target.
    include_related: bool = True


class TargetComponentResponse(BaseModel):
    accession: Optional[str] = None
    name: Optional[str] = None
    gene_symbol: Optional[str] = None
    role: Optional[str] = None
    organism: Optional[str] = None


class ResolutionCandidateResponse(BaseModel):
    identifier: str
    name: Optional[str] = None
    organism: Optional[str] = None
    target_type: Optional[str] = None
    source_name: Optional[str] = None
    reason: Optional[str] = None


class TargetResolutionResponse(BaseModel):
    status: str
    query: str
    species: str
    target_id: Optional[uuid.UUID] = None
    target_key: Optional[str] = None
    name: Optional[str] = None
    organism: Optional[str] = None
    uniprot_accession: Optional[str] = None
    gene_symbol: Optional[str] = None
    target_type: Optional[str] = None
    scope_kind: Optional[str] = None
    aliases: list[str] = []
    components: list[TargetComponentResponse] = []
    candidates: list[ResolutionCandidateResponse] = []
    excluded: list[ResolutionCandidateResponse] = []
    notes: list[str] = []
    source_name: str = "uniprot"
    source_version: Optional[str] = None
    retrieved_at: str = ""




def _target_payload(target, resolution: Optional[TargetResolutionResponse] = None) -> ResolvedTargetResponse:
    """Serialize a resolved target exactly once, so components are never passed
    twice (a pydantic model dump already carries them)."""
    payload = target.model_dump()
    payload["components"] = [
        TargetComponentResponse(**c.model_dump()) for c in target.components
    ]
    payload["resolution"] = resolution
    return ResolvedTargetResponse(**payload)


class ResolvedTargetResponse(BaseModel):
    id: uuid.UUID
    target_key: str
    name: Optional[str] = None
    organism: Optional[str] = None
    taxon_id: Optional[int] = None
    uniprot_accession: Optional[str] = None
    gene_symbol: Optional[str] = None
    target_type: Optional[str] = None
    scope_kind: Optional[str] = None
    aliases: list[str] = []
    components: list[TargetComponentResponse] = []
    source_name: Optional[str] = None
    dataset_version: Optional[str] = None
    #: Only present when the scope was actually resolved in this deployment.
    resolution: Optional[TargetResolutionResponse] = None


def _resolution_payload(outcome) -> TargetResolutionResponse:
    record = outcome.record
    target = outcome.target
    return TargetResolutionResponse(
        status=record.status,
        query=record.query,
        species=record.species,
        target_id=target.id if target else None,
        target_key=target.target_key if target else None,
        name=target.name if target else None,
        organism=target.organism if target else None,
        uniprot_accession=target.uniprot_accession if target else None,
        gene_symbol=target.gene_symbol if target else None,
        target_type=target.target_type.value if target and target.target_type else None,
        scope_kind=target.scope_kind.value if target and target.scope_kind else None,
        aliases=list(target.aliases) if target else [],
        components=[
            TargetComponentResponse(**c.model_dump()) for c in (target.components if target else [])
        ],
        candidates=[ResolutionCandidateResponse(**c.model_dump()) for c in record.candidates],
        excluded=[ResolutionCandidateResponse(**c.model_dump()) for c in record.excluded],
        notes=list(record.notes),
        source_name=record.source_name,
        source_version=record.source_version,
        retrieved_at=record.retrieved_at.isoformat(),
    )


def _get_target_service(request: Request):
    from spago_core.services.targets import TargetResolutionService

    return getattr(request.app.state, "target_service", None) or TargetResolutionService()


def _get_discovery_service(request: Request):
    from spago_core.services.discovery import TargetDiscoveryService

    return getattr(request.app.state, "discovery_service", None) or TargetDiscoveryService()


@router.post("/targets/resolve", response_model=TargetResolutionResponse)
def resolve_target(
    body: TargetScopeRequest,
    request: Request,
    engine=Depends(get_engine),
):
    """Resolve a requested target to a reviewed protein identity.

    Ambiguity is reported, not resolved silently: `status` is `resolved`,
    `ambiguous`, `not_found` or `failed`, and the alternatives are returned
    either way. No network call happens unless the target is not already
    resolved in this deployment.
    """
    from spago_core.services.targets import TargetResolutionService

    service = _get_target_service(request)
    existing = service.find_target(engine, body.query)
    if existing is not None:
        record = service.latest_resolution(engine, existing.id)
        return TargetResolutionResponse(
            status="resolved",
            query=body.query,
            species=body.species,
            target_id=existing.id,
            target_key=existing.target_key,
            name=existing.name,
            organism=existing.organism,
            uniprot_accession=existing.uniprot_accession,
            gene_symbol=existing.gene_symbol,
            target_type=existing.target_type.value if existing.target_type else None,
            scope_kind=existing.scope_kind.value if existing.scope_kind else None,
            aliases=existing.aliases,
            components=[TargetComponentResponse(**c.model_dump()) for c in existing.components],
            candidates=(
                [ResolutionCandidateResponse(**c.model_dump()) for c in record.candidates]
                if record
                else []
            ),
            excluded=(
                [ResolutionCandidateResponse(**c.model_dump()) for c in record.excluded]
                if record
                else []
            ),
            notes=(
                list(record.notes) if record else ["No stored resolution record for this scope."]
            )
            + ["Reused the already-resolved scope; no new source lookup was performed."],
            source_name=(record.source_name if record else existing.source_name) or "uniprot",
            source_version=record.source_version if record else None,
            retrieved_at=(record.retrieved_at.isoformat() if record else ""),
        )
    outcome = service.resolve(
        engine, body.query, body.species, include_related=body.include_related
    )
    return _resolution_payload(outcome)


@router.get("/targets", response_model=list[ResolvedTargetResponse])
def list_targets(engine=Depends(get_engine), request: Request = None):
    service = _get_target_service(request)
    return [_target_payload(t) for t in service.list_targets(engine)]


@router.get("/targets/{target_id}", response_model=ResolvedTargetResponse)
def get_target(target_id: uuid.UUID, engine=Depends(get_engine), request: Request = None):
    from spago_core.services import NotFoundError

    service = _get_target_service(request)
    try:
        target = service.get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record = service.latest_resolution(engine, target.id)
    return _target_payload(
        target,
        resolution=(
            TargetResolutionResponse(
                status=record.status,
                query=record.query,
                species=record.species,
                target_id=target.id,
                target_key=target.target_key,
                name=target.name,
                organism=target.organism,
                uniprot_accession=target.uniprot_accession,
                gene_symbol=target.gene_symbol,
                target_type=target.target_type.value if target.target_type else None,
                scope_kind=target.scope_kind.value if target.scope_kind else None,
                aliases=target.aliases,
                components=[
                    TargetComponentResponse(**c.model_dump()) for c in target.components
                ],
                candidates=[
                    ResolutionCandidateResponse(**c.model_dump()) for c in record.candidates
                ],
                excluded=[
                    ResolutionCandidateResponse(**c.model_dump()) for c in record.excluded
                ],
                notes=list(record.notes),
                source_name=record.source_name,
                source_version=record.source_version,
                retrieved_at=record.retrieved_at.isoformat(),
            )
            if record
            else None
        ),
    )


class DiscoverRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    target_id: uuid.UUID
    sources: list[str] = Field(
        default_factory=lambda: ["chembl", "bindingdb", "pubchem"],
        max_length=4,
    )
    include_related: bool = False


class RetrievalResponse(BaseModel):
    source_name: str
    status: str
    query: dict = {}
    dataset_version: Optional[str] = None
    source_version: Optional[str] = None
    pages_fetched: int = 0
    records_seen: int = 0
    records_kept: int = 0
    records_excluded: int = 0
    rejection_counts: dict = {}
    #: B-02: how the source-declared document reference resolved over the kept
    #: records (disjoint buckets; sum = `records_kept`). Empty means the run
    #: predates the tally and must not be read as "none declared".
    reference_counts: dict = {}
    latency_ms: Optional[int] = None
    warnings: list[str] = []
    checksum: Optional[str] = None
    retrieved_at: str
    #: B-06: whether *this* run asked this source. False means the row reports the
    #: source's last stored outcome, which this run did not touch. Null on a
    #: stored-state read (`/targets/{id}/coverage`), where no run is described.
    requested_in_run: Optional[bool] = None


class ActiveCompoundResponse(BaseModel):
    compound_id: uuid.UUID
    inchikey: str
    potency_label: str
    standard_type: str
    value: float
    unit: str
    relation: str
    value_nm: float
    evidence_class: str
    source_name: str
    measurement_id: Optional[uuid.UUID] = None
    potential_duplicate: bool = False


class ReferencePolicyResponse(BaseModel):
    version: str
    threshold_nm: float
    threshold_label: str
    min_compounds: int
    #: True when the verdict counted every modality the source returned.
    all_modalities: bool = False
    modality_scope: str
    scope_note: str


class ReferenceVerdictResponse(BaseModel):
    """A deterministic count with its numbers, not a biological conclusion."""

    target_id: uuid.UUID
    target_key: str
    target_name: Optional[str] = None
    qualifies: bool = False
    reason: str = ""
    policy: ReferencePolicyResponse
    compounds: int = 0
    compounds_active: int = 0
    compounds_weak: int = 0
    compounds_unknown: int = 0
    compounds_not_applicable: int = 0
    active_compounds_outside_scope: int = 0
    measurements: int = 0
    class_counts: dict = {}
    endpoint_counts: dict = {}
    evidence_class_counts: dict = {}
    modality_counts: dict = {}
    actives: list[ActiveCompoundResponse] = []
    best_active: Optional[ActiveCompoundResponse] = None
    potential_duplicates: int = 0
    records_without_structure: int = 0
    #: ONLINE-07: hand-added rows that carry a value but no public structure.
    supplement_remarks: int = 0
    withdrawn_supplements: int = 0
    #: B-25: rows a bundle (agent or script) proposed and no person has confirmed.
    #: Stored and readable, and deliberately outside every count above.
    unreviewed_supplements: int = 0
    source_declared_patents: list[str] = []
    truncated: bool = False


def _verdict_payload(verdict) -> ReferenceVerdictResponse:
    return ReferenceVerdictResponse(
        target_id=verdict.target_id,
        target_key=verdict.target_key,
        target_name=verdict.target_name,
        qualifies=verdict.qualifies,
        reason=verdict.reason,
        policy=ReferencePolicyResponse(**verdict.policy.model_dump()),
        compounds=verdict.compounds,
        compounds_active=verdict.compounds_active,
        compounds_weak=verdict.compounds_weak,
        compounds_unknown=verdict.compounds_unknown,
        compounds_not_applicable=verdict.compounds_not_applicable,
        active_compounds_outside_scope=verdict.active_compounds_outside_scope,
        measurements=verdict.measurements,
        class_counts=verdict.class_counts,
        endpoint_counts=verdict.endpoint_counts,
        evidence_class_counts=verdict.evidence_class_counts,
        modality_counts=verdict.modality_counts,
        actives=[ActiveCompoundResponse(**a.model_dump()) for a in verdict.actives],
        best_active=(
            ActiveCompoundResponse(**verdict.best_active.model_dump())
            if verdict.best_active
            else None
        ),
        potential_duplicates=verdict.potential_duplicates,
        records_without_structure=verdict.records_without_structure,
        supplement_remarks=verdict.supplement_remarks,
        withdrawn_supplements=verdict.withdrawn_supplements,
        unreviewed_supplements=verdict.unreviewed_supplements,
        source_declared_patents=verdict.source_declared_patents,
        truncated=verdict.truncated,
    )


def _potency_override(
    settings: Settings,
    activity_threshold_nm: Optional[float],
    min_compounds: Optional[int],
    include_all_modalities: bool,
):
    """The stated policy for one request: deployment defaults plus overrides."""
    from spago_core.services.reference import policy_from_settings

    return policy_from_settings(
        settings,
        threshold_nm=activity_threshold_nm,
        min_compounds=min_compounds,
        include_all_modalities=include_all_modalities,
    )


class DiscoverResponse(BaseModel):
    target_id: uuid.UUID
    target_key: str
    sources: list[RetrievalResponse]
    compounds_stored: int
    compounds_reused: int
    measurements_stored: int
    candidates_stored: int
    small_molecule_candidates: int
    modality_counts: dict = {}
    rejections: dict = {}
    warnings: list[str] = []
    #: ONLINE-06: the potency verdict under the deployment policy, computed from
    #: the rows just persisted. The UI needs no second call and no second rule.
    reference: Optional[ReferenceVerdictResponse] = None
    #: Required by the plan: an empty result must never read as "no inhibitors".
    coverage_note: str = (
        "A source that returned nothing, failed, or was not queried is reported as such. "
        "Missing records do not demonstrate that no inhibitors exist."
    )


@router.post("/targets/discover", response_model=DiscoverResponse)
def discover_target(
    body: DiscoverRequest,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """Run bounded retrieval from the open sources for a resolved target.

    `sources` may name a subset: only those sources are asked and only their
    stored retrieval is rewritten. Every other source is reported from its stored
    outcome with `requested_in_run=false` — a retry of one source must not blank
    another's status, and B-06 is the recovery path for a single failed source.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.discovery import EXTERNAL_SOURCES
    from spago_core.services.reference import reference_verdict

    unknown = [s for s in body.sources if s not in EXTERNAL_SOURCES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported source(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(EXTERNAL_SOURCES)}.",
        )
    if not body.sources:
        raise HTTPException(
            status_code=422,
            detail="Name at least one source; a run that asks nothing would only re-date the target.",
        )
    target_service = _get_target_service(request)
    try:
        target = target_service.get_target(engine, body.target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    service = _get_discovery_service(request)
    report = service.investigate(engine, target, body.sources)
    asked = set(report.requested_sources)
    # The verdict is computed from the rows that were just persisted, under the
    # deployment policy, so it reports the retrieval that happened rather than
    # whatever the caller hoped for.
    verdict = reference_verdict(engine, target, _potency_override(settings, None, None, False))
    return DiscoverResponse(
        target_id=report.target_id,
        target_key=report.target_key,
        sources=[
            RetrievalResponse(
                source_name=r.source_name,
                status=r.status.value,
                query=r.query,
                dataset_version=r.dataset_version,
                source_version=r.source_version,
                pages_fetched=r.pages_fetched,
                records_seen=r.records_seen,
                records_kept=r.records_kept,
                records_excluded=r.records_excluded,
                rejection_counts=r.rejection_counts,
                reference_counts=r.reference_counts,
                latency_ms=r.latency_ms,
                warnings=r.warnings,
                checksum=r.checksum,
                retrieved_at=r.retrieved_at.isoformat(),
                requested_in_run=r.source_name in asked,
            )
            for r in report.retrievals
        ],
        compounds_stored=report.compounds_stored,
        compounds_reused=report.compounds_reused,
        measurements_stored=report.measurements_stored,
        candidates_stored=report.candidates_stored,
        small_molecule_candidates=report.small_molecule_candidates,
        modality_counts=report.modality_counts,
        rejections=report.rejections,
        warnings=report.warnings,
        reference=_verdict_payload(verdict),
    )


@router.get("/targets/{target_id}/reference", response_model=ReferenceVerdictResponse)
def target_reference(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    activity_threshold_nm: Optional[float] = Query(None, gt=0, le=1e9),
    min_compounds: Optional[int] = Query(None, ge=1, le=10_000),
    include_all_modalities: bool = False,
):
    """Whether this target's retrieved set can serve as a potency reference.

    A deterministic count under an explicit policy: how many in-scope compounds
    were reported at or below the threshold, how many were weak or undecided,
    and what the source records did *not* provide (values without structures).
    The response states the policy it used; nothing here is a biological
    conclusion, and a thin set is never reported as a negative result.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.reference import reference_verdict

    try:
        target = _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    policy = _potency_override(
        settings, activity_threshold_nm, min_compounds, include_all_modalities
    )
    return _verdict_payload(reference_verdict(engine, target, policy))


class CandidateResponse(BaseModel):
    compound_id: uuid.UUID
    canonical_smiles: str
    inchikey: str
    molecular_formula: Optional[str] = None
    molecular_weight: Optional[float] = None
    modality: str
    modality_rule: Optional[str] = None
    modality_source: Optional[str] = None
    source_name: str
    source_record_id: str
    evidence_class: str
    #: How many patent occurrences exist. Zero is a first-class, savable state:
    #: a candidate with no patent mapping is not discarded (ONLINE-00 C).
    patent_occurrences: int = 0
    patent_labels: list[str] = []
    measurements: int = 0
    #: ONLINE-06: this compound's own potency class under the requested policy,
    #: with the as-reported label that decided it, the sources behind it, and any
    #: publication numbers the *source* declares (source-declared, not corpus).
    activity_class: str = "not_applicable"
    activity_rule: Optional[str] = None
    potency_label: Optional[str] = None
    sources: list[str] = []
    source_declared_patents: list[str] = []
    #: True only for a row returned because it was asked for by id while the
    #: active filter excludes it. Not part of `total`; the table labels it.
    outside_filter: bool = False


class CandidatePageResponse(BaseModel):
    total: int
    offset: int
    limit: int
    items: list[CandidateResponse]
    modality_breakdown: dict = {}
    default_filter: str = "small molecules and unclassified entities"
    policy: Optional[ReferencePolicyResponse] = None


@router.get("/targets/{target_id}/candidates", response_model=CandidatePageResponse)
def list_target_candidates(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    modality: Optional[str] = None,
    evidence_class: Optional[str] = None,
    include_all_modalities: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(_DEFAULT_PAGE, ge=1),
    activity_threshold_nm: Optional[float] = Query(None, gt=0, le=1e9),
    include_compound_id: Optional[list[uuid.UUID]] = Query(
        None,
        description=(
            "Repeatable. Adds each given compound as a labelled `outside_filter` row when "
            "the current filter excludes it, so every saved or deep-linked item stays "
            "visible without the scope changing by itself (defect D2)."
        ),
    ),
):
    """Candidate compounds for a target.

    The default view is small molecules and unclassified entities. Peptides,
    oligonucleotides and biologics are excluded by an explicit, labelled filter
    whose counts are returned in `modality_breakdown` — never dropped silently.

    `include_compound_id` (repeatable) adds those compounds as labelled
    `outside_filter` rows when the filter excludes them, so a saved or deep-linked
    item stays visible without changing the scope the reader is looking at.

    Each row carries the potency class of that compound under the requested
    policy, so the table and the verdict above it are computed by one rule.
    """
    from spago_core.services import NotFoundError
    from spago_core.services import discovery as discovery_svc

    offset, limit = services.clamp_page(
        offset, limit, settings.default_page_size, settings.max_page_size
    )
    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    policy = _potency_override(settings, activity_threshold_nm, None, False)
    total, items = discovery_svc.list_candidates(
        engine,
        target_id,
        modality=modality,
        evidence_class=evidence_class,
        include_all_modalities=include_all_modalities,
        offset=offset,
        limit=limit,
        pin_compound_ids=include_compound_id,
        policy=policy,
    )
    return CandidatePageResponse(
        total=total,
        offset=offset,
        limit=limit,
        items=[CandidateResponse(**item.model_dump(mode="json")) for item in items],
        modality_breakdown=discovery_svc.modality_breakdown(engine, target_id),
        default_filter=(
            "all modalities"
            if include_all_modalities
            else "small molecules and unclassified entities"
        ),
        policy=ReferencePolicyResponse(**policy.model_dump()),
    )


@router.get("/targets/{target_id}/coverage", response_model=list[RetrievalResponse])
def target_coverage(target_id: uuid.UUID, request: Request, engine=Depends(get_engine)):
    """The coverage matrix for one target: per-source retrieval outcome."""
    from spago_core.services import NotFoundError
    from spago_core.services import discovery as discovery_svc

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        RetrievalResponse(
            source_name=r.source_name,
            status=r.status.value,
            query=r.query,
            dataset_version=r.dataset_version,
            source_version=r.source_version,
            pages_fetched=r.pages_fetched,
            records_seen=r.records_seen,
            records_kept=r.records_kept,
            records_excluded=r.records_excluded,
            rejection_counts=r.rejection_counts,
            reference_counts=r.reference_counts,
            latency_ms=r.latency_ms,
            warnings=r.warnings,
            checksum=r.checksum,
            retrieved_at=r.retrieved_at.isoformat(),
        )
        for r in discovery_svc.list_source_retrievals(engine, target_id)
    ]


class MeasurementResponse(BaseModel):
    id: uuid.UUID
    compound_id: uuid.UUID
    inchikey: Optional[str] = None
    #: The object the measurement is actually against. For an interaction or
    #: complex target this is that object, not the investigated protein.
    target_name: Optional[str] = None
    target_key: Optional[str] = None
    target_type: Optional[str] = None
    assay_key: str
    assay_type: Optional[str] = None
    assay_description: Optional[str] = None
    #: ONLINE-07: the note a person wrote when adding the row by hand. Separate from
    #: `assay_description` on purpose — one is a source's assay, the other is a
    #: statement by a person, and a reader must be able to tell them apart.
    note: Optional[str] = None
    assay_format: Optional[str] = None
    standard_type: str
    value: float
    unit: str
    relation: str
    raw_value: Optional[str] = None
    evidence_class: str
    species: Optional[str] = None
    variant_accession: Optional[str] = None
    variant_mutation: Optional[str] = None
    pchembl_value: Optional[float] = None
    potential_duplicate: bool = False
    validity_comment: Optional[str] = None
    document_ref: Optional[str] = None
    #: ONLINE-06: the reference decomposed, and the class this one report
    #: supports under the requested threshold (never stored, always recomputed).
    document_patent_number: Optional[str] = None
    document_doi: Optional[str] = None
    document_pmid: Optional[str] = None
    activity_class: str = "not_applicable"
    activity_class_rule: Optional[str] = None
    source_url: Optional[str] = None
    source_record_id: Optional[str] = None
    source_name: str
    extraction_method: str
    provenance_state: str
    dataset_version: str
    retrieved_at: str


@router.get("/targets/{target_id}/measurements", response_model=list[MeasurementResponse])
def target_measurements(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    compound_id: Optional[uuid.UUID] = None,
    evidence_class: Optional[str] = None,
    include_duplicates: bool = True,
    limit: int = Query(200, ge=1, le=500),
    activity_threshold_nm: Optional[float] = Query(None, gt=0, le=1e9),
):
    """Every measurement for a target, with its assay context.

    Values are never ranked or averaged across assays: Kd, Ki, IC50 and EC50
    stay distinct, contradictions are preserved, and records that share an
    original document reference are flagged (ONLINE-00 C). Each row states what
    its own report implies under the displayed threshold (ONLINE-06).
    """
    from spago_core.services import NotFoundError
    from spago_core.services import discovery as discovery_svc

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    policy = _potency_override(settings, activity_threshold_nm, None, False)
    return discovery_svc.list_target_measurements(
        engine,
        target_id,
        compound_id=compound_id,
        evidence_class=evidence_class,
        include_duplicates=include_duplicates,
        limit=limit,
        threshold_nm=policy.threshold_nm,
    )


class SupplementRowOutcomeResponse(BaseModel):
    index: int
    status: str
    name: str = ""
    #: The id `…/supplements/{record_id}/withdraw` accepts, so the dialog can
    #: offer the action for the row it just stored (defect D3).
    record_id: Optional[str] = None
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    activity_class: Optional[str] = None
    reused_compound: bool = False
    reasons: list[str] = []


class SupplementImportResponse(BaseModel):
    """What one import applied, per row and per reason (ONLINE-07).

    A partial import is reported as such: no row is dropped silently, and a rejected
    row carries the reason it was refused.
    """

    target_id: uuid.UUID
    received: int = 0
    measurements: int = 0
    remarks: int = 0
    compounds_created: int = 0
    compounds_reused: int = 0
    updated: int = 0
    rows: list[SupplementRowOutcomeResponse] = []


class SupplementRemarkResponse(BaseModel):
    id: uuid.UUID
    target_id: uuid.UUID
    name: str
    note: str
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    patent_number: Optional[str] = None
    provenance_state: str
    created_at: str
    #: A withdrawn row stays readable: what a user took back, and why, is state
    #: the reader must be able to see (migration 0015).
    source_record_id: str
    retracted_at: Optional[str] = None
    retracted_reason: Optional[str] = None


class SupplementRequest(BaseModel):
    """A bounded batch of hand-added literature rows.

    The shape is fixed (`extra: forbid` inside each row) and the batch is capped,
    because this is the one write path where a caller supplies scientific content
    directly (AGENTS.md §12). The note requirement lives on the row model so a body
    cannot omit it.
    """

    model_config = {"extra": "forbid"}
    rows: list[dict] = Field(default_factory=list, max_length=MAX_SUPPLEMENT_ROWS)


@router.post("/targets/{target_id}/supplements", response_model=SupplementImportResponse)
def add_target_supplements(
    target_id: uuid.UUID,
    body: SupplementRequest,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Add literature/patent rows by hand to a target.

    Each row is validated on its own and answered for: stored as a user-curated
    measurement (`source_name='user_supplement'`, `provenance_state='user_curated'`),
    kept as a structure-less remark when no public structure was supplied, or refused
    with its reasons. A row never becomes a source fact, and re-posting the same row
    updates it instead of duplicating the claim.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.reference import policy_from_settings
    from spago_core.services.supplements import import_supplements

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    policy = policy_from_settings(settings)
    result = import_supplements(
        engine, target_id, body.rows, threshold_nm=policy.threshold_nm
    )
    return SupplementImportResponse(
        target_id=result.target_id,
        received=result.received,
        measurements=result.measurements,
        remarks=result.remarks,
        compounds_created=result.compounds_created,
        compounds_reused=result.compounds_reused,
        updated=result.updated,
        rows=[
            SupplementRowOutcomeResponse(
                index=outcome.index,
                status=outcome.status,
                name=outcome.name,
                record_id=outcome.record_id,
                compound_id=outcome.compound_id,
                inchikey=outcome.inchikey,
                activity_class=(
                    outcome.activity_class.value if outcome.activity_class else None
                ),
                reused_compound=outcome.reused_compound,
                reasons=outcome.reasons,
            )
            for outcome in result.rows
        ],
    )


@router.get(
    "/targets/{target_id}/supplements/remarks",
    response_model=list[SupplementRemarkResponse],
)
def target_supplement_remarks(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
):
    """Stored structure-less literature rows for a target.

    They are kept because a thin set must not be read as a negative result, and they
    are not compounds: no structure was published, so SPAgo will not invent one.
    Withdrawn rows are returned with their reason rather than hidden: a row the user
    took back is a fact about the investigation (migration 0015).
    """
    from spago_core.services import NotFoundError
    from spago_core.services.supplements import list_supplement_remarks

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        SupplementRemarkResponse(
            id=remark.id,
            target_id=remark.target_id,
            source_record_id=remark.source_record_id,
            name=remark.name,
            note=remark.note,
            activity_type=remark.activity_type,
            value=remark.value,
            unit=remark.unit,
            relation=remark.relation,
            doi=remark.doi,
            pmid=remark.pmid,
            patent_number=remark.patent_number,
            provenance_state=remark.provenance_state.value,
            created_at=remark.created_at.isoformat(),
            retracted_at=remark.retracted_at.isoformat() if remark.retracted_at else None,
            retracted_reason=remark.retracted_reason,
        )
        for remark in list_supplement_remarks(engine, target_id, include_withdrawn=True)
    ]


class SupplementWithdrawalRequest(BaseModel):
    """Why a hand-added row is being taken back. Required: a withdrawal without a
    reason would be an unexplained disappearance (AGENTS.md §10)."""

    reason: str = Field(min_length=3, max_length=500)


class SupplementWithdrawalResponse(BaseModel):
    status: str
    kind: str
    #: The id the caller used, so a UI can drop the row it just took back.
    record_id: str
    compound_id: Optional[uuid.UUID] = None
    candidate_retracted: bool = False
    reason: str


class WithdrawnSupplementResponse(BaseModel):
    """A hand-added row the user took back: the audit trail behind
    `withdrawn_supplements` in the verdict (defect D3)."""

    kind: str
    record_id: str
    name: str = ""
    note: Optional[str] = None
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    retracted_at: str
    retracted_reason: Optional[str] = None
    candidate_retracted: bool = False


@router.get(
    "/targets/{target_id}/supplements/withdrawn",
    response_model=list[WithdrawnSupplementResponse],
)
def target_withdrawn_supplements(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
):
    """Rows this user added by hand and later took back.

    A withdrawal must not read as a row that never existed: the row, its note, its
    value and the reason are returned so the dialog can show them (AGENTS.md §10).
    """
    from spago_core.services import NotFoundError
    from spago_core.services.supplements import list_withdrawn_supplements

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        WithdrawnSupplementResponse(
            kind=row.kind,
            record_id=row.record_id,
            name=row.name,
            note=row.note,
            activity_type=row.activity_type,
            value=row.value,
            unit=row.unit,
            relation=row.relation,
            retracted_at=row.retracted_at.isoformat(),
            retracted_reason=row.retracted_reason,
            candidate_retracted=row.candidate_retracted,
        )
        for row in list_withdrawn_supplements(engine, target_id)
    ]


@router.post(
    "/targets/{target_id}/supplements/{record_id}/withdraw",
    response_model=SupplementWithdrawalResponse,
)
def withdraw_target_supplement(
    target_id: uuid.UUID,
    record_id: str,
    body: SupplementWithdrawalRequest,
    request: Request,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Take back a row this user added by hand (ONLINE-08).

    Only `user_supplement` rows can be withdrawn. A retrieved row belongs to its
    source; retracting one is a source-refresh action, not a user edit.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.supplements import withdraw_supplement

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        result = withdraw_supplement(engine, target_id, record_id, body.reason)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SupplementWithdrawalResponse(
        status="withdrawn",
        kind=result.kind,
        record_id=result.record_id,
        compound_id=uuid.UUID(result.compound_id) if result.compound_id else None,
        candidate_retracted=result.candidate_retracted,
        reason=result.reason,
    )


# --- B-25: importing a set of literature rows as one artifact, and reviewing it ------


class SuppliedRowStateResponse(BaseModel):
    """One stored row of an import as it stands now: readable whatever its state."""

    kind: str
    record_id: str
    name: str = ""
    note: Optional[str] = None
    activity_type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    relation: Optional[str] = None
    doi: Optional[str] = None
    pmid: Optional[str] = None
    patent_number: Optional[str] = None
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    #: Computed on read under the deployment's policy, never stored.
    activity_class: Optional[str] = None
    activity_class_rule: Optional[str] = None
    live: bool = True
    retracted_at: Optional[str] = None
    retracted_reason: Optional[str] = None


class SupplementImportReportResponse(BaseModel):
    """The stored record of one import: who produced it, what it refused, its review."""

    id: uuid.UUID
    target_id: uuid.UUID
    bundle_hash: str
    bundle_version: int
    produced_by: str
    produced_by_kind: str
    searched: str
    generated_at: Optional[str] = None
    received: int = 0
    measurements: int = 0
    remarks: int = 0
    rejected: int = 0
    compounds_created: int = 0
    compounds_reused: int = 0
    updated_rows: int = 0
    record_ids: list[str] = []
    rows: list[SupplementRowOutcomeResponse] = []
    provenance_state: str
    submitted_by: Optional[str] = None
    created_at: str
    confirmed_at: Optional[str] = None
    confirmed_by: Optional[str] = None
    #: True when these rows are proposals: stored, readable, outside the investigation.
    awaiting_review: bool = False
    #: Set when this same bundle was imported for this target before.
    repeated_of: Optional[uuid.UUID] = None
    #: The rows as they stand *now* (may have been withdrawn since the import).
    stored: list[SuppliedRowStateResponse] = []


class SupplementBundleImportResponse(BaseModel):
    report: SupplementImportReportResponse


class SupplementConfirmationResponse(BaseModel):
    import_id: uuid.UUID
    target_id: uuid.UUID
    rows: int = 0
    candidates_created: int = 0
    confirmed_at: str
    confirmed_by: Optional[str] = None
    already_confirmed: bool = False


def _import_report_payload(
    report, *, awaiting_review: bool
) -> SupplementImportReportResponse:
    """One stored import as the response model: the run, its answers, its rows now."""
    return SupplementImportReportResponse(
        id=report.id,
        target_id=report.target_id,
        bundle_hash=report.bundle_hash,
        bundle_version=report.bundle_version,
        produced_by=report.produced_by,
        produced_by_kind=report.produced_by_kind,
        searched=report.searched,
        generated_at=report.generated_at,
        received=report.received,
        measurements=report.measurements,
        remarks=report.remarks,
        rejected=report.rejected,
        compounds_created=report.compounds_created,
        compounds_reused=report.compounds_reused,
        updated_rows=report.updated_rows,
        record_ids=report.record_ids,
        rows=[
            SupplementRowOutcomeResponse(
                index=outcome.index,
                status=outcome.status,
                name=outcome.name,
                record_id=outcome.record_id,
                compound_id=outcome.compound_id,
                inchikey=outcome.inchikey,
                activity_class=(
                    outcome.activity_class.value if outcome.activity_class else None
                ),
                reused_compound=outcome.reused_compound,
                reasons=outcome.reasons,
            )
            for outcome in report.outcomes
        ],
        provenance_state=report.provenance_state.value,
        submitted_by=report.submitted_by,
        created_at=report.created_at.isoformat(),
        confirmed_at=report.confirmed_at.isoformat() if report.confirmed_at else None,
        confirmed_by=report.confirmed_by,
        awaiting_review=awaiting_review,
        repeated_of=report.repeated_of,
        stored=[
            SuppliedRowStateResponse(
                kind=state.kind,
                record_id=state.record_id,
                name=state.name,
                note=state.note,
                activity_type=state.activity_type,
                value=state.value,
                unit=state.unit,
                relation=state.relation,
                doi=state.doi,
                pmid=state.pmid,
                patent_number=state.patent_number,
                compound_id=state.compound_id,
                inchikey=state.inchikey,
                activity_class=(
                    state.activity_class.value if state.activity_class else None
                ),
                activity_class_rule=state.activity_class_rule,
                live=state.live,
                retracted_at=state.retracted_at.isoformat() if state.retracted_at else None,
                retracted_reason=state.retracted_reason,
            )
            for state in report.stored
        ],
    )


@router.post(
    "/targets/{target_id}/supplements/bundle",
    response_model=SupplementBundleImportResponse,
    status_code=201,
)
def import_target_supplement_bundle(
    target_id: uuid.UUID,
    body: SupplementBundle,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Import a whole literature artifact: rows plus the run that produced them.

    The part that makes this a workflow and not a paste box (B-25):

    * the file states who produced the rows and what was searched, and the report
      keeps that with the rows — the note a reader needs to re-find them (AGENTS.md §12);
    * a file a person wrote is their own statement; a file an agent or a script wrote is
      a **proposal**. Those rows are stored, readable and counted separately, and they
      join no verdict, selection, export or summary until a person confirms the import
      at `…/supplement-imports/{id}/confirm`;
    * a row SPAgo refuses is answered for with its reasons, per row, in the stored
      report — never silently dropped.

    The `record_ids` in the answer are the ids the withdrawal path accepts, so a row
    admitted here can be taken back the same way as a hand-typed one.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.reference import policy_from_settings
    from spago_core.services.supplements import BundleRefused, import_supplement_bundle

    try:
        _get_target_service(request).get_target(engine, target_id)
        result = import_supplement_bundle(
            engine,
            target_id,
            body,
            threshold_nm=policy_from_settings(settings).threshold_nm,
            submitted_by=(user.display_name or user.email),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BundleRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SupplementBundleImportResponse(
        report=_import_report_payload(result.report, awaiting_review=result.awaiting_review)
    )


@router.get(
    "/targets/{target_id}/supplement-imports",
    response_model=list[SupplementImportReportResponse],
)
def target_supplement_imports(
    target_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """Import runs for this target, newest first, with their rows as they stand now.

    A reader reopening a session must be able to see what arrived, who produced it and
    whether it has been reviewed — an unreviewed import that scrolled out of a dialog
    would otherwise be an invisible set of rows.
    """
    from spago_core.services import NotFoundError
    from spago_core.services.reference import policy_from_settings
    from spago_core.services.supplements import list_supplement_imports

    try:
        _get_target_service(request).get_target(engine, target_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        _import_report_payload(
            report,
            awaiting_review=(
                report.provenance_state.value != "user_curated" and report.confirmed_at is None
            ),
        )
        for report in list_supplement_imports(
            engine, target_id, threshold_nm=policy_from_settings(settings).threshold_nm
        )
    ]


@router.post(
    "/targets/{target_id}/supplement-imports/{import_id}/confirm",
    response_model=SupplementConfirmationResponse,
)
def confirm_target_supplement_import(
    target_id: uuid.UUID,
    import_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Admit an import's rows to the investigation after a person has read them.

    One recorded act with one meaning: the rows' provenance becomes `user_curated` and
    their live compounds join the investigation's candidates — the table migration 0015
    defines scope by. Nothing else changes, and the rows themselves are untouched, so
    the review leaves the file's own answer readable beside the human's (AGENTS.md §10).
    """
    from spago_core.services import NotFoundError
    from spago_core.services.supplements import confirm_supplement_import

    try:
        _get_target_service(request).get_target(engine, target_id)
        result = confirm_supplement_import(
            engine, target_id, import_id, confirmed_by=(user.display_name or user.email)
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SupplementConfirmationResponse(
        import_id=result.import_id,
        target_id=result.target_id,
        rows=result.rows,
        candidates_created=result.candidates_created,
        confirmed_at=result.confirmed_at.isoformat(),
        confirmed_by=result.confirmed_by,
        already_confirmed=result.already_confirmed,
    )


class CoverageMatrixRow(BaseModel):
    target_id: uuid.UUID
    target_key: str
    target_name: Optional[str] = None
    gene_symbol: Optional[str] = None
    uniprot_accession: Optional[str] = None
    target_type: Optional[str] = None
    organism: Optional[str] = None
    source_name: str
    status: str
    query: dict = {}
    records_seen: int = 0
    records_kept: int = 0
    records_excluded: int = 0
    rejection_counts: dict = {}
    #: B-02: how the source-declared document reference resolved over this
    #: retrieval's kept records (disjoint buckets; sum = `records_kept`). Empty
    #: means the run predates the tally — not "nothing was declared".
    reference_counts: dict = {}
    candidates: int = 0
    small_molecule_candidates: int = 0
    dataset_version: Optional[str] = None
    source_version: Optional[str] = None
    latency_ms: Optional[int] = None
    retrieved_at: str
    warnings: list[str] = []
    #: ONLINE-06: the same target's potency verdict, repeated on each of its rows
    #: so a coverage report can separate "retrieved nothing" from "retrieved a
    #: set with no compound at or below the threshold".
    reference_qualifies: Optional[bool] = None
    reference_reason: Optional[str] = None
    reference_threshold_nm: Optional[float] = None
    reference_n_active: Optional[int] = None
    reference_policy_version: Optional[str] = None


@router.get("/targets/coverage/matrix", response_model=list[CoverageMatrixRow])
def coverage_matrix(
    engine=Depends(get_engine), settings: Settings = Depends(get_settings)
):
    """Dated source-by-target coverage: exact queries, counts, outcomes, versions.

    This is the artifact that makes an honest coverage claim possible. A row
    with `status: empty` and a row with `status: failed` are different facts and
    stay different here, and each target's potency verdict is reported next to
    the retrieval outcome that produced its compounds.
    """
    from spago_core.services import discovery as discovery_svc
    from spago_core.services.reference import policy_from_settings, reference_verdicts
    from spago_core.services.targets import TargetResolutionService

    rows = discovery_svc.coverage_matrix(engine)
    targets = {t.id: t for t in TargetResolutionService().list_targets(engine)}
    policy = policy_from_settings(settings)
    verdicts = reference_verdicts(engine, list(targets.values()), policy)
    out: list[CoverageMatrixRow] = []
    for row in rows:
        verdict = verdicts.get(row["target_id"])
        out.append(
            CoverageMatrixRow(
                **row,
                reference_qualifies=verdict.qualifies if verdict else None,
                reference_reason=verdict.reason if verdict else None,
                reference_threshold_nm=verdict.policy.threshold_nm if verdict else None,
                reference_n_active=verdict.compounds_active if verdict else None,
                reference_policy_version=verdict.policy.version if verdict else None,
            )
        )
    return out


# --- ONLINE-00: saving a candidate that has no patent mapping ----------------------


class SaveCandidateRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    target_id: uuid.UUID
    compound_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    evidence_class: Optional[str] = None


class SaveCandidateResponse(BaseModel):
    created_rows: int
    already_present_rows: int
    target_key: str
    dataset_versions: list[dict] = []


@router.post(
    "/projects/{project_id}/candidates", response_model=SaveCandidateResponse, status_code=201
)
def save_candidates(
    project_id: uuid.UUID,
    body: SaveCandidateRequest,
    request: Request,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    """Save target candidates to a project, including compounds with no patent
    occurrence. Such an item keeps its target scope and an identity snapshot
    (ONLINE-00 C: a non-patent candidate must remain usable and savable)."""
    from spago_core.services import NotFoundError
    from spago_core.services import projects as projects_svc

    try:
        _get_target_service(request).get_target(engine, body.target_id)
        result = projects_svc.save_candidates(
            engine,
            project_id,
            body.target_id,
            body.compound_ids,
            body.evidence_class,
            auth_svc.owner_id_for(user),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except projects_svc.ProjectScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SaveCandidateResponse(**result.__dict__)


# --- projects (M1: save-to-project) --------------------------------------------------


class ProjectSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    item_count: int
    created_at: str


class ProjectItemResponse(BaseModel):
    id: uuid.UUID
    #: Patent-scoped items carry a family; target-candidate items carry a
    #: target scope instead (ONLINE-00 C).
    family_id: Optional[uuid.UUID] = None
    family_key: Optional[str] = None
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    canonical_smiles: Optional[str] = None
    dataset_version: str
    # Full server-derived source list at save time (PROD-03) and drift flags.
    dataset_versions: list[dict] = []
    record_missing: bool = False
    source_updated: bool = False
    added_at: str
    target_id: Optional[uuid.UUID] = None
    target_key: Optional[str] = None
    target_name: Optional[str] = None
    evidence_class: Optional[str] = None


class ProjectDetailResponse(ProjectSummaryResponse):
    items: list[ProjectItemResponse]


class CreateProjectRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class SaveScopeRequest(BaseModel):
    family_id: uuid.UUID
    # None/empty saves the whole family; otherwise the selected compound ids.
    compound_ids: Optional[list[uuid.UUID]] = None
    # Deprecated: accepted for compatibility, ignored. The server derives the
    # dataset versions from the rows actually saved (PROD-03).
    dataset_version: Optional[str] = None


class SaveScopeResponse(BaseModel):
    created_rows: int
    already_present_rows: int
    scope_family: bool
    dataset_versions: list[dict] = []


@router.get("/projects", response_model=list[ProjectSummaryResponse])
def list_projects(engine=Depends(get_engine), user: auth_svc.AuthUser = Depends(current_user)):
    """Only the caller's own projects. An unassigned legacy project is not listed
    in hosted mode; it is attached by an operator command (ADR-0002)."""
    from spago_core.services import projects as projects_svc

    return projects_svc.list_projects(engine, auth_svc.owner_id_for(user))


@router.post("/projects", response_model=ProjectSummaryResponse, status_code=201)
def create_project(
    body: CreateProjectRequest,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    from spago_core.services import projects as projects_svc

    try:
        return projects_svc.create_project(
            engine, body.name, body.description, auth_svc.owner_id_for(user)
        )
    except projects_svc.ProjectScopeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: uuid.UUID,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    from spago_core.services import projects as projects_svc

    try:
        summary, items = projects_svc.get_project(
            engine, project_id, auth_svc.owner_id_for(user)
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ProjectDetailResponse(
        **summary.__dict__,
        items=[ProjectItemResponse(**i.__dict__) for i in items],
    )


@router.post("/projects/{project_id}/items", response_model=SaveScopeResponse)
def save_scope(
    project_id: uuid.UUID,
    body: SaveScopeRequest,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    from spago_core.services import projects as projects_svc

    try:
        result = projects_svc.save_scope(
            engine,
            project_id,
            body.family_id,
            body.compound_ids,
            body.dataset_version,
            auth_svc.owner_id_for(user),
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SaveScopeResponse(**result.__dict__)


@router.delete("/projects/{project_id}/items/{item_id}", status_code=204)
def remove_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    engine=Depends(get_engine),
    user: auth_svc.AuthUser = Depends(current_user),
):
    from spago_core.services import projects as projects_svc

    try:
        projects_svc.remove_item(engine, project_id, item_id, auth_svc.owner_id_for(user))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- export (M1: CSV / SDF with provenance) -------------------------------------------


class ExportStructureQueryBody(BaseModel):
    mode: str = Field(pattern="^(exact|substructure|similarity)$")
    smiles: str = Field(min_length=1, max_length=2000)
    threshold: Optional[float] = Field(default=None, ge=0.3, le=1.0)
    filters: Optional[MoleculeFiltersBody] = None


class ExportRequest(BaseModel):
    # Unknown fields are refused, not ignored: a caller must not be able to
    # smuggle in an endpoint, a model name or another scope.
    model_config = {"extra": "forbid"}
    # Exactly one scope owner: a patent family, or a target investigation
    # (ONLINE-00: a candidate with no patent mapping must still be exportable).
    family_id: Optional[uuid.UUID] = None
    target_id: Optional[uuid.UUID] = None
    document_id: Optional[uuid.UUID] = None
    # Explicit selection wins over family/document/structure scope.
    compound_ids: Optional[list[uuid.UUID]] = None
    # Re-executed server-side so the export covers every match, not just the
    # loaded page. Requires the same chemistry contract as structure search.
    structure_query: Optional[ExportStructureQueryBody] = None
    # Candidate exports default to the same small-molecule focus as the table;
    # the labelled expansion is an explicit request.
    include_all_modalities: bool = False
    # ONLINE-06: an export must state the rule behind its `activity_class` and
    # `reference_*` columns. A workspace that changed the threshold exports under
    # that same threshold, so the file matches the table it came from.
    activity_threshold_nm: Optional[float] = Field(default=None, gt=0, le=1e9)
    # B-33: the screen's evidence-class selection is part of the scope the user
    # is looking at, so "current results" must mean the same set the table
    # shows. Applied to the results scope only — an explicit selection wins
    # over filters, the same contract modality follows above.
    evidence_class: Optional[str] = Field(
        default=None,
        pattern=(
            "^(measured_direct_binding|interaction_disruption|functional_effect"
            "|screening_assay|unspecified)$"
        ),
    )
    format: str = Field(pattern="^(csv|sdf)$")


@router.post("/export")
def export_scope(
    body: ExportRequest,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
):
    """Export by server-side scope: an explicit selection, a structure query,
    a family/document scope — never silently only the loaded page.

    A candidate export also carries the potency class and the target's verdict
    under the deployment policy, so the file states the rule that produced its
    columns (ONLINE-06).

    Scope errors (unknown or out-of-scope ids, unusable structure query) and
    oversized scopes are rejected with 422 from the counting phase."""
    from spago_core.services import export as export_svc
    from spago_core.services import structure_search as ss

    if (body.family_id is None) == (body.target_id is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one export scope: family_id or target_id.",
        )
    if body.family_id is not None and body.evidence_class is not None:
        # A family/document scope has no evidence-class filter; accepting and
        # ignoring it here would let a filtered-looking request export an
        # unfiltered family — the exact defect B-33 closes.
        raise HTTPException(
            status_code=422,
            detail="evidence_class applies to target candidate exports only.",
        )

    structure_query = None
    if body.structure_query is not None and body.compound_ids is None:
        structure_query = export_svc.StructureExportQuery(
            mode=body.structure_query.mode,
            smiles=body.structure_query.smiles,
            threshold=body.structure_query.threshold,
            filters=(
                ss.MoleculeFilters(**body.structure_query.filters.model_dump())
                if body.structure_query.filters
                else None
            ),
        )

    try:
        if body.target_id is not None:
            rows = export_svc.collect_candidate_export_rows(
                engine,
                body.target_id,
                compound_ids=body.compound_ids,
                include_all_modalities=body.include_all_modalities,
                # A filter is a way to construct the current-results scope; an
                # explicit selection names its own rows and is not re-filtered.
                evidence_class=(
                    None if body.compound_ids is not None else body.evidence_class
                ),
                policy=_potency_override(
                    settings, body.activity_threshold_nm, None, body.include_all_modalities
                ),
            )
        else:
            rows = export_svc.collect_export_rows(
                engine,
                family_id=body.family_id,
                document_id=body.document_id,
                compound_ids=body.compound_ids,
                structure_query=structure_query,
            )
        if body.format == "csv":
            content = export_svc.render_csv(rows)
            media_type = "text/csv; charset=utf-8"
            filename = "spago-export.csv"
        else:
            content = export_svc.render_sdf(rows)
            media_type = "chemical/x-mdl-sdfile"
            filename = "spago-export.sdf"
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except export_svc.ExportTooLargeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except export_svc.ExportScopeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        # Covers structure-query parse errors (StructureParseError) and any
        # other scope-contract violation: 422 with the instance reason.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Lets callers and tests confirm the exported scope size without
            # parsing the file.
            "X-Spago-Export-Rows": str(len(rows)),
        },
    )
