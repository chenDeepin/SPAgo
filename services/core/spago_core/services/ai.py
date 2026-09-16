"""Evidence-grounded AI services (M5 + LLM interface plan, 2026-09-14).

Facts and citations:
- Facts are collected with explicit scopes and DISTINCT granularity, bounded
  (max 50 items per kind, scaffold list capped, excerpts ≤1 KiB UTF-8), and
  addressed by typed fact refs ("family:{id}", "measurement:{id}",
  "evidence:{id}"). A measurement is a database record reference — it is never
  presented as patent-text evidence (LLM-01), and global ingestion-issue counts
  never enter a family summary (LLM-04).
- The final annotated snapshot is the artifact the budget applies to: the note
  and omission counters are written into it before the size check, whole
  optional items are dropped until it fits, and required metadata that cannot
  fit fails the request before any provider call (LLM-05).
- Caching is content-keyed: input_hash = SHA-256 over the canonical JSON of
  the input snapshot + family + mode/provider + model + sanitized endpoint
  fingerprint + prompt_version + output budget. The cache is checked before
  any provider call; only validated successes are persisted; on concurrent
  insert the database's winning row is returned (LLM-02).

Provenance: offline extractive output is machine_extracted; anything an LLM
produces is llm_inferred — never silently upgraded (AGENTS.md §10/§12).
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass

import enum

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.domain import ProvenanceState

# --- budgets (internal defaults; see plan §4) ---------------------------------

#: One prompt/schema version per summary scope, so a stored analysis can always
#: be traced to the input shape and instructions that produced it (ONLINE-01).
#: v6/v5/v5: the citation rule now says what a fact ref is and how aggregate
#: facts are cited (the input key is not a ref) — the dominant refusal class in
#: benchmarks/online01-llm-eval-2026-09-15.md. The version is part of the
#: analysis cache key, so no cached summary is served as if it came from the
#: new instruction.
#: v6 for target (run 4): the retrievals themselves now carry `source:<name>`
#: refs, so per-source status is cited rather than described against the target
#: root. Only that scope's instructions and input changed.
PROMPT_VERSION = "family-summary-v6"
DOCUMENT_PROMPT_VERSION = "document-summary-v5"
#: v7 (ONLINE-06): the target snapshot now carries a `reference` fact — the
#: deterministic potency verdict and the policy it was computed under — plus the
#: per-measurement class and the source-declared patent/DOI/PMID references. The
#: version is part of the analysis cache key, so no cached summary is served as
#: if it came from the new input.
#: v8 (ONLINE-07): the verdict fact also carries `supplement_remarks` — rows a
#: person added by hand without a public structure — so a summary of a thin set
#: cannot read as "nothing was recorded for this target".
TARGET_PROMPT_VERSION = "target-investigation-v8"
#: Map a provider failure onto the usage outcome vocabulary, so the accounting
#: records why budget was consumed rather than a generic failure.
def _usage_outcome(exc: AIError) -> str:
    if isinstance(exc, LLMAuthError):
        return "auth_failed"
    if isinstance(exc, LLMUpstreamRateLimitError):
        return "rate_limited"
    if isinstance(exc, LLMTimeoutError):
        return "timeout"
    if isinstance(exc, LLMOutputRejectedError):
        # The only upstream failure where an answer arrived and SPAgo refused
        # its content (and the only one that is re-sampled once). Everything
        # else that is not auth/rate-limit/timeout — an unreachable endpoint,
        # an HTTP status, an unreadable envelope — stays generic `failed`, so
        # the ledger does not claim content was reviewed when it never was.
        return "invalid_output"
    return "failed"


#: Roles that describe a distinct related member of the same ligand/receptor
#: system. Anything else on a target's component list is an annotation of the
#: entry itself, not a partner (ONLINE-00 A: keep components distinct).
RELATED_MEMBER_ROLES = ("ligand", "receptor", "signalling_component", "pathway")

PROMPT_VERSION_BY_SCOPE = {
    "family": PROMPT_VERSION,
    "document": DOCUMENT_PROMPT_VERSION,
    "target": TARGET_PROMPT_VERSION,
}


class SummaryScope(str, enum.Enum):
    """What a summary is about. Never inferred from the caller's intent.

    A family summary covers stored family facts; a document summary covers only
    that document; a target summary covers an open-database investigation with
    its per-source coverage. Labelling one as another is the failure mode this
    enum exists to prevent (ONLINE-01).
    """

    FAMILY = "family"
    DOCUMENT = "document"
    TARGET = "target"
MAX_FACT_ITEMS = 50  # per kind (measurements, evidence excerpts)
MAX_BODY_BYTES = 32 * 1024
MAX_EXCERPT_BYTES = 1024  # UTF-8 bytes, not characters
MAX_SCAFFOLDS = 20
#: Output budget per call. Live finding 2026-09-15: a complete summary answer
#: needed ~1.9k tokens for the demo family snapshot, so 1500 truncated the JSON
#: (`finish_reason == "length"`) and the adapter rightly failed the call. The
#: value is part of the cache key, so changing it cannot serve stale text.
MAX_OUTPUT_TOKENS = 4096
MAX_CONCURRENT_LLM_CALLS = 2
#: Provider calls allowed for one summary request: at most one re-sample after a
#: *content rejection of a completed response*, decided by the owner on
#: 2026-09-15 to lift the measured 85 % single-attempt compliance
#: (docs/archive/2026-09-15-llm-live-smoke.md §9). Every failure where the call may
#: not have been billed — timeout, throttle, auth, transport, protocol — stays
#: single-attempt, so this bound cannot multiply an unknown charge.
MAX_LLM_ATTEMPTS = 2
#: Schema limits shared by the instructions and the pydantic model, so the model
#: is told the same contract that validation enforces. Live finding 2026-09-15:
#: without the stated cap, 3/3 DeepSeek calls returned 6–9 limitation strings
#: and every summary was rejected (see docs/archive/2026-09-15-llm-live-smoke.md).
#: Live finding 2026-09-16 (hosted-acceptance rehearsal): a target-scope answer
#: legitimately carries more caveats than a family or document answer — empty
#: source, excluded records, screening-only source, evidence-class mix, bounded
#: selection, absence of corpus occurrences — and 6 such strings were refused
#: twice in a row against a cap of 5, turning a complete, billed answer into a
#: 502. The cap is now 8, the instructions state it (they interpolate this
#: constant), and the refusal names the bound it broke.
MAX_PARAGRAPHS = 12
MAX_LIMITATIONS = 8

#: The two bounded lists of the answer schema, as `field: (min, max)`. Kept next
#: to the caps so a refusal can say which bound broke (see `_bound_violation_detail`).
_BOUNDED_LISTS = {
    "paragraphs": (1, MAX_PARAGRAPHS),
    "limitations": (0, MAX_LIMITATIONS),
}

INPUT_NOTE = "Bounded fact selection: whole items only; omitted items are reported in coverage."

_NAMESPACE = uuid.UUID("9f0c3d1a-7e2b-4c8d-a1b2-3c4d5e6f7a8b")


class AIError(Exception):
    """Base for AI summary failures; subclasses map to HTTP status codes."""

    status_code = 502
    detail = "AI summary failed."

    #: What the provider billed for the calls this failure consumed, when the
    #: provider reported it. A completed-but-refused answer is billed like any
    #: other call, so the usage ledger records these tokens instead of leaving
    #: only the pre-call reservation (measured 2026-09-16: two refused target
    #: answers billed ~11k tokens each while the row kept 2k reserved tokens,
    #: which lets repeated refusals outrun the quota). None means unknown —
    #: a transport failure never reports usage — and keeps the reservation.
    usage: dict | None = None

    def __init__(self, message: str | None = None) -> None:
        # Instance messages (e.g. the specific validation failure) surface to
        # the client; the class default is the honest generic fallback.
        if message:
            self.detail = message
        super().__init__(self.detail)


class LLMConfigError(AIError):
    status_code = 503
    detail = "LLM summary is not available: the model endpoint is not configured or is invalid."


class ContentInFlightError(AIError):
    status_code = 409
    detail = "An identical summary is already being generated; reuse the running request."


class ProviderBusyError(AIError):
    status_code = 429
    detail = "The model caller is busy; try again shortly."


class LLMAuthError(AIError):
    status_code = 502
    detail = "The model endpoint rejected authentication."


class LLMUpstreamError(AIError):
    status_code = 502
    detail = "The model response failed validation."


class LLMTransportError(LLMUpstreamError):
    """The endpoint could not be reached or did not answer at the HTTP layer.

    Kept distinct from the failures that produced a response SPAgo could read,
    because the operator-facing outcome and the billing expectation differ:
    nothing was returned, so nothing was billed and there is no answer to
    re-sample. Measured 2026-09-16 during the H8 drill: a `ConnectError` was
    settled as `invalid_output`, which tells an operator the model's *content*
    was refused when the endpoint was never reached.
    """


class LLMOutputRejectedError(LLMUpstreamError):
    """The provider completed a response and SPAgo rejected its content.

    Kept distinct from the transport and protocol failures that share
    `LLMUpstreamError`, because it is the only case SPAgo re-samples: the
    response arrived, was read and was billed, so a second attempt cannot pay
    twice for an unknown outcome. A timeout, an upstream throttle, an auth
    failure, an unreadable HTTP body or a `tool_calls` violation are *not* this
    class and are never retried (AGENTS.md §16/§22).
    """


class LLMUpstreamRateLimitError(AIError):
    """Upstream 429, kept distinct from a generic upstream failure (LLM-07) so
    the API can answer 429 and forward a validated Retry-After header."""

    status_code = 429
    detail = "The model endpoint rate limited the request."

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            "The model endpoint rate limited the request."
            + (
                f" Retry-After: {retry_after}s."
                if retry_after is not None
                else " The endpoint did not provide a usable retry delay."
            )
        )


class SnapshotBudgetError(AIError):
    """Required family metadata alone exceeds the bounded input budget (LLM-05).
    Raised before any provider call, so nothing is generated or cached."""

    status_code = 500
    detail = "Family facts exceed the bounded model-input budget and cannot be trimmed to fit."


class LLMTimeoutError(AIError):
    status_code = 504
    detail = "The model endpoint did not answer in time."


# --- bounded fact collection (LLM-01 / LLM-04) --------------------------------


def _collect_family_facts(engine: Engine, family_id: uuid.UUID) -> dict:
    """Collect bounded, correctly scoped facts for one family.

    Granularity rules (LLM-04): documents/compounds/scaffolds counted with
    DISTINCT compound granularity; measurements identified by measurement.id;
    dataset versions reported per version (mixed → "mixed"); global ingestion
    issues are excluded from family conclusions. All counting happens in SQL;
    item lists are selected with stable ORDER BY and LIMIT.
    """
    from spago_core.services import get_family_overview

    overview = get_family_overview(engine, family_id)  # raises NotFoundError
    family_ref = f"family:{family_id}"

    with engine.connect() as conn:
        compound_count = conn.execute(
            text(
                """
                SELECT count(DISTINCT c.id)
                FROM compounds c
                JOIN current_compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid
                """
            ),
            {"fid": family_id},
        ).scalar_one()

        scaffolds_total = conn.execute(
            text(
                """
                SELECT count(DISTINCT c.scaffold)
                FROM compounds c
                JOIN current_compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid AND c.scaffold IS NOT NULL
                """
            ),
            {"fid": family_id},
        ).scalar_one()
        scaffolds = conn.execute(
            text(
                """
                SELECT c.scaffold, count(DISTINCT c.id) AS n
                FROM compounds c
                JOIN current_compound_mentions m ON m.compound_id = c.id
                JOIN patent_documents d ON d.id = m.document_id
                WHERE d.family_id = :fid AND c.scaffold IS NOT NULL
                GROUP BY c.scaffold ORDER BY n DESC, c.scaffold
                LIMIT :limit
                """
            ),
            {"fid": family_id, "limit": MAX_SCAFFOLDS},
        ).all()

        measurement_total = conn.execute(
            text(
                """
                SELECT count(DISTINCT mm.id)
                FROM current_measurements mm
                JOIN current_compound_mentions cm ON cm.compound_id = mm.compound_id
                JOIN patent_documents d ON d.id = cm.document_id
                WHERE d.family_id = :fid
                """
            ),
            {"fid": family_id},
        ).scalar_one()
        measurement_rows = conn.execute(
            text(
                """
                SELECT mm.id, mm.compound_id, mm.standard_type, mm.relation, mm.value, mm.unit,
                       mm.source_name, mm.dataset_version, mm.provenance_state,
                       a.assay_key, a.assay_type, t.name AS target_name,
                       c.inchikey
                FROM current_measurements mm
                JOIN compounds c ON c.id = mm.compound_id
                JOIN assays a ON a.id = mm.assay_id
                JOIN targets t ON t.id = a.target_id
                WHERE mm.id IN (
                    SELECT DISTINCT mm2.id
                    FROM current_measurements mm2
                    JOIN current_compound_mentions cm ON cm.compound_id = mm2.compound_id
                    JOIN patent_documents d ON d.id = cm.document_id
                    WHERE d.family_id = :fid
                )
                ORDER BY mm.id
                LIMIT :limit
                """
            ),
            {"fid": family_id, "limit": MAX_FACT_ITEMS},
        ).mappings().all()

        evidence_total = conn.execute(
            text(
                """
                SELECT count(DISTINCT e.id)
                FROM current_evidence_records e
                JOIN patent_documents d ON d.id = e.document_id
                WHERE d.family_id = :fid
                """
            ),
            {"fid": family_id},
        ).scalar_one()
        evidence_rows = conn.execute(
            text(
                """
                SELECT e.id, e.source_type, e.section, e.page, e.raw_excerpt,
                       d.publication_number, cm.compound_id
                FROM current_evidence_records e
                JOIN patent_documents d ON d.id = e.document_id
                LEFT JOIN current_compound_mentions cm ON cm.id = e.compound_mention_id
                WHERE d.family_id = :fid
                ORDER BY e.id
                LIMIT :limit
                """
            ),
            {"fid": family_id, "limit": MAX_FACT_ITEMS},
        ).mappings().all()

        coverage_rows = conn.execute(
            text(
                """
                SELECT d.dataset_version,
                       count(DISTINCT d.id) AS documents,
                       count(DISTINCT cm.compound_id) AS compounds,
                       count(DISTINCT mm.id) AS measurements,
                       di.synthetic AS synthetic
                FROM patent_documents d
                LEFT JOIN current_compound_mentions cm ON cm.document_id = d.id
                LEFT JOIN current_measurements mm ON mm.compound_id = cm.compound_id
                LEFT JOIN dataset_info di
                       ON di.dataset_version = d.dataset_version
                      AND di.source_name = d.source_name
                WHERE d.family_id = :fid
                GROUP BY d.dataset_version, di.synthetic
                ORDER BY d.dataset_version
                """
            ),
            {"fid": family_id},
        ).mappings().all()

    measurements = [
        {
            "ref": f"measurement:{r['id']}",
            "compound_id": str(r["compound_id"]),
            "inchikey": r["inchikey"],
            "standard_type": r["standard_type"],
            "relation": r["relation"],
            "value": float(r["value"]),
            "unit": r["unit"],
            "assay_key": r["assay_key"],
            "assay_type": r["assay_type"],
            "target_name": r["target_name"],
            "source_name": r["source_name"],
            "dataset_version": r["dataset_version"],
            "provenance_state": r["provenance_state"],
        }
        for r in measurement_rows
    ]
    evidence = [
        {
            "ref": f"evidence:{r['id']}",
            "evidence_id": str(r["id"]),
            # The owning compound, when the evidence is tied to a live mention:
            # a retracted mention keeps the evidence with no compound_id rather
            # than pointing at an occurrence that is no longer current.
            "compound_id": str(r["compound_id"]) if r["compound_id"] else None,
            "publication_number": r["publication_number"],
            "source_type": r["source_type"],
            "section": r["section"],
            "page": r["page"],
            "excerpt": r["raw_excerpt"] or None,
        }
        for r in evidence_rows
    ]
    coverage = [
        {
            "dataset_version": r["dataset_version"],
            "synthetic": bool(r["synthetic"]) if r["synthetic"] is not None else None,
            "documents": int(r["documents"]),
            "compounds": int(r["compounds"]),
            "measurements": int(r["measurements"]),
        }
        for r in coverage_rows
    ]
    versions = [c["dataset_version"] for c in coverage]
    dataset_version = versions[0] if len(versions) == 1 else ("mixed" if len(versions) > 1 else "unknown")

    return {
        "family": {"ref": family_ref, "id": str(family_id), "family_key": overview.family.family_key},
        "document_count": len(overview.documents),
        "compound_count": int(compound_count),
        "scaffolds": [{"scaffold": r[0], "compounds": int(r[1])} for r in scaffolds],
        "scaffold_total": int(scaffolds_total),
        "measurements": measurements,
        "measurement_total": int(measurement_total),
        "evidence": evidence,
        "evidence_total": int(evidence_total),
        "coverage": coverage,
        "dataset_version": dataset_version,
    }


def _collect_document_facts(engine: Engine, document_id: uuid.UUID) -> dict:
    """Bounded facts for exactly one patent document (ONLINE-01).

    Scope is enforced in every query: compounds, measurements and evidence come
    only from this document, so a document summary can never quote a sibling
    document's facts. Absence of a stored abstract or claims text is recorded as
    a gap, never as a scientific conclusion.
    """
    with engine.connect() as conn:
        doc = conn.execute(
            text(
                """
                SELECT id, publication_number, title, abstract, assignee,
                       publication_date, jurisdiction, doc_type, family_id,
                       dataset_version, source_name
                FROM patent_documents WHERE id = :did
                """
            ),
            {"did": document_id},
        ).mappings().first()
        if doc is None:
            from spago_core.services import NotFoundError

            raise NotFoundError(f"Document {document_id} not found")

        family = conn.execute(
            text("SELECT family_key, title FROM patent_families WHERE id = :fid"),
            {"fid": doc["family_id"]},
        ).mappings().first()

        compound_count = conn.execute(
            text(
                "SELECT count(DISTINCT compound_id) FROM current_compound_mentions WHERE document_id = :did"
            ),
            {"did": document_id},
        ).scalar_one()
        scaffolds = conn.execute(
            text(
                """
                SELECT c.scaffold, count(DISTINCT c.id) AS n
                FROM compounds c
                JOIN current_compound_mentions m ON m.compound_id = c.id
                WHERE m.document_id = :did AND c.scaffold IS NOT NULL
                GROUP BY c.scaffold ORDER BY n DESC, c.scaffold
                LIMIT :limit
                """
            ),
            {"did": document_id, "limit": MAX_SCAFFOLDS},
        ).all()
        scaffold_total = conn.execute(
            text(
                """
                SELECT count(DISTINCT c.scaffold)
                FROM compounds c
                JOIN current_compound_mentions m ON m.compound_id = c.id
                WHERE m.document_id = :did AND c.scaffold IS NOT NULL
                """
            ),
            {"did": document_id},
        ).scalar_one()

        measurement_total = conn.execute(
            text(
                """
                SELECT count(DISTINCT mm.id)
                FROM current_measurements mm
                JOIN current_compound_mentions cm ON cm.compound_id = mm.compound_id
                WHERE cm.document_id = :did
                """
            ),
            {"did": document_id},
        ).scalar_one()
        measurement_rows = conn.execute(
            text(
                """
                SELECT mm.id, mm.compound_id, mm.standard_type, mm.relation, mm.value, mm.unit,
                       mm.source_name, mm.evidence_class, coalesce(mm.evidence_class,'unspecified') AS cls,
                       a.assay_key, a.assay_type, t.name AS target_name, c.inchikey
                FROM current_measurements mm
                JOIN compounds c ON c.id = mm.compound_id
                JOIN assays a ON a.id = mm.assay_id
                JOIN targets t ON t.id = a.target_id
                WHERE mm.compound_id IN (
                    SELECT DISTINCT compound_id FROM current_compound_mentions WHERE document_id = :did
                )
                ORDER BY mm.id LIMIT :limit
                """
            ),
            {"did": document_id, "limit": MAX_FACT_ITEMS},
        ).mappings().all()

        evidence_total = conn.execute(
            text("SELECT count(*) FROM current_evidence_records WHERE document_id = :did"),
            {"did": document_id},
        ).scalar_one()
        evidence_rows = conn.execute(
            text(
                """
                SELECT e.id, e.source_type, e.section, e.page, e.raw_excerpt,
                       e.provenance_state, e.source_url, cm.compound_id
                FROM current_evidence_records e
                LEFT JOIN current_compound_mentions cm ON cm.id = e.compound_mention_id
                WHERE e.document_id = :did
                ORDER BY e.id LIMIT :limit
                """
            ),
            {"did": document_id, "limit": MAX_FACT_ITEMS},
        ).mappings().all()

        # Claim text is not stored in this deployment. Only a claim-typed
        # evidence record counts as an assessed claim: an abstract or a
        # description excerpt is not a claim, and treating it as one would let
        # the summary claim to have assessed claim scope.
        claim_count = conn.execute(
            text(
                "SELECT count(*) FROM current_evidence_records "
                "WHERE document_id = :did AND source_type = 'claim'"
            ),
            {"did": document_id},
        ).scalar_one()

    evidence_types = sorted({r["source_type"] for r in evidence_rows})
    return {
        "document": {
            "ref": f"document:{document_id}",
            "id": str(document_id),
            "publication_number": doc["publication_number"],
            "title": doc["title"],
            "has_abstract": bool(doc["abstract"]),
            "assignee": doc["assignee"],
            "publication_date": str(doc["publication_date"]) if doc["publication_date"] else None,
            "jurisdiction": doc["jurisdiction"],
            "doc_type": doc["doc_type"],
            "family_key": family["family_key"] if family else None,
            "family_ref": f"family:{doc['family_id']}",
        },
        "compound_count": int(compound_count),
        "scaffolds": [{"scaffold": r[0], "compounds": int(r[1])} for r in scaffolds],
        "scaffold_total": int(scaffold_total),
        "measurements": [
            {
                "ref": f"measurement:{r['id']}",
                "compound_id": str(r["compound_id"]),
                "inchikey": r["inchikey"],
                "standard_type": r["standard_type"],
                "relation": r["relation"],
                "value": float(r["value"]),
                "unit": r["unit"],
                "assay_key": r["assay_key"],
                "assay_type": r["assay_type"],
                "target_name": r["target_name"],
                "evidence_class": r["cls"],
                "source_name": r["source_name"],
            }
            for r in measurement_rows
        ],
        "measurement_total": int(measurement_total),
        "evidence": [
            {
                "ref": f"evidence:{r['id']}",
                "evidence_id": str(r["id"]),
                "compound_id": str(r["compound_id"]) if r["compound_id"] else None,
                "publication_number": doc["publication_number"],
                "source_type": r["source_type"],
                "section": r["section"],
                "page": r["page"],
                "excerpt": r["raw_excerpt"] or None,
                "provenance_state": r["provenance_state"],
                "source_url": r["source_url"],
            }
            for r in evidence_rows
        ],
        "evidence_total": int(evidence_total),
        "evidence_source_types": evidence_types,
        "claims_assessed": bool(claim_count),
        "coverage": [
            {
                "dataset_version": doc["dataset_version"],
                "synthetic": None,
                "documents": 1,
                "compounds": int(compound_count),
                "measurements": int(measurement_total),
            }
        ],
        "dataset_version": doc["dataset_version"],
        "source_name": doc["source_name"],
    }


def _collect_target_facts(
    engine: Engine, target_id: uuid.UUID, include_all_modalities: bool = False
) -> dict:
    """Bounded facts for one target investigation (ONLINE-01).

    The per-source coverage travels with the facts so a summary can state what
    was retrieved, what failed and what was not queried. That distinction is the
    difference between "no small molecule was found" and "no inhibitor exists",
    and the summary must never make the second claim.

    ONLINE-06 adds the potency verdict as its own citable fact: it is a
    deterministic count under a policy that travels in the snapshot, so a
    summary can report "none of N in-scope compounds is at or below 10 µM"
    without inventing a comparison and without presenting a count as a finding
    about the literature.
    """
    from spago_core.config import get_settings
    from spago_core.services import discovery as discovery_svc
    from spago_core.services import reference as reference_svc
    from spago_core.services.targets import TargetResolutionService

    service = TargetResolutionService()
    target = service.get_target(engine, target_id)
    policy = reference_svc.policy_from_settings(
        get_settings(), include_all_modalities=include_all_modalities
    )
    verdict = reference_svc.reference_verdict(engine, target, policy)

    with engine.connect() as conn:
        retrievals = conn.execute(
            text(
                """
                SELECT source_name, status, query, dataset_version, source_version,
                       records_seen, records_kept, records_excluded, rejection_counts,
                       warnings, retrieved_at
                FROM source_retrievals WHERE target_id = :tid ORDER BY source_name
                """
            ),
            {"tid": target_id},
        ).mappings().all()
        breakdown = discovery_svc.modality_breakdown(engine, target_id)
        candidate_total, candidates = discovery_svc.list_candidates(
            engine,
            target_id,
            include_all_modalities=include_all_modalities,
            limit=MAX_FACT_ITEMS,
        )
        measurement_rows = discovery_svc.list_target_measurements(
            engine, target_id, limit=MAX_FACT_ITEMS
        )
        measurement_total = conn.execute(
            text(
                """
                SELECT count(*)
                FROM investigation_measurements m
                WHERE m.investigation_target_id = :tid
                """
            ),
            {"tid": target_id},
        ).scalar_one()
        evidence_class_rows = conn.execute(
            text(
                """
                SELECT coalesce(m.evidence_class, 'unspecified') AS cls, count(*) AS n
                FROM investigation_measurements m
                WHERE m.investigation_target_id = :tid
                GROUP BY 1 ORDER BY 2 DESC, 1
                """
            ),
            {"tid": target_id},
        ).all()
        patent_linked = conn.execute(
            text(
                """
                SELECT count(DISTINCT tc.compound_id)
                FROM target_candidates tc
                WHERE tc.target_id = :tid
                  AND EXISTS (SELECT 1 FROM current_compound_mentions cm WHERE cm.compound_id = tc.compound_id)
                """
            ),
            {"tid": target_id},
        ).scalar_one()

    # Counts over ALL measurements (these are what a summary may cite as totals);
    # the listed measurements are only a bounded sample and are labelled as such.
    evidence_classes = {row[0]: int(row[1]) for row in evidence_class_rows}

    return {
        "target": {
            "ref": f"target:{target_id}",
            "id": str(target_id),
            "target_key": target.target_key,
            "name": target.name,
            "organism": target.organism,
            "uniprot_accession": target.uniprot_accession,
            "gene_symbol": target.gene_symbol,
            "target_type": target.target_type.value if target.target_type else None,
            "scope_kind": target.scope_kind.value if target.scope_kind else None,
            # Only reviewed ligand/receptor/signalling membership is presented as
            # a related member. UniProt "contains" entries and ComplexPortal
            # cross-references are structural annotations of the entry itself;
            # listing them as partners would invent relationships.
            "components": [
                {"gene_symbol": c.gene_symbol, "role": c.role, "accession": c.accession}
                for c in target.components
                if c.role in RELATED_MEMBER_ROLES and (c.gene_symbol or c.accession)
            ],
            "structural_annotations": [
                {"name": c.name, "role": c.role, "accession": c.accession}
                for c in target.components
                if c.role not in RELATED_MEMBER_ROLES
            ],
        },
        "sources": [
            {
                # A retrieval is a citable fact in its own right: its status,
                # counts, exclusions and dataset version are statements the
                # summary makes. Without a ref here the model had to invent one
                # and cited the version string or the key name, so every target
                # summary that mentioned coverage risked refusal (ONLINE-01
                # evaluation, benchmarks/online01-llm-eval-2026-09-15.md).
                # The retrieval's identity is the source, not the version: a
                # failed source with no version still has a ref.
                "ref": f"source:{r['source_name']}",
                "source_name": r["source_name"],
                "status": r["status"],
                "records_seen": r["records_seen"],
                "records_kept": r["records_kept"],
                "records_excluded": r["records_excluded"],
                "rejection_counts": _as_json(r["rejection_counts"]) or {},
                "dataset_version": r["dataset_version"],
                "source_version": r["source_version"],
                "retrieved_at": r["retrieved_at"].isoformat(),
                "warnings": list(_as_json(r["warnings"]) or []),
            }
            for r in retrievals
        ],
        "modality_breakdown": breakdown,
        # The verdict is a citable fact in its own right: every number a summary
        # may repeat about potency comes from here, and the policy it was
        # computed under is part of the fact.
        "reference": {
            "ref": f"reference:{target_id}",
            "qualifies": verdict.qualifies,
            "reason": verdict.reason,
            "policy_version": verdict.policy.version,
            "threshold_nM": verdict.policy.threshold_nm,
            "threshold_label": verdict.policy.threshold_label,
            "min_compounds": verdict.policy.min_compounds,
            "modality_scope": verdict.policy.modality_scope,
            "compounds": verdict.compounds,
            "compounds_active": verdict.compounds_active,
            "compounds_weak": verdict.compounds_weak,
            "compounds_unknown": verdict.compounds_unknown,
            "compounds_not_applicable": verdict.compounds_not_applicable,
            "active_compounds_outside_scope": verdict.active_compounds_outside_scope,
            "measurements": verdict.measurements,
            "class_counts": verdict.class_counts,
            "endpoint_counts": verdict.endpoint_counts,
            "evidence_class_counts": verdict.evidence_class_counts,
            "potential_duplicates": verdict.potential_duplicates,
            "records_without_structure": verdict.records_without_structure,
            # ONLINE-07: rows a person added by hand without a public structure. Part
            # of the verdict, so a summary of a thin set cannot omit them and read as
            # "nothing was recorded for this target".
            "supplement_remarks": verdict.supplement_remarks,
            "source_declared_patents": verdict.source_declared_patents,
            "best_active": (
                {
                    "inchikey": verdict.best_active.inchikey,
                    "potency_label": verdict.best_active.potency_label,
                    "evidence_class": verdict.best_active.evidence_class.value,
                    "source_name": verdict.best_active.source_name,
                }
                if verdict.best_active
                else None
            ),
            "note": (
                "Deterministic count, not a biological conclusion: it says which stored "
                "records are at or below the stated threshold, and it never implies that "
                "no other inhibitor exists."
            ),
        },
        "candidate_total": int(candidate_total),
        "candidates": [
            {
                "ref": f"candidate:{c.compound_id}",
                "compound_id": str(c.compound_id),
                "inchikey": c.inchikey,
                "molecular_formula": c.molecular_formula,
                "molecular_weight": c.molecular_weight,
                "modality": c.modality.value,
                "modality_rule": c.modality_rule,
                "evidence_class": c.evidence_class.value,
                "source_name": c.source_name,
                "measurements": c.measurements,
                "patent_occurrences": c.patent_occurrences,
                "activity_class": c.activity_class.value,
                "potency_label": c.potency_label,
                "source_declared_patents": c.source_declared_patents,
            }
            for c in candidates
        ],
        "candidates_shown": len(candidates),
        "patent_linked_candidates": int(patent_linked),
        "measurements": [
            {
                "ref": f"measurement:{m['id']}",
                "measurement_id": str(m["id"]),
                "compound_id": str(m["compound_id"]),
                "inchikey": m["inchikey"],
                "standard_type": m["standard_type"],
                "relation": m["relation"],
                "value": m["value"],
                "unit": m["unit"],
                "evidence_class": m["evidence_class"],
                "assay_key": m["assay_key"],
                "assay_type": m["assay_type"],
                "target_name": m["target_name"],
                "target_key": m["target_key"],
                "species": m["species"],
                "potential_duplicate": m["potential_duplicate"],
                "source_name": m["source_name"],
                "source_url": m["source_url"],
                "activity_class": m["activity_class"],
                "document_patent_number": m["document_patent_number"],
                "document_doi": m["document_doi"],
                "document_pmid": m["document_pmid"],
            }
            for m in measurement_rows
        ],
        "measurement_total": int(measurement_total),
        "evidence_class_counts": evidence_classes,
        "measurements_listed": len(measurement_rows),
        "coverage": [
            # Same ref as the matching `sources` row: this projection of the
            # retrieval is where the model read the version string it cited as a
            # ref, so both places must advertise the one legal citation.
            {"ref": f"source:{r['source_name']}", "source_name": r["source_name"],
             "dataset_version": r["dataset_version"], "synthetic": None, "documents": 0,
             "compounds": r["records_kept"], "measurements": 0}
            for r in retrievals
            if r["dataset_version"]
        ],
        "dataset_version": target.dataset_version,
        "source_name": target.source_name,
        "default_candidate_filter": (
            "all modalities" if include_all_modalities else "small molecules and unclassified entities"
        ),
    }


def collect_facts(
    engine: Engine,
    scope: str,
    scope_id: uuid.UUID,
    include_all_modalities: bool = False,
) -> dict:
    """Dispatch to the collector for the requested scope."""
    if scope == SummaryScope.FAMILY.value:
        return _collect_family_facts(engine, scope_id)
    if scope == SummaryScope.DOCUMENT.value:
        return _collect_document_facts(engine, scope_id)
    if scope == SummaryScope.TARGET.value:
        return _collect_target_facts(engine, scope_id, include_all_modalities)
    raise AIError(f"Unknown summary scope {scope!r}.")


def _truncate_utf8(value: str, max_bytes: int) -> tuple[str, bool]:
    """Trim to a UTF-8 byte budget without splitting a character (LLM-05).
    A 1024-character slice is not a 1024-byte bound for non-ASCII excerpts."""
    raw = value.encode("utf-8")
    if len(raw) <= max_bytes:
        return value, False
    return raw[:max_bytes].decode("utf-8", errors="ignore"), True


def _truncate_excerpts(snapshot: dict, delta: dict) -> None:
    """Byte-bound every excerpt and mark the ones that were shortened, so a
    trimmed excerpt is never silently presented as the whole source text."""
    for item in snapshot.get("evidence") or []:
        excerpt = item.get("excerpt")
        if not excerpt:
            continue
        bounded, was_truncated = _truncate_utf8(excerpt, MAX_EXCERPT_BYTES)
        if was_truncated:
            item["excerpt"] = bounded
            item["excerpt_truncated"] = True
            delta["truncated_excerpts"] += 1


def _snapshot_bytes(snapshot: dict) -> int:
    return len(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _annotate_snapshot(snapshot: dict, delta: dict) -> None:
    """Write the bounded-selection note and omission counters into the snapshot
    itself, so the budget check covers exactly what would be sent."""
    snapshot["input_note"] = INPUT_NOTE
    for key, count in (
        ("measurement_omitted", delta["omitted_measurements"]),
        ("evidence_omitted", delta["omitted_evidence"]),
        ("scaffold_omitted", delta["omitted_scaffolds"]),
        ("candidate_omitted", delta["omitted_candidates"]),
        ("excerpt_truncated", delta["truncated_excerpts"]),
    ):
        if count:
            snapshot[key] = count
        else:
            snapshot.pop(key, None)


def _drop_optional_item(snapshot: dict, delta: dict) -> bool:
    """Remove one whole item (never mid-JSON, never mid-value) from the largest
    optional list, so trimming stays balanced across kinds and normally sheds
    the fewest possible items. False when nothing optional is left, which the
    caller reports as an unrepresentable input."""
    best: tuple[str, int, str] | None = None
    for key, counter in (
        ("measurements", "omitted_measurements"),
        ("evidence", "omitted_evidence"),
        ("scaffolds", "omitted_scaffolds"),
        ("candidates", "omitted_candidates"),
    ):
        items = snapshot.get(key) or []
        if not items:
            continue
        size = len(json.dumps(items, ensure_ascii=False).encode("utf-8"))
        if best is None or size > best[1]:
            best = (key, size, counter)
    if best is None:
        return False
    snapshot[best[0]].pop()
    delta[best[2]] += 1
    return True


def finalize_snapshot(facts: dict) -> tuple[dict, dict]:
    """Annotate, bound and re-verify the model input snapshot (LLM-05).

    Excerpts are byte-bounded first, then the budget is checked on the
    *annotated* body, so the note and the omission counters cannot push a
    trimmed snapshot back over the limit. Only whole optional items are
    dropped, and the reported counts travel inside the snapshot. Raises
    SnapshotBudgetError when the required metadata alone cannot fit, so no
    provider call and no success cache entry follow."""
    snapshot = facts
    scaffolds = snapshot.get("scaffolds") or []
    delta = {
        "included": True,
        "omitted_measurements": 0,
        "omitted_evidence": 0,
        # The totals stay in the snapshot: they are the denominator a reader
        # needs to know what was omitted, and dropping them made the summarizer
        # report a partially-listed set as if it were complete.
        "omitted_scaffolds": max(0, int(snapshot.get("scaffold_total") or 0) - len(scaffolds)),
        "omitted_candidates": max(
            0,
            int(snapshot.get("candidate_total") or 0) - len(snapshot.get("candidates") or []),
        ),
        "truncated_excerpts": 0,
        "truncated": False,
    }
    _truncate_excerpts(snapshot, delta)
    _annotate_snapshot(snapshot, delta)
    while _snapshot_bytes(snapshot) > MAX_BODY_BYTES:
        if not _drop_optional_item(snapshot, delta):
            raise SnapshotBudgetError(
                "Required family metadata alone exceeds the bounded model-input budget "
                f"({MAX_BODY_BYTES} bytes)."
            )
        _annotate_snapshot(snapshot, delta)
    delta["truncated"] = bool(
        delta["omitted_measurements"]
        or delta["omitted_evidence"]
        or delta["omitted_scaffolds"]
        or delta["truncated_excerpts"]
    )
    delta["included"] = not delta["truncated"]
    return snapshot, delta


def build_summary_snapshot(
    engine: Engine, scope: str, scope_id: uuid.UUID, include_all_modalities: bool = False
) -> dict:
    """The exact provider input for a scope, in the shipped order (ONLINE-01).

    `collect_facts` → target coverage note → `finalize_snapshot` → `summary_scope`.
    One owner on purpose: the summary path and any re-measurement of it (the
    evaluation runner in `scripts/llm_summary_eval.py`) must send the same
    payload, or the numbers describe a request the product never makes.
    """
    facts = collect_facts(engine, scope, scope_id, include_all_modalities)
    if scope == SummaryScope.TARGET.value:
        # Absence of records is not evidence of absence; the per-source status
        # block is the whole basis of a target summary.
        facts["coverage_note"] = (
            "Missing records do not demonstrate that no inhibitors exist; the per-source status "
            "above is the entire basis of this summary."
        )
    snapshot, _bounding = finalize_snapshot(facts)
    snapshot["summary_scope"] = scope
    return snapshot


def allowed_refs(snapshot: dict) -> set[str]:
    """Every fact reference the model is allowed to cite.

    Built from the snapshot actually sent, so a citation outside the supplied
    scope is rejected rather than stored (ONLINE-01).

    The walk is generic over the snapshot on purpose (defect D9). This function
    used to enumerate `family`, `document`, `target` and five item lists, which
    silently omitted the `reference` node — the ONLINE-06 potency verdict — while
    the target prompt tells the model to "cite `reference:<id>` for any statement
    about potency or about the set being usable or not". A summary that obeyed
    its instructions was refused as citing an unknown ref; the recorded sparse-
    scope run refused 4 of 4 attempts that way
    (`benchmarks/online01-llm-eval-2026-09-16-sparse.md`). The rule is now the one
    the prompt states: any `ref` / `family_ref` inside the input is a fact the
    model may cite. Nothing else can drift out of a second list.
    """
    refs: set[str] = set()

    def visit(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("ref", "family_ref"):
                    if isinstance(value, str) and value:
                        refs.add(value)
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(snapshot)
    return refs


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_input_hash(
    snapshot: dict,
    *,
    scope: str = SummaryScope.FAMILY.value,
    mode: str,
    provider_name: str,
    model: str | None,
    endpoint_fingerprint: str | None,
    thinking_disabled: bool | None = None,
    json_mode: bool | None = None,
) -> str:
    """Content key: scope kind + exact input snapshot + mode/provider + model +
    sanitized endpoint fingerprint + prompt_version + output budget + request
    shape.

    The scope is part of the key, so a family summary can never be served as a
    document summary of the same data (ONLINE-01: cache by authorized data
    scope). The request shape is part of it because a summary produced with the
    provider's hidden reasoning enabled is not the same analysis as one produced
    without it.
    """
    return _canonical_hash(
        {
            "kind": f"{scope}_summary",
            "prompt_version": PROMPT_VERSION_BY_SCOPE.get(scope, PROMPT_VERSION),
            "mode": mode,
            "provider": provider_name,
            "model": model,
            "endpoint_fingerprint": endpoint_fingerprint,
            "output_budget": {"max_tokens": MAX_OUTPUT_TOKENS},
            "thinking_disabled": thinking_disabled,
            "json_mode": json_mode,
            "input_snapshot": snapshot,
        }
    )


# --- providers ------------------------------------------------------------------


class SummaryProvider:
    """Protocol: render/produce summary text for a bounded input snapshot."""

    name = "provider"
    provenance_state = ProvenanceState.LLM_INFERRED
    model: str | None = None
    usage: dict | None = None

    def summarize(self, snapshot: dict) -> str:
        raise NotImplementedError


class OfflineExtractiveProvider(SummaryProvider):
    """Assembles a deterministic summary from typed DB facts. No LLM."""

    name = "offline-extractive"
    provenance_state = ProvenanceState.MACHINE_EXTRACTED
    interpretation = (
        "Interpretation (SAR narrative, claim scope discussion) requires an LLM "
        "provider, which is not configured on this deployment. Everything above is "
        "assembled verbatim from stored records."
    )

    def summarize(self, snapshot: dict) -> str:
        lines: list[str] = []
        family = snapshot["family"]
        coverage = snapshot["coverage"]
        versions = ", ".join(
            f"{c['dataset_version']}{' (synthetic)' if c['synthetic'] else ''}"
            for c in coverage
        )
        lines.append(
            f"Family {family['family_key']} contains {snapshot['document_count']} document(s) "
            f"with {snapshot['compound_count']} deduplicated compound(s) "
            f"(dataset version(s): {versions or 'unknown'})."
        )
        if snapshot.get("scaffolds"):
            top = ", ".join(
                f"{s['scaffold']} ({s['compounds']})" for s in snapshot["scaffolds"][:5]
            )
            lines.append(f"Murcko scaffolds present: {top}.")
        if snapshot.get("scaffold_omitted"):
            lines.append(
                f"{snapshot['scaffold_omitted']} further distinct scaffold(s) were not included "
                "in this bounded summary."
            )
        total = snapshot.get("measurement_total", 0)
        if snapshot.get("measurements"):
            omitted = total - len(snapshot["measurements"])
            scope = f"{total} typed measurement(s) exist" + (
                f"; the first {len(snapshot['measurements'])} are listed" if omitted > 0 else ""
            )
            lines.append(
                f"{scope}. Values are listed per assay and are not ranked or "
                "combined into selectivity numbers:"
            )
            for m in (snapshot.get("measurements") or [])[:12]:
                lines.append(
                    f"- {m['inchikey']} {m['standard_type']} {m['relation']} {m['value']:g} "
                    f"{m['unit']} in {m['assay_key']} (measurement record {m['ref'].split(':', 1)[1]})."
                )
        else:
            lines.append(
                f"{total} typed measurement(s) exist but were omitted from this bounded summary."
                if total
                else "No typed measurements exist for these compounds; absence of a "
                "measurement is not evidence of inactivity."
            )
        if snapshot.get("evidence_omitted"):
            lines.append(
                f"{snapshot['evidence_omitted']} further evidence record(s) exist but were "
                "not included in this bounded summary."
            )
        lines.append(self.interpretation)
        return "\n".join(lines)


class OfflineDocumentProvider(SummaryProvider):
    """Deterministic document-scope summary. No LLM, no cross-document facts."""

    name = "offline-extractive"
    provenance_state = ProvenanceState.MACHINE_EXTRACTED

    def summarize(self, snapshot: dict) -> str:
        doc = snapshot["document"]
        lines = [
            f"Document {doc['publication_number']}"
            + (f" ({doc['title']})" if doc.get("title") else "")
            + (f", family {doc['family_key']}" if doc.get("family_key") else "")
            + f": {snapshot['compound_count']} deduplicated compound(s) are recorded for this "
            "document."
        ]
        if not doc.get("has_abstract"):
            lines.append(
                "No abstract text is stored for this document in this deployment, so the "
                "abstract was not summarized."
            )
        if not snapshot.get("claims_assessed"):
            lines.append(
                "No claims text is stored for this document: claims were not assessed, and "
                "nothing here should be read as a statement about claim scope."
            )
        if snapshot.get("scaffolds"):
            lines.append(
                "Murcko scaffolds present (this document only): "
                + ", ".join(f"{s['scaffold']} ({s['compounds']})" for s in snapshot["scaffolds"][:5])
                + "."
            )
        if snapshot.get("candidate_omitted"):
            lines.append(f"{snapshot['candidate_omitted']} further item(s) were omitted.")
        total = snapshot.get("measurement_total", 0)
        if snapshot.get("measurements"):
            lines.append(
                f"{total} typed measurement(s) are recorded for compounds in this document; "
                "values are listed per assay and are not ranked or combined:"
            )
            for m in (snapshot.get("measurements") or [])[:12]:
                lines.append(
                    f"- {m['inchikey']} {m['standard_type']} {m['relation']} {m['value']:g} "
                    f"{m['unit']} in {m['assay_key']} ({m['evidence_class']})."
                )
        else:
            lines.append(
                "No typed measurement is available for this document's compounds. Absence of a "
                "measurement is not evidence of inactivity."
            )
        if snapshot.get("evidence"):
            types = ", ".join(snapshot.get("evidence_source_types") or [])
            lines.append(
                f"{snapshot['evidence_total']} evidence record(s) are linked to this document "
                f"(source types: {types or 'unspecified'})."
            )
        else:
            lines.append("No evidence record is linked to this document.")
        lines.append(
            "Interpretation (SAR narrative, claim discussion, cross-document comparison) requires "
            "an LLM provider, which is not configured on this deployment."
        )
        return "\n".join(lines)


class OfflineTargetProvider(SummaryProvider):
    """Deterministic target-scope summary. Reports coverage as retrieved."""

    name = "offline-extractive"
    provenance_state = ProvenanceState.MACHINE_EXTRACTED

    def summarize(self, snapshot: dict) -> str:
        target = snapshot["target"]
        lines = [
            f"Target {target['target_key']}"
            + (f" ({target['name']})" if target.get("name") else "")
            + (f", UniProt {target['uniprot_accession']}" if target.get("uniprot_accession") else "")
            + f", {target.get('organism') or 'organism not recorded'}"
            + f", type {target.get('target_type') or 'not recorded'}"
            + f": {snapshot['candidate_total']} candidate compound(s) match the current filter "
            f"({snapshot['default_candidate_filter']})."
        ]
        if target.get("components"):
            related = [c for c in target["components"] if c.get("role") and c["role"] != "component"]
            if related:
                lines.append(
                    "System members kept distinct from this target: "
                    + ", ".join(f"{c['gene_symbol'] or c['accession']} ({c['role']})" for c in related)
                    + "."
                )
        for source in snapshot["sources"]:
            detail = f"- {source['source_name']}: {source['status']}"
            if source["records_kept"] or source["records_seen"]:
                detail += (
                    f" ({source['records_kept']} kept of {source['records_seen']} seen, "
                    f"{source['records_excluded']} not qualifying)"
                )
            if source["status"] == "failed":
                detail += " — the source did not answer; nothing can be concluded about its coverage"
            elif source["status"] == "empty":
                detail += " — the source answered and returned nothing for this scope"
            elif source["status"] == "not_queried":
                detail += " — this source was not queried"
            lines.append(detail)
        breakdown = snapshot.get("modality_breakdown") or {}
        if breakdown:
            lines.append(
                "Modality of the retrieved compounds: "
                + ", ".join(f"{n} {name}" for name, n in sorted(breakdown.items()))
                + ". Peptides and biologics are not interchangeable with small molecules."
            )
        reference = snapshot.get("reference") or {}
        if reference:
            lines.append(
                f"Potency reference under policy {reference.get('policy_version')} "
                f"(threshold {reference.get('threshold_label')}, scope "
                f"{reference.get('modality_scope')}): {reference.get('reason')}"
                + (
                    " This is a count of stored records under that stated threshold; it is not a "
                    "statement about what exists in the literature."
                )
            )
            if reference.get("best_active"):
                best = reference["best_active"]
                lines.append(
                    f"Best reported value in scope: {best.get('potency_label')} "
                    f"({best.get('evidence_class')}, {best.get('source_name')})."
                )
            if reference.get("records_without_structure"):
                lines.append(
                    f"{reference['records_without_structure']} source record(s) reported a value "
                    "without a public structure and are counted as rejections, not as "
                    "measurements."
                )
            if reference.get("supplement_remarks"):
                lines.append(
                    f"{reference['supplement_remarks']} row(s) were added by hand with a value "
                    "but no public structure and are stored as remarks, not as compounds or "
                    "measurements: a person's reading, not a source's record."
                )
        if snapshot.get("measurements"):
            counts = snapshot.get("evidence_class_counts") or {}
            listed = snapshot.get("measurements_listed", len(snapshot["measurements"]))
            lines.append(
                f"{snapshot['measurement_total']} typed measurement(s) are recorded for these "
                "candidates, classified conservatively across all of them: "
                + ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))
                + ". A measured affinity is not by itself proof of inhibitory function, and "
                "values from different assays are not comparable."
                + (
                    f" {listed} of them are listed in this bounded summary."
                    if listed < snapshot["measurement_total"]
                    else ""
                )
            )
        else:
            lines.append(
                "No typed measurement is recorded for the current candidate filter. That is not "
                "evidence that no inhibitors exist."
            )
        lines.append(
            f"{snapshot['patent_linked_candidates']} candidate(s) have a patent occurrence in the "
            "loaded corpus; the rest have no patent mapping. A patent occurrence is not proof that "
            "a compound inhibits this target, and its absence is not proof that it is unclaimed."
        )
        lines.append(
            "Missing records never demonstrate that no inhibitors exist. This summary covers the "
            "sources listed above and no wider claim is made."
        )
        lines.append(
            "Interpretation (mechanism narrative, SAR comparison) requires an LLM provider, which "
            "is not configured on this deployment."
        )
        return "\n".join(lines)


def offline_provider_for(scope: str) -> SummaryProvider:
    if scope == SummaryScope.DOCUMENT.value:
        return OfflineDocumentProvider()
    if scope == SummaryScope.TARGET.value:
        return OfflineTargetProvider()
    return OfflineExtractiveProvider()


class Paragraph(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    fact_refs: list[str] = Field(min_length=1)


class LlmSummaryOutput(BaseModel):
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=MAX_PARAGRAPHS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_LIMITATIONS)


def render_llm_text(output: LlmSummaryOutput) -> str:
    parts = [p.text for p in output.paragraphs]
    if output.limitations:
        parts.append(
            "Limitations:\n" + "\n".join(f"- {item}" for item in output.limitations)
        )
    return "\n\n".join(parts)


# --- summary orchestration -------------------------------------------------------

# Bounded in-flight registry (single process; plan §4). Multi-worker deployments
# are documented as outside this guarantee.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: set[str] = set()


def clear_inflight() -> None:
    """Test helper: reset the in-flight registry."""
    with _INFLIGHT_LOCK:
        _INFLIGHT.clear()


def summarize_family(
    engine: Engine,
    family_id: uuid.UUID,
    mode: str = "offline",
    llm_provider=None,
    owner_id: uuid.UUID | None = None,
):
    """Family-scope summary. A named entry point per scope keeps the service
    boundary explicit and the shared `summarize` path the single
    implementation to keep correct."""
    return summarize(
        engine,
        SummaryScope.FAMILY.value,
        family_id,
        mode=mode,
        llm_provider=llm_provider,
        owner_id=owner_id,
    )


def summarize_document(
    engine: Engine,
    document_id: uuid.UUID,
    mode: str = "offline",
    llm_provider=None,
    owner_id: uuid.UUID | None = None,
):
    """Document-scope summary: only this document's facts and evidence."""
    return summarize(
        engine,
        SummaryScope.DOCUMENT.value,
        document_id,
        mode=mode,
        llm_provider=llm_provider,
        owner_id=owner_id,
    )


