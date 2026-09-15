"""Plan execution (ONLINE-02).

A validated plan becomes calls to the *same* deterministic services the manual
UI uses. Nothing here re-implements search, chemistry or evidence logic, and no
step may widen its own scope:

- structure search runs through `services.structure_search` (RDKit), never
  through the client;
- corpus reads go through `services`/`services.core`;
- summaries go through the scoped AI service;
- target discovery goes through the ONLINE-00 services with their own bounds.

Every executed step returns a typed, bounded result plus the status of the
underlying work, so a failed step is reported as failed rather than as an empty
success (AGENTS.md §22).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.domain import RetrievalStatus
from spago_core.services import NotFoundError
from spago_core.services import ai as ai_svc
from spago_core.services import discovery as discovery_svc
from spago_core.services import structure_search as ss
from spago_core.services.planner import (
    CompareEvidenceStep,
    OpenPatentStep,
    PlanStep,
    SearchPlan,
    StructureSearchStep,
    SummarizeStep,
    TargetDiscoveryStep,
    UnsupportedRequest,
    validate_plan,
)


@dataclass
class StepResult:
    op: str
    status: str  # ok | not_found | invalid | failed
    detail: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"op": self.op, "status": self.status, "detail": self.detail, "data": self.data}


@dataclass
class ExecutionResult:
    query: str
    producer: str
    steps: list[StepResult] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "producer": self.producer,
            "steps": [s.to_dict() for s in self.steps],
            "unresolved": list(self.unresolved),
        }


def execute_plan(
    engine: Engine,
    plan: SearchPlan | dict,
    *,
    documents_by_id: Optional[dict[uuid.UUID, uuid.UUID]] = None,
) -> ExecutionResult:
    """Execute a validated plan. Re-validates first, always.

    A plan arriving from a client is untrusted input: the same validation that
    ran at creation runs again here, so a hand-written body cannot introduce an
    operation or parameter that the allowlist forbids.
    """
    validated = validate_plan(plan)
    result = ExecutionResult(query=validated.query, producer=validated.producer)
    result.unresolved = list(validated.unresolved)

    for raw in validated.steps:
        try:
            step = validate_plan(
                {"query": validated.query, "producer": validated.producer, "steps": [raw]}
            ).typed_steps()[0]
        except UnsupportedRequest as exc:
            result.steps.append(StepResult(op=str(raw.get("op")), status="invalid", detail=exc.reason))
            continue
        result.steps.append(_execute_step(engine, step))
    return result


def _execute_step(engine: Engine, step: PlanStep) -> StepResult:
    if isinstance(step, OpenPatentStep):
        return _open_patent(engine, step)
    if isinstance(step, StructureSearchStep):
        return _structure_search(engine, step)
    if isinstance(step, SummarizeStep):
        return _summarize(engine, step)
    if isinstance(step, TargetDiscoveryStep):
        return _target_discovery(engine, step)
    if isinstance(step, CompareEvidenceStep):
        return _compare_evidence(engine, step)
    return StepResult(op="unknown", status="invalid", detail="Unsupported step.")


def _open_patent(engine: Engine, step: OpenPatentStep) -> StepResult:
    from spago_core.services import find_patent

    try:
        document, overview = find_patent(engine, step.publication_number)
    except NotFoundError as exc:
        return StepResult(
            op=step.op.value,
            status="not_found",
            detail=str(exc),
            data={"publication_number": step.publication_number},
        )
    return StepResult(
        op=step.op.value,
        status="ok",
        detail=f"Opened {document.publication_number} in family {overview.family.family_key}.",
        data={
            "publication_number": document.publication_number,
            "family_id": str(overview.family.id),
            "family_key": overview.family.family_key,
            "documents": len(overview.documents),
            "mention_counts": overview.mention_counts,
        },
    )


def _structure_search(engine: Engine, step: StructureSearchStep) -> StepResult:
    """Similarity/substructure/exact search, executed server-side by RDKit.

    The query structure is resolved server-side from a stored compound id: the
    plan never carries a structure the user did not select, and the browser
    cannot substitute one.
    """
    if step.family_id is None:
        return StepResult(
            op=step.op.value,
            status="invalid",
            detail="A structure search needs an open family; open one and retry.",
        )
    smiles = step.query_smiles
    if step.query_compound_id is not None:
        try:
            smiles = _compound_smiles(engine, step.query_compound_id)
        except NotFoundError as exc:
            return StepResult(op=step.op.value, status="not_found", detail=str(exc))
    assert smiles is not None

    try:
        result = ss.search_family_structures(
            engine,
            step.family_id,
            smiles,
            ss.SearchMode(step.mode),
            threshold=step.threshold if step.threshold is not None else ss.DEFAULT_SIMILARITY_THRESHOLD,
            offset=0,
            limit=step.limit,
        )
    except ss.StructureParseError as exc:
        return StepResult(op=step.op.value, status="invalid", detail=str(exc))
    except NotFoundError as exc:
        return StepResult(op=step.op.value, status="not_found", detail=str(exc))

    return StepResult(
        op=step.op.value,
        status="ok",
        detail=(
            f"{result.mode.value} search on {result.query_inchikey} returned {result.total} match(es)."
        ),
        data={
            "mode": result.mode.value,
            "family_id": str(step.family_id),
            "total": result.total,
            "limit": result.limit,
            "query_inchikey": result.query_inchikey,
            "query_canonical_smiles": result.query_canonical_smiles,
            "threshold": result.threshold,
            "matches": [
                {"compound_id": str(row["id"]), "inchikey": row["inchikey"]} for row in result.rows
            ],
        },
    )


def _compound_smiles(engine: Engine, compound_id: uuid.UUID) -> str:
    from spago_core.services import get_compound_smiles

    return get_compound_smiles(engine, compound_id)


def _summarize(engine: Engine, step: SummarizeStep) -> StepResult:
    """Route to the ONLINE-01 scoped summary. Offline mode only: a plan never
    triggers a paid model call by itself."""
    try:
        if step.op.value == "summarize_document":
            assert step.document_id is not None
            result = ai_svc.summarize_document(engine, step.document_id, mode="offline")
        else:
            assert step.family_id is not None
            result = ai_svc.summarize_family(engine, step.family_id, mode="offline")
    except (NotFoundError, ai_svc.AIError) as exc:
        return StepResult(op=step.op.value, status="failed", detail=str(exc))

    return StepResult(
        op=step.op.value,
        status="ok",
        detail=f"Generated a {result.get('scope', 'family')}-scope summary.",
        data={
            "analysis_id": str(result["analysis_id"]),
            "scope": result.get("scope", "family"),
            "provider": result["provider"],
            "provenance_state": result["provenance_state"],
            "text": result["text"],
            "citations": result["citations"],
            "cached": result["cached"],
        },
    )


def _target_discovery(engine: Engine, step: TargetDiscoveryStep) -> StepResult:
    from spago_core.services.discovery import TargetDiscoveryService
    from spago_core.services.targets import TargetResolutionService

    resolution = TargetResolutionService()
    try:
        existing = resolution.find_target(engine, step.target_query)
        if existing is not None:
            target = existing
            resolution_state = "resolved (reused stored scope)"
        else:
            outcome = resolution.resolve(engine, step.target_query, step.species)
            if outcome.target is None:
                return StepResult(
                    op=step.op.value,
                    status="not_found" if outcome.record.status == "not_found" else "failed",
                    detail=f"Target resolution was {outcome.record.status}.",
                    data={"resolution_status": outcome.record.status, "notes": outcome.record.notes},
                )
            target = outcome.target
            resolution_state = f"resolved ({outcome.record.status})"
    except Exception as exc:  # source outage must not look like an empty result
        return StepResult(
            op=step.op.value,
            status="failed",
            detail=f"Target resolution could not run: {type(exc).__name__}.",
        )

    discovery = TargetDiscoveryService()
    report = discovery.investigate(engine, target)
    total, candidates = discovery_svc.list_candidates(
        engine, target.id, include_all_modalities=step.include_interaction_evidence, limit=step.limit
    )
    return StepResult(
        op=step.op.value,
        status="ok",
        detail=f"{resolution_state}; {total} candidate(s) match the current filter.",
        data={
            "target_id": str(target.id),
            "target_key": target.target_key,
            "name": target.name,
            "uniprot_accession": target.uniprot_accession,
            "target_type": target.target_type.value if target.target_type else None,
            "resolution_status": resolution_state,
            "candidate_total": total,
            "candidates": [
                {
                    "compound_id": str(c.compound_id),
                    "inchikey": c.inchikey,
                    "modality": c.modality.value,
                    "evidence_class": c.evidence_class.value,
                    "patent_occurrences": c.patent_occurrences,
                }
                for c in candidates
            ],
            "sources": [
                {
                    "source_name": r.source_name,
                    "status": r.status.value,
                    "records_kept": r.records_kept,
                }
                for r in report.retrievals
            ],
            "coverage_note": (
                "A source that returned nothing, failed, or was not queried is reported as such. "
                "Missing records do not demonstrate that no inhibitors exist."
            ),
        },
    )


def _compare_evidence(engine: Engine, step: CompareEvidenceStep) -> StepResult:
    """Group measurements by evidence class so direct and indirect evidence can
    be compared without ranking heterogeneous assays."""
    from spago_core.services.targets import TargetResolutionService

    target_id = step.target_id
    if target_id is None:
        found = TargetResolutionService().find_target(engine, step.target_query or "")
        if found is None:
            return StepResult(
                op=step.op.value,
                status="not_found",
                detail=(
                    f"{step.target_query!r} is not a resolved target in this deployment; "
                    "run a target discovery for it first."
                ),
            )
        target_id = found.id

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT coalesce(m.evidence_class, 'unspecified') AS evidence_class,
                       count(*) AS n,
                       count(DISTINCT m.compound_id) AS compounds,
                       min(a.target_id::text) AS target_sample
                FROM investigation_measurements m
                JOIN assays a ON a.id = m.assay_id
                WHERE m.investigation_target_id = :tid
                GROUP BY 1 ORDER BY 2 DESC, 1
                """
            ),
            {"tid": target_id},
        ).mappings().all()

    groups = [
        {
            "evidence_class": r["evidence_class"],
            "measurements": int(r["n"]),
            "compounds": int(r["compounds"]),
        }
        for r in rows
    ]
    if not groups:
        return StepResult(
            op=step.op.value,
            status="ok",
            detail="No measurement is recorded for this target's candidates.",
            data={
                "target_id": str(target_id),
                "groups": [],
                "note": (
                    "No measurement is a coverage statement, not evidence that no inhibitor "
                    "exists."
                ),
            },
        )
    return StepResult(
        op=step.op.value,
        status="ok",
        detail=f"{len(groups)} evidence class(es) present across " + ", ".join(
            f"{g['measurements']} {g['evidence_class']}" for g in groups
        ),
        data={
            "target_id": str(target_id),
            "groups": groups,
            "note": (
                "Classes are shown as counted. Direct binding and functional or interaction "
                "readouts are different kinds of evidence and are deliberately not merged into "
                "one ranking."
            ),
        },
    )
