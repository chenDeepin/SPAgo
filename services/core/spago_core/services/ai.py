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
import re
import threading
import uuid

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.domain import ProvenanceState

# --- budgets (internal defaults; see plan §4) ---------------------------------

PROMPT_VERSION = "family-summary-v2"
MAX_FACT_ITEMS = 50  # per kind (measurements, evidence excerpts)
MAX_BODY_BYTES = 32 * 1024
MAX_EXCERPT_BYTES = 1024  # UTF-8 bytes, not characters
MAX_SCAFFOLDS = 20
MAX_OUTPUT_TOKENS = 1500
MAX_CONCURRENT_LLM_CALLS = 2

INPUT_NOTE = "Bounded fact selection: whole items only; omitted items are reported in coverage."

_NAMESPACE = uuid.UUID("9f0c3d1a-7e2b-4c8d-a1b2-3c4d5e6f7a8b")


class AIError(Exception):
    """Base for AI summary failures; subclasses map to HTTP status codes."""

    status_code = 502
    detail = "AI summary failed."

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
                JOIN compound_mentions m ON m.compound_id = c.id
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
                JOIN compound_mentions m ON m.compound_id = c.id
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
                JOIN compound_mentions m ON m.compound_id = c.id
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
                FROM measurements mm
                JOIN compound_mentions cm ON cm.compound_id = mm.compound_id
                JOIN patent_documents d ON d.id = cm.document_id
                WHERE d.family_id = :fid
                """
            ),
            {"fid": family_id},
        ).scalar_one()
        measurement_rows = conn.execute(
            text(
                """
                SELECT mm.id, mm.standard_type, mm.relation, mm.value, mm.unit,
                       mm.source_name, mm.dataset_version, mm.provenance_state,
                       a.assay_key, a.assay_type, t.name AS target_name,
                       c.inchikey
                FROM measurements mm
                JOIN compounds c ON c.id = mm.compound_id
                JOIN assays a ON a.id = mm.assay_id
                JOIN targets t ON t.id = a.target_id
                WHERE mm.id IN (
                    SELECT DISTINCT mm2.id
                    FROM measurements mm2
                    JOIN compound_mentions cm ON cm.compound_id = mm2.compound_id
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
                FROM evidence_records e
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
                       d.publication_number
                FROM evidence_records e
                JOIN patent_documents d ON d.id = e.document_id
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
                LEFT JOIN compound_mentions cm ON cm.document_id = d.id
                LEFT JOIN measurements mm ON mm.compound_id = cm.compound_id
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
        "omitted_scaffolds": max(0, int(snapshot.pop("scaffold_total", 0)) - len(scaffolds)),
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


def allowed_refs(snapshot: dict) -> set[str]:
    refs = {snapshot["family"]["ref"]}
    refs.update(m["ref"] for m in snapshot["measurements"])
    refs.update(e["ref"] for e in snapshot["evidence"])
    return refs


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_input_hash(
    snapshot: dict,
    *,
    mode: str,
    provider_name: str,
    model: str | None,
    endpoint_fingerprint: str | None,
) -> str:
    """Content key: exact input snapshot + family + mode/provider + model +
    sanitized endpoint fingerprint + prompt_version + output budget (LLM-02)."""
    return _canonical_hash(
        {
            "kind": "family_summary",
            "prompt_version": PROMPT_VERSION,
            "mode": mode,
            "provider": provider_name,
            "model": model,
            "endpoint_fingerprint": endpoint_fingerprint,
            "output_budget": {"max_tokens": MAX_OUTPUT_TOKENS},
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
        if snapshot["scaffolds"]:
            top = ", ".join(
                f"{s['scaffold']} ({s['compounds']})" for s in snapshot["scaffolds"][:5]
            )
            lines.append(f"Murcko scaffolds present: {top}.")
        if snapshot.get("scaffold_omitted"):
            lines.append(
                f"{snapshot['scaffold_omitted']} further distinct scaffold(s) were not included "
                "in this bounded summary."
            )
        total = snapshot["measurement_total"]
        if snapshot["measurements"]:
            omitted = total - len(snapshot["measurements"])
            scope = f"{total} typed measurement(s) exist" + (
                f"; the first {len(snapshot['measurements'])} are listed" if omitted > 0 else ""
            )
            lines.append(
                f"{scope}. Values are listed per assay and are not ranked or "
                "combined into selectivity numbers:"
            )
            for m in snapshot["measurements"][:12]:
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


class Paragraph(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    fact_refs: list[str] = Field(min_length=1)


class LlmSummaryOutput(BaseModel):
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=12)
    limitations: list[str] = Field(default_factory=list, max_length=5)


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
):
    """Generate or reuse a family summary.

    mode="offline" uses the deterministic extractive provider; mode="llm"
    requires a configured `llm_provider` instance (OpenAI-compatible adapter).
    Content-key caching: identical input + identity reuses the stored row
    without calling the provider again (checked before any provider call).
    """
    from spago_core.services import NotFoundError  # noqa: F401  (re-exported for routes)

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

    facts = _collect_family_facts(engine, family_id)
    snapshot, _bounding = finalize_snapshot(facts)
    input_hash = compute_input_hash(
        snapshot,
        mode=mode,
        provider_name=provider_name,
        model=model,
        endpoint_fingerprint=fingerprint,
    )

    # 1. Cache lookup happens BEFORE any provider call (LLM-02).
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, provider, provenance_state, text, citations,
                       dataset_version, model, usage, created_at, input_snapshot
                FROM ai_analyses WHERE input_hash = :h
                """
            ),
            {"h": input_hash},
        ).mappings().first()
    if row is not None:
        return _row_to_response(row, cached=True, input_snapshot=row["input_snapshot"])

    # 2. Generate (offline is local; llm goes through the bounded in-flight set).
    if mode == "llm":
        with _INFLIGHT_LOCK:
            if input_hash in _INFLIGHT:
                raise ContentInFlightError()
            if len(_INFLIGHT) >= MAX_CONCURRENT_LLM_CALLS:
                raise ProviderBusyError()
            _INFLIGHT.add(input_hash)
        try:
            llm_result = llm_provider.generate(snapshot)
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.discard(input_hash)
        output = _validate_llm_output(llm_result, snapshot)
        summary_text = render_llm_text(output)
        usage = llm_result.usage
    else:
        offline = OfflineExtractiveProvider()
        summary_text = offline.summarize(snapshot)
        usage = None

    citations = _build_citations(output if mode == "llm" else None, snapshot)

    analysis_id = uuid.uuid5(_NAMESPACE, f"family-summary:{input_hash}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO ai_analyses (id, family_id, provider, analysis_kind, text,
                                         citations, provenance_state, dataset_version,
                                         model, input_hash, prompt_version,
                                         input_snapshot, usage)
                VALUES (:id, :family_id, :provider, 'family_summary', :text,
                        CAST(:citations AS jsonb), :provenance_state, :dataset_version,
                        :model, :input_hash, :prompt_version,
                        CAST(:input_snapshot AS jsonb), CAST(:usage AS jsonb))
                ON CONFLICT (input_hash) WHERE input_hash IS NOT NULL DO NOTHING
                """
            ),
            {
                "id": analysis_id,
                "family_id": family_id,
                "provider": provider_name,
                "text": summary_text,
                "citations": json.dumps(citations, ensure_ascii=False),
                "provenance_state": provenance.value,
                "dataset_version": snapshot["dataset_version"],
                "model": model,
                "input_hash": input_hash,
                "prompt_version": PROMPT_VERSION,
                "input_snapshot": json.dumps(snapshot, ensure_ascii=False),
                "usage": json.dumps(usage) if usage else None,
            },
        )
        winner_id = conn.execute(
            text("SELECT id FROM ai_analyses WHERE input_hash = :h"),
            {"h": input_hash},
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
    # If a racing writer won, its persisted row is returned (never new text
    # with an old timestamp — LLM-02).
    return _row_to_response(
        row, cached=winner_id != analysis_id, input_snapshot=row["input_snapshot"]
    )


def _validate_llm_output(llm_result, snapshot: dict) -> LlmSummaryOutput:
    """Structural + citation validation. Any failure rejects the output —
    nothing invalid is persisted as success."""
    if llm_result.finish_reason != "stop":
        raise LLMUpstreamError("Model did not finish normally.")
    if llm_result.tool_calls:
        raise LLMUpstreamError("Model attempted tool calls; tool use is not allowed.")
    try:
        output = LlmSummaryOutput.model_validate_json(llm_result.content)
    except ValidationError as exc:
        raise LLMUpstreamError("Model output failed JSON/schema validation.") from exc
    allowed = allowed_refs(snapshot)
    for p in output.paragraphs:
        if not p.text.strip():
            raise LLMUpstreamError("Model produced an empty paragraph.")
        if not p.fact_refs:
            raise LLMUpstreamError("A fact paragraph lacks citations.")
        unknown = [r for r in p.fact_refs if r not in allowed]
        if unknown:
            raise LLMUpstreamError(
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
        used.extend(m["ref"] for m in snapshot["measurements"])
        if snapshot["family"]["ref"]:
            used.insert(0, snapshot["family"]["ref"])

    by_ref: dict[str, dict] = {snapshot["family"]["ref"]: {"kind": "family"}}
    for m in snapshot["measurements"]:
        by_ref[m["ref"]] = {
            "kind": "measurement",
            "inchikey": m["inchikey"],
            "measurement_id": m["ref"].split(":", 1)[1],
            "label": (
                f"{m['standard_type']} {m['relation']} {m['value']:g} {m['unit']} "
                f"({m['assay_key']})"
            ),
        }
    for e in snapshot["evidence"]:
        by_ref[e["ref"]] = {
            "kind": "evidence",
            "evidence_id": e["evidence_id"],
            "label": (
                f"{e['publication_number']} · {e['source_type']}"
                + (f" · {e['section']}" if e["section"] else "")
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


# --- deterministic planner (unchanged contract) -----------------------------------

_PUBNUM_RE = re.compile(r"\b([A-Z]{2}\d{5,12}[A-Z]\d?)\b")


def plan_query(query: str) -> dict:
    """Deterministic identifier parsing only (PROMPT.md §12): extract
    publication-number-shaped tokens into a validated plan; everything else is
    reported unresolved rather than guessed."""
    tokens = _PUBNUM_RE.findall((query or "").upper())
    remainder = _PUBNUM_RE.sub(" ", (query or "").upper()).strip()
    return {
        "patent_queries": tokens,
        "unresolved_text": remainder or None,
        "note": (
            "Offline planner: only publication-number identifiers are extracted. "
            "Language interpretation requires an LLM provider."
        ),
    }