def summarize_target(
    engine: Engine,
    target_id: uuid.UUID,
    mode: str = "offline",
    llm_provider=None,
    include_all_modalities: bool = False,
    owner_id: uuid.UUID | None = None,
):
    """Target-investigation summary: candidates, measurements and per-source
    coverage for one resolved target."""
    return summarize(
        engine,
        SummaryScope.TARGET.value,
        target_id,
        mode=mode,
        llm_provider=llm_provider,
        include_all_modalities=include_all_modalities,
        owner_id=owner_id,
    )


#: Scope → service entry point. One table, so a new scope must declare its
#: entry point instead of silently reusing another scope's collector.
SUMMARY_ENTRY_POINTS = {
    SummaryScope.FAMILY.value: "summarize_family",
    SummaryScope.DOCUMENT.value: "summarize_document",
    SummaryScope.TARGET.value: "summarize_target",
}


def summarize(
    engine: Engine,
    scope: str,
    scope_id: uuid.UUID,
    mode: str = "offline",
    llm_provider=None,
    include_all_modalities: bool = False,
    owner_id: uuid.UUID | None = None,
):
    """Generate or reuse a summary for an explicit scope.

    `scope` is one of `SummaryScope`; the caller must state it, because a
    document or target summary is a different analysis from a family summary
    even when the underlying rows overlap. Caching, validation and provenance
    behave exactly as for the family path.
    """
    from spago_core.services import NotFoundError  # noqa: F401  (re-exported for routes)

    if scope not in PROMPT_VERSION_BY_SCOPE:
        raise AIError(f"Unknown summary scope {scope!r}.")
    if mode not in ("offline", "llm"):
        raise AIError("Unknown summary mode.")
    if mode == "llm" and llm_provider is None:
        raise LLMConfigError()

    provider_name = "offline-extractive" if mode == "offline" else llm_provider.name
    model = None if mode == "offline" else llm_provider.model
    fingerprint = None if mode == "offline" else llm_provider.endpoint_fingerprint
    provenance = (
        ProvenanceState.MACHINE_EXTRACTED if mode == "offline" else llm_provider.provenance_state
    )
    prompt_version = PROMPT_VERSION_BY_SCOPE[scope]

    snapshot = build_summary_snapshot(engine, scope, scope_id, include_all_modalities)
    input_hash = compute_input_hash(
        snapshot,
        scope=scope,
        mode=mode,
        provider_name=provider_name,
        model=model,
        endpoint_fingerprint=fingerprint,
        thinking_disabled=None if mode == "offline" else bool(
            getattr(llm_provider, "disable_thinking", False)
        ),
        json_mode=None if mode == "offline" else bool(
            getattr(llm_provider, "json_mode", False)
        ),
    )

    # Cache lookup is owner-scoped: an analysis of private inputs must never be
    # served to another owner, so the owner is part of both the key and the
    # query (ONLINE-03, ADR-0002).
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, provider, provenance_state, text, citations,
                       dataset_version, model, usage, created_at, input_snapshot
                FROM ai_analyses
                WHERE input_hash = :h
                  AND ((CAST(:owner AS uuid) IS NULL AND owner_id IS NULL) OR owner_id = :owner)
                """
            ),
            {"h": input_hash, "owner": owner_id},
        ).mappings().first()
    if row is not None:
        return _row_to_response(row, cached=True, input_snapshot=row["input_snapshot"])

    if mode == "llm":
        from spago_core.config import get_settings
        from spago_core.services import usage as usage_svc

        limits = get_settings()
        usage_id = uuid.uuid4()
        reserved = False
        # The in-flight gate is taken before the quota check and the reservation:
        # a request refused for concurrency never reached the provider, so it must
        # not leave a reservation consuming budget for a call that never happened
        # (same defect class as finding 6; found 2026-09-15 while reading this path
        # to add the bounded retry, §9.3 of the live-smoke record).
        with _INFLIGHT_LOCK:
            if input_hash in _INFLIGHT:
                raise ContentInFlightError()
            if len(_INFLIGHT) >= MAX_CONCURRENT_LLM_CALLS:
                raise ProviderBusyError()
            _INFLIGHT.add(input_hash)
        try:
            if engine is not None:
                # Refuse before the call when a configured limit would be crossed
                # (ONLINE-04): browser controls are not a billing protection.
                usage_svc.check_quota(
                    engine,
                    owner_id=owner_id,
                    user_limit=limits.llm_user_token_limit,
                    deployment_limit=limits.llm_deployment_token_limit,
                    window=limits.llm_quota_window,
                    estimated_tokens=limits.llm_reserve_tokens,
                )
                usage_id = usage_svc.reserve(
                    engine,
                    owner_id=owner_id,
                    provider=provider_name,
                    model=model,
                    scope=scope,
                    input_hash=input_hash,
                    estimated_tokens=limits.llm_reserve_tokens,
                )
                reserved = True
            # One request, at most MAX_LLM_ATTEMPTS provider calls. Validation
            # stays inside the guarded region on purpose: a rejected answer is a
            # failed call. Leaving it outside left the reservation dangling
            # (outcome='reserved', settled_at NULL) and that row kept consuming
            # quota forever — found on 2026-09-15 by reading live usage rows after
            # provider rejections. A genuinely interrupted process still keeps its
            # reservation (usage.py documents why).
            accepted = _generate_accepted(llm_provider, snapshot)
            output = accepted.output
            summary_text = accepted.text
        except AIError as exc:
            if reserved:
                # A refused answer was still billed; settle with what the
                # provider reported so the quota reflects the real spend, and
                # fall back to the reservation when usage is unknown.
                observed = exc.usage or {}
                usage_svc.settle(
                    engine,
                    usage_id,
                    outcome=_usage_outcome(exc),
                    error=exc.detail,
                    prompt_tokens=observed.get("prompt_tokens"),
                    completion_tokens=observed.get("completion_tokens"),
                    total_tokens=observed.get("total_tokens"),
                )
            raise
        except Exception as exc:  # never leave a reservation unexplained
            if reserved:
                usage_svc.settle(engine, usage_id, outcome="failed", error=type(exc).__name__)
            raise
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(input_hash)
        # Both attempts were billed, so the account reports their sum; `attempts`
        # stays visible in the stored analysis for the operator.
        usage = _combine_usage(accepted.usages, attempts=accepted.attempts)
        if reserved:
            usage_svc.settle(
                engine,
                usage_id,
                outcome="succeeded",
                prompt_tokens=(usage or {}).get("prompt_tokens"),
                completion_tokens=(usage or {}).get("completion_tokens"),
                total_tokens=(usage or {}).get("total_tokens"),
            )
    else:
        summary_text = offline_provider_for(scope).summarize(snapshot)
        usage = None

    citations = _build_citations(output if mode == "llm" else None, snapshot)
    analysis_kind = f"{scope}_summary"

    # The id is owner-scoped: two owners analysing the same public family must
    # get two rows, not one row that one of them cannot read (ADR-0002).
    analysis_id = uuid.uuid5(_NAMESPACE, f"{analysis_kind}:{owner_id}:{input_hash}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ai_analyses (id, family_id, document_id, target_id, scope_kind,
                                         owner_id, provider, analysis_kind, text, citations,
                                         provenance_state, dataset_version, model,
                                         input_hash, prompt_version, input_snapshot, usage)
                VALUES (:id, :family_id, :document_id, :target_id, :scope_kind,
                        :owner_id, :provider, :analysis_kind, :text,
                        CAST(:citations AS jsonb), :provenance_state, :dataset_version,
                        :model, :input_hash, :prompt_version,
                        CAST(:input_snapshot AS jsonb), CAST(:usage AS jsonb))
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": analysis_id,
                "family_id": _scope_owner_id(snapshot, "family"),
                "document_id": _scope_owner_id(snapshot, "document"),
                "target_id": _scope_owner_id(snapshot, "target"),
                "scope_kind": scope,
                "owner_id": owner_id,
                "provider": provider_name,
                "analysis_kind": analysis_kind,
                "text": summary_text,
                "citations": json.dumps(citations, ensure_ascii=False),
                "provenance_state": provenance.value,
                "dataset_version": snapshot.get("dataset_version") or "unknown",
                "model": model,
                "input_hash": input_hash,
                "prompt_version": prompt_version,
                "input_snapshot": json.dumps(snapshot, ensure_ascii=False),
                "usage": json.dumps(usage) if usage else None,
            },
        )
        winner_id = conn.execute(
            text(
                """
                SELECT id FROM ai_analyses
                WHERE input_hash = :h
                  AND ((CAST(:owner AS uuid) IS NULL AND owner_id IS NULL) OR owner_id = :owner)
                """
            ),
            {"h": input_hash, "owner": owner_id},
        ).scalar_one()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, provider, provenance_state, text, citations,
                       dataset_version, model, usage, created_at, input_snapshot
                FROM ai_analyses WHERE id = :id
                """
            ),
            {"id": winner_id},
        ).mappings().first()
    return _row_to_response(
        row, cached=winner_id != analysis_id, input_snapshot=row["input_snapshot"]
    )


