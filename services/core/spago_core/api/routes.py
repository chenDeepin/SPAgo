"""HTTP API for SPAgo M0.

Serving rules: server-side paging (default 100, cap 500), lazy cached depictions,
explicit missing-source and not-found states. UI never sees adapter schemas.
"""
from __future__ import annotations

import uuid
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from spago_core import services
from spago_core.services import bioactivity as services_bioactivity
from spago_core.adapters import SureChemblFixtureAdapter
from spago_core.chemistry import StructureParseError, depict_svg
from spago_core.config import Settings, get_settings
from spago_core.domain import PatentDocument, PatentFamily
from spago_core.queries import compound_counts_by_document
from spago_core.services import NotFoundError

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
    )


# --- patents / families ----------------------------------------------------------


class FamilyOverviewResponse(BaseModel):
    family: PatentFamily
    documents: list[PatentDocument]
    mention_counts: dict[str, int]


class PatentResponse(BaseModel):
    document: PatentDocument
    family: PatentFamily
    documents: list[PatentDocument]
    mention_counts: dict[str, int]


@router.get("/patents/{publication_number}", response_model=PatentResponse)
def get_patent(publication_number: str, engine=Depends(get_engine)):
    try:
        document, overview = services.find_patent(engine, publication_number)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PatentResponse(
        document=document,
        family=overview.family,
        documents=overview.documents,
        mention_counts=overview.mention_counts,
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

    # Mentions for the search hits: one batched family query, per-hit fallback
    # for hits beyond the first max-size page.
    mention_map: dict = {}
    overview_page = services.list_family_compounds(
        engine, family_id, body.document_id, 0, settings.max_page_size
    )
    for row in overview_page.items:
        mention_map[row.compound.id] = [MentionResponse(**m.model_dump()) for m in row.mentions]

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
        mentions = mention_map.get(r["id"])
        if mentions is None:
            try:
                full = services.get_compound(engine, r["id"])
                mentions = [MentionResponse(**m.model_dump()) for m in full.mentions]
            except NotFoundError:
                mentions = []
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
    model: Optional[str] = None
    cached: bool = False
    usage: Optional[dict] = None
    coverage: list[dict] = []


class PlanQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class PlanQueryResponse(BaseModel):
    patent_queries: list[str]
    unresolved_text: Optional[str] = None
    note: str


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
    mode: str = Field(default="offline", pattern="^(offline|llm)$")


@router.post("/families/{family_id}/summary", response_model=FamilySummaryResponse)
def family_summary(
    family_id: uuid.UUID,
    request: Request,
    engine=Depends(get_engine),
    settings: Settings = Depends(get_settings),
    body: SummaryRequest | None = None,
):
    """Family summary. Without a body (legacy callers) this stays offline; an
    explicit {"mode": "llm"} is required before any paid model call is made.

    Error mapping (plan §5): 502 upstream/validation, 504 timeout, 503 not
    configured, 409 identical content in flight, 429 busy or upstream rate
    limited (Retry-After forwarded only when the endpoint provided a usable
    value), 500 unrepresentable bounded input."""
    from spago_core.adapters.llm import LLMConfigProblem, OpenAICompatibleSummaryProvider, parse_endpoint
    from spago_core.services import ai as ai_svc

    mode = body.mode if body else "offline"
    llm_provider = None
    if mode == "llm":
        try:
            endpoint = parse_endpoint(settings)
        except LLMConfigProblem as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        llm_provider = OpenAICompatibleSummaryProvider(
            endpoint, client=getattr(request.app.state, "llm_client", None)
        )

    try:
        result = ai_svc.summarize_family(engine, family_id, mode=mode, llm_provider=llm_provider)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ai_svc.ContentInFlightError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.ProviderBusyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMConfigError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMUpstreamRateLimitError as exc:
        # Upstream throttling is reported as 429, with Retry-After only when the
        # endpoint supplied a usable value (LLM-07).
        headers = (
            {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc
    except ai_svc.LLMAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMTimeoutError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.SnapshotBudgetError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except ai_svc.LLMUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    # Response fields the old callers can ignore; model/cached/usage/coverage
    # are additive (plan §5).
    result["mode"] = mode
    return result


@router.post("/ai/plan", response_model=PlanQueryResponse)
def ai_plan(body: PlanQueryRequest):
    from spago_core.services import ai as ai_svc

    return PlanQueryResponse(**ai_svc.plan_query(body.query))


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


# --- projects (M1: save-to-project) --------------------------------------------------


class ProjectSummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str] = None
    item_count: int
    created_at: str


class ProjectItemResponse(BaseModel):
    id: uuid.UUID
    family_id: uuid.UUID
    family_key: str
    compound_id: Optional[uuid.UUID] = None
    inchikey: Optional[str] = None
    canonical_smiles: Optional[str] = None
    dataset_version: str
    added_at: str


class ProjectDetailResponse(ProjectSummaryResponse):
    items: list[ProjectItemResponse]


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class SaveScopeRequest(BaseModel):
    family_id: uuid.UUID
    # None/empty saves the whole family; otherwise the selected compound ids.
    compound_ids: Optional[list[uuid.UUID]] = None
    dataset_version: str = Field(min_length=1)


class SaveScopeResponse(BaseModel):
    created_rows: int
    already_present_rows: int
    scope_family: bool


@router.get("/projects", response_model=list[ProjectSummaryResponse])
def list_projects(engine=Depends(get_engine)):
    from spago_core.services import projects as projects_svc

    return projects_svc.list_projects(engine)


@router.post("/projects", response_model=ProjectSummaryResponse, status_code=201)
def create_project(body: CreateProjectRequest, engine=Depends(get_engine)):
    from spago_core.services import projects as projects_svc

    return projects_svc.create_project(engine, body.name, body.description)


@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
def get_project(project_id: uuid.UUID, engine=Depends(get_engine)):
    from spago_core.services import projects as projects_svc

    summary, items = projects_svc.get_project(engine, project_id)
    return ProjectDetailResponse(
        **summary.__dict__,
        items=[ProjectItemResponse(**i.__dict__) for i in items],
    )


@router.post("/projects/{project_id}/items", response_model=SaveScopeResponse)
def save_scope(project_id: uuid.UUID, body: SaveScopeRequest, engine=Depends(get_engine)):
    from spago_core.services import projects as projects_svc

    try:
        result = projects_svc.save_scope(
            engine, project_id, body.family_id, body.compound_ids, body.dataset_version
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SaveScopeResponse(**result.__dict__)


@router.delete("/projects/{project_id}/items/{item_id}", status_code=204)
def remove_item(project_id: uuid.UUID, item_id: uuid.UUID, engine=Depends(get_engine)):
    from spago_core.services import projects as projects_svc

    try:
        projects_svc.remove_item(engine, project_id, item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- export (M1: CSV / SDF with provenance) -------------------------------------------


class ExportRequest(BaseModel):
    family_id: uuid.UUID
    document_id: Optional[uuid.UUID] = None
    # Explicit selection wins over family/document scope.
    compound_ids: Optional[list[uuid.UUID]] = None
    format: str = Field(pattern="^(csv|sdf)$")


@router.post("/export")
def export_scope(body: ExportRequest, engine=Depends(get_engine)):
    """Export by server-side scope: 'current results' (family/document) or an
    explicit selection. Never silently only the loaded page."""
    from spago_core.services import export as export_svc

    try:
        rows = export_svc.collect_export_rows(
            engine,
            family_id=body.family_id,
            document_id=body.document_id,
            compound_ids=body.compound_ids,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if body.format == "csv":
        content = export_svc.render_csv(rows)
        media_type = "text/csv; charset=utf-8"
        filename = "spago-export.csv"
    else:
        content = export_svc.render_sdf(rows)
        media_type = "chemical/x-mdl-sdfile"
        filename = "spago-export.sdf"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