def _scope_owner_id(snapshot: dict, kind: str) -> uuid.UUID | None:
    """The id of the object that owns this analysis, for the given kind.

    A document summary records its document *and* the document's family; a
    target summary records its target and no family. Nothing is inferred beyond
    what the snapshot states.
    """
    if kind == "family":
        family = snapshot.get("family")
        if family and family.get("ref", "").startswith("family:"):
            return uuid.UUID(family["ref"].split(":", 1)[1])
        document = snapshot.get("document")
        if document and document.get("family_ref"):
            return uuid.UUID(document["family_ref"].split(":", 1)[1])
        return None
    node = snapshot.get(kind)
    if node and node.get("id") and node.get("ref", "").startswith(f"{kind}:"):
        return uuid.UUID(node["id"])
    return None


@dataclass(frozen=True)
class _AcceptedSummary:
    """A validated answer plus the provider calls it took to get one."""

    output: LlmSummaryOutput
    text: str
    attempts: int
    #: One entry per attempt, in order; None where the provider reported no
    #: usage, so the accounting can tell "unknown" from "zero".
    usages: list[dict | None]


def _generate_accepted(provider, snapshot: dict) -> _AcceptedSummary:
    """Generate and validate, re-sampling once after a content rejection.

    Only `LLMOutputRejectedError` is retried (see `MAX_LLM_ATTEMPTS`): that class
    means the provider completed and billed the call, so a second attempt cannot
    pay twice for an unknown outcome. The retry sends the identical request —
    no prompt mutation, so `prompt_version` stays truthful. A final rejection is
    re-raised unchanged: the API fails closed instead of repairing output, and
    the last attempt's error detail is what the operator sees.
    """
    usages: list[dict | None] = []
    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        result = None
        try:
            result = provider.generate(snapshot)
            output = _validate_llm_output(result, snapshot)
        except LLMOutputRejectedError as exc:
            usages.append(getattr(result, "usage", None))
            _attach_observed_usage(exc, usages, attempts=attempt)
            if attempt == MAX_LLM_ATTEMPTS:
                raise
            continue
        except LLMUpstreamError as exc:
            # Protocol failures raised after a completed response (a tool-call
            # attempt, say) were billed too; a transport failure carries no
            # usage and leaves the caller with the reservation.
            usages.append(getattr(result, "usage", None))
            _attach_observed_usage(exc, usages, attempts=attempt)
            raise
        usages.append(getattr(result, "usage", None))
        return _AcceptedSummary(
            output=output,
            text=render_llm_text(output),
            attempts=attempt,
            usages=usages,
        )
    raise AssertionError("unreachable: the attempt loop returns or raises")


def _attach_observed_usage(exc: AIError, usages: list[dict | None], *, attempts: int) -> None:
    """Record the billed usage on a failure, when every attempt reported it.

    `_combine_usage` returns None unless each attempt's usage is known: a
    partial sum would understate a real invoice, and the usage row keeps its
    reservation in that case (usage.py documents why the reservation stands).
    """
    observed = _combine_usage(usages, attempts=attempts)
    if observed is not None:
        exc.usage = observed


def _combine_usage(usages: list[dict | None], *, attempts: int) -> dict | None:
    """Total the billed usage of a re-sampled answer.

    Both calls were billed, so a retried answer reports their sum rather than the
    accepted attempt's numbers alone (AGENTS.md §10). If any attempt's usage is
    unknown the result is None on purpose: a partial sum would understate a real
    invoice, and the usage row then keeps its reservation instead.
    """
    if not usages or any(u is None for u in usages):
        return None
    totals: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        values = [u.get(key) for u in usages]
        if all(isinstance(v, int) for v in values):
            totals[key] = sum(values)
    if attempts > 1:
        totals["attempts"] = attempts
    return totals or None


def _bound_violation_detail(content: str, problems: list) -> str:
    """`paragraphs: 13 returned, at most 12 allowed.` for a length refusal, else "".

    Deliberately limited to the two declared list bounds: it exists so an
    operator can tell a paragraph overflow from a limitation overflow without
    re-running a billed call (2026-09-16), and it never echoes model text.
    """
    for problem in problems:
        kind = problem.get("type")
        if kind not in ("too_long", "too_short"):
            continue
        loc = problem.get("loc") or ()
        field = str(loc[0]) if loc else ""
        if field not in _BOUNDED_LISTS:
            continue
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            return ""
        value = parsed.get(field) if isinstance(parsed, dict) else None
        if not isinstance(value, list):
            return ""
        low, high = _BOUNDED_LISTS[field]
        if kind == "too_long":
            return f" {field}: {len(value)} returned, at most {high} allowed."
        return f" {field}: {len(value)} returned, at least {low} required."


def _validate_llm_output(llm_result, snapshot: dict) -> LlmSummaryOutput:
    """Structural + citation validation. Any failure rejects the output —
    nothing invalid is persisted as success.

    Rejections raised here are `LLMOutputRejectedError` (the answer was complete
    and billed, so it may be re-sampled once); a `tool_calls` violation is the
    exception, because re-asking a model that tried to use tools invites the same
    violation (AGENTS.md §12).
    """
    if llm_result.finish_reason != "stop":
        raise LLMOutputRejectedError("Model did not finish normally.")
    if llm_result.tool_calls:
        raise LLMUpstreamError("Model attempted tool calls; tool use is not allowed.")
    try:
        output = LlmSummaryOutput.model_validate_json(llm_result.content)
    except ValidationError as exc:
        # Name the failing class with the pydantic error `type` (a stable machine
        # token such as `json_invalid` or `too_long`). Measured 2026-09-15: the
        # generic message forced a manual diff of the raw answer to tell a
        # malformed-JSON tail from a length violation; the ledger and the 502
        # detail now say which rule broke. No model text is included.
        problems = exc.errors()
        first = problems[0]["type"] if problems else "unknown"
        detail = _bound_violation_detail(llm_result.content, problems)
        raise LLMOutputRejectedError(
            f"Model output failed JSON/schema validation ({first}).{detail}"
        ) from exc
    allowed = allowed_refs(snapshot)
    for p in output.paragraphs:
        if not p.text.strip():
            raise LLMOutputRejectedError("Model produced an empty paragraph.")
        if not p.fact_refs:
            raise LLMOutputRejectedError("A fact paragraph lacks citations.")
        unknown = [r for r in p.fact_refs if r not in allowed]
        if unknown:
            raise LLMOutputRejectedError(
                "Model cited fact references outside the allowed input set."
            )
    return output


def _build_citations(output: LlmSummaryOutput | None, snapshot: dict) -> list[dict]:
    """Typed citations from used fact refs. Measurements are database record
    references (inchikey label) — never patent-text evidence; evidence refs
    keep the legacy evidence_id field."""
    used: list[str] = []
    if output is not None:
        seen = set()
        for p in output.paragraphs:
            for ref in p.fact_refs:
                if ref not in seen:
                    seen.add(ref)
                    used.append(ref)
    else:
        used.extend(m["ref"] for m in snapshot.get("measurements") or [])
        root = (
            snapshot.get("family", {}).get("ref")
            or snapshot.get("document", {}).get("ref")
            or snapshot.get("target", {}).get("ref")
        )
        if root:
            used.insert(0, root)

    by_ref: dict[str, dict] = {}
    if snapshot.get("family"):
        by_ref[snapshot["family"]["ref"]] = {
            "kind": "family",
            "family_id": snapshot["family"].get("id"),
        }
    if snapshot.get("document"):
        doc = snapshot["document"]
        by_ref[doc["ref"]] = {
            "kind": "document",
            "document_id": doc["id"],
            "label": (
                f"{doc['publication_number']}"
                + (f" · {doc['title']}" if doc.get("title") else "")
            ),
        }
    if snapshot.get("target"):
        target = snapshot["target"]
        by_ref[target["ref"]] = {
            "kind": "target",
            "target_id": target["id"],
            "label": (
                f"{target['target_key']}"
                + (f" · {target['uniprot_accession']}" if target.get("uniprot_accession") else "")
            ),
        }
    reference = snapshot.get("reference")
    if isinstance(reference, dict) and reference.get("ref"):
        # The ONLINE-06 potency verdict (defect D9). The target prompt tells the
        # model to cite `reference:<id>` for potency statements; without this
        # mapping the ref was accepted by the validator and then dropped here, so
        # the reader lost the support link for the one number the summary is
        # allowed to repeat.
        by_ref[reference["ref"]] = {
            "kind": "reference",
            "target_id": snapshot.get("target", {}).get("id"),
            "label": (
                f"{reference.get('compounds_active')} of {reference.get('compounds')} "
                f"in-scope compound(s) at or below {reference.get('threshold_label')} "
                f"· {reference.get('policy_version')}"
            ),
        }
    for candidate in snapshot.get("candidates") or []:
        by_ref[candidate["ref"]] = {
            "kind": "candidate",
            "compound_id": candidate["compound_id"],
            "inchikey": candidate["inchikey"],
            "label": (
                f"{candidate['inchikey']} · {candidate['modality']} · "
                f"{candidate['evidence_class']}"
            ),
        }
    for s in snapshot.get("sources") or []:
        # A per-source retrieval citation (ONLINE-01, 2026-09-15): the label
        # states the retrieval's own facts, so a reader can see which source the
        # summary's coverage paragraph rests on. Without this mapping the ref
        # would be accepted by the validator and then silently dropped from the
        # citation list — an invisible support link.
        kept, seen = s.get("records_kept"), s.get("records_seen")
        label = f"{s['source_name']} · {s['status']} · {kept} kept"
        if seen is not None and kept != seen:
            label += f" of {seen} seen"
        if s.get("dataset_version"):
            label += f" · {s['dataset_version']}"
        by_ref[s["ref"]] = {
            "kind": "source",
            "source_name": s["source_name"],
            "label": label,
        }
    for m in snapshot.get("measurements") or []:
        by_ref[m["ref"]] = {
            "kind": "measurement",
            "inchikey": m["inchikey"],
            "compound_id": m.get("compound_id"),
            "measurement_id": m["ref"].split(":", 1)[1],
            "label": (
                f"{m['standard_type']} {m['relation']} {m['value']:g} {m['unit']} "
                f"({m['assay_key']})"
            ),
        }
    for e in snapshot.get("evidence") or []:
        # The document summary's evidence facts carry the document implicitly, so
        # the label falls back to the source type rather than assuming a
        # publication_number field is present (it is not, for that scope).
        prefix = e.get("publication_number") or (
            snapshot.get("document", {}).get("publication_number") if snapshot.get("document") else None
        )
        by_ref[e["ref"]] = {
            "kind": "evidence",
            "evidence_id": e["evidence_id"],
            "compound_id": e.get("compound_id"),
            "label": (
                (f"{prefix} · " if prefix else "")
                + f"{e['source_type']}"
                + (f" · {e['section']}" if e.get("section") else "")
            ),
        }

    citations = []
    for ref in used:
        meta = by_ref.get(ref)
        if meta is None:
            continue
        entry = {"fact_ref": ref, **meta}
        citations.append(entry)
    return citations


def _as_json(value):
    """psycopg may hand JSONB back as dict/list already; str means legacy text."""
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value


def _row_to_response(row, cached: bool, input_snapshot: dict) -> dict:
    snapshot = _as_json(input_snapshot) or {}
    return {
        "analysis_id": row["id"],
        "scope": snapshot.get("summary_scope") or "family",
        "provider": row["provider"],
        "provenance_state": row["provenance_state"],
        "text": row["text"],
        "citations": _as_json(row["citations"]) or [],
        "dataset_version": row["dataset_version"],
        "model": row["model"],
        "cached": cached,
        "usage": _as_json(row["usage"]),
        "coverage": snapshot.get("coverage", []),
        "input_snapshot": snapshot,
        "created_at": row["created_at"].isoformat(),
    }


# The deterministic planner moved to `services.planner`: it now emits the same
# typed plan contract the model produces, so there is one plan vocabulary rather
# than a second identifier-only response shape (ONLINE-02).
