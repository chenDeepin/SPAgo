"""Reading back stored analyses: the history half of the summary feature (B-10).

A summary SPAgo generated is a stored, citable artifact (`ai_analyses`), but until
now the only way back to it was to re-issue the exact same request and hit the
content cache. This module is the read path: list what an owner has, open one by
id, say honestly whether it still describes the current data, and render it for
export.

Two rules shape it:

- **Owner-scoped, exactly like the write path.** A stored analysis of private
  inputs is never listed or opened for another owner, and a legacy row with no
  owner is visible only to the unauthenticated (single-operator) deployment — the
  same predicate the cache lookup and the save path use (ADR-0002).
- **Staleness is stated, never hidden.** An analysis is a statement about the
  inputs it was given. When the deployment's data or the potency policy has moved
  since, the entry says so; it is never re-served as if it were current. The list
  uses cheap checks; opening one analysis additionally recomputes its input
  fingerprint, which is the exact question "would this request be a cache hit
  now?" (AGENTS.md §10, §25).
"""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text
from sqlalchemy.engine import Engine

from spago_core.services import NotFoundError

#: Page size for the history list. Bounded like every other list endpoint
#: (AGENTS.md §13): default 50, hard cap 200 — a person reads history, and one
#: owner rarely has more than a page of it.
DEFAULT_PAGE = 50
MAX_PAGE = 200

#: What the exported artifact says about the analysis' own provenance state; the
#: export never lets a reader mistake an inference for a source fact (AGENTS.md §10).
_PROVENANCE_SENTENCE = {
    "llm_inferred": "model output (llm_inferred) — an inference to be checked against the cited records, not a source fact",
    "machine_extracted": "deterministic extraction (machine_extracted) — assembled from the stored records without a model",
    "database_curated": "curated database content (database_curated)",
    "source_fact": "source fact (source_fact)",
    "user_curated": "edited by a person (user_curated)",
}

_SCOPE_NOUN = {"family": "patent family", "document": "document", "target": "target"}

_SELECT_COLUMNS = """
        a.id, a.scope_kind, a.analysis_kind, a.provider, a.model, a.provenance_state,
        a.dataset_version, a.prompt_version, a.created_at,
        a.family_id, a.document_id, a.target_id, a.usage,
        COALESCE(jsonb_array_length(a.citations), 0) AS citation_count,
        a.usage->>'total_tokens' AS total_tokens,
        a.input_snapshot->>'summary_scope' AS snapshot_scope,
        a.input_snapshot->'reference'->>'policy_version' AS policy_version,
        a.input_snapshot->'reference'->>'threshold_nM' AS policy_threshold_nm,
        f.family_key,
        d.publication_number AS document_number,
        t.target_key, t.name AS target_name,
        (SELECT pd.publication_number
           FROM patent_documents pd
          WHERE pd.family_id = a.family_id
          ORDER BY pd.publication_date NULLS LAST, pd.publication_number
          LIMIT 1) AS family_number
"""

_FROM = """
      FROM ai_analyses a
      LEFT JOIN patent_families f ON f.id = a.family_id
      LEFT JOIN patent_documents d ON d.id = a.document_id
      LEFT JOIN targets t ON t.id = a.target_id
"""


def _owner_predicate() -> str:
    """The one ownership rule, shared by every query here.

    Mirrors the cache lookup in `services.ai`: a null owner (single-operator
    deployment) sees only null-owner rows, and an authenticated owner sees only
    their own. Written once so a list, a get and an export cannot disagree.
    """
    return "((CAST(:owner AS uuid) IS NULL AND a.owner_id IS NULL) OR a.owner_id = :owner)"


def _scope_label(row) -> str:
    kind = row["scope_kind"] or "family"
    if kind == "target":
        return row["target_key"] or row["target_name"] or f"{_SCOPE_NOUN[kind]} (no longer present)"
    if kind == "document":
        return row["document_number"] or f"{_SCOPE_NOUN[kind]} (no longer present)"
    return row["family_key"] or f"{_SCOPE_NOUN[kind]} (no longer present)"


def _scope_query(row) -> str | None:
    """What the search box accepts to get back to this scope, when it exists.

    A family is opened by one of its publication numbers and a target by its key;
    a document by its own number. `None` means the scope entity is gone, and the
    UI must not offer navigation it cannot perform (AGENTS.md §18).
    """
    kind = row["scope_kind"] or "family"
    if kind == "target":
        return row["target_key"] if row["target_id"] and row["target_key"] else None
    if kind == "document":
        return row["document_number"] if row["document_id"] and row["document_number"] else None
    return row["family_number"] if row["family_id"] and row["family_number"] else None


def _stored_snapshot(engine: Engine, analysis_id: uuid.UUID) -> dict | None:
    """The stored `input_snapshot`, read on demand.

    The list query deliberately does not select it: fifty snapshots of up to
    32 KB is a payload no history view needs, and the fields the list does show
    (policy version, threshold) are extracted from it in SQL.
    """
    with engine.connect() as conn:
        raw = conn.execute(
            text("SELECT input_snapshot FROM ai_analyses WHERE id = :id"), {"id": analysis_id}
        ).scalar_one_or_none()
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def _canonical_hash(snapshot: dict) -> str:
    from spago_core.services import ai as ai_svc

    return ai_svc._canonical_hash(snapshot)


def _exact_input_check(engine: Engine, row, stored: dict | None) -> dict:
    """Recompute this analysis' input fingerprint and compare.

    The recomputation is the same pure function the write path uses, so a match
    means regenerating the request would serve this very row from the content
    cache, and a mismatch means something in the scope's inputs moved (records
    added, edited, or retracted). No model call is made either way.
    """
    from spago_core.services import ai as ai_svc

    scope = row["scope_kind"] or "family"
    scope_id = {
        "family": row["family_id"],
        "document": row["document_id"],
        "target": row["target_id"],
    }.get(scope)
    if scope_id is None:
        return {"same_inputs": None, "note": "the scope this analysis covers no longer exists"}
    reference = (stored or {}).get("reference")
    include_all = None
    if isinstance(reference, dict) and reference.get("modality_scope"):
        include_all = "all modalities" in str(reference["modality_scope"])
    try:
        snapshot = ai_svc.build_summary_snapshot(engine, scope, scope_id, bool(include_all))
    except NotFoundError:
        return {"same_inputs": None, "note": "the scope this analysis covers no longer exists"}
    except Exception as exc:  # noqa: BLE001 — reported, never guessed at
        return {"same_inputs": None, "note": f"the inputs could not be re-read ({type(exc).__name__})"}
    same = stored is not None and _canonical_hash(stored) == _canonical_hash(snapshot)
    return {
        "same_inputs": same,
        "note": (
            "The scope's inputs are unchanged since this analysis was generated; regenerating "
            "it would return this same stored answer."
            if same
            else "The scope's inputs have changed since this analysis was generated (records "
            "added, edited or retracted). Regenerating would produce a new analysis."
        ),
    }


def _cheap_staleness(row, *, current_dataset, current_policy_version, prompt_versions) -> list[str]:
    """The reasons visible without recomputing anything.

    Deliberately conservative: it names only changes it can prove from the row
    and the deployment's current constants. "No reason listed" therefore means
    "nothing cheap says this moved" — the exact check answers the question fully
    when the entry is opened.
    """
    reasons: list[str] = []
    scope = row["scope_kind"] or "family"
    if _scope_query(row) is None:
        reasons.append(
            f"The {_SCOPE_NOUN[scope]} this analysis covers is no longer in the workspace."
        )
    if scope == "target" and row["policy_version"] and row["policy_version"] != current_policy_version:
        reasons.append(
            f"Generated under potency policy {row['policy_version']}; this deployment applies "
            f"{current_policy_version}. Counts and classes may differ."
        )
    current_prompt = prompt_versions.get(scope)
    if row["prompt_version"] and current_prompt and row["prompt_version"] != current_prompt:
        reasons.append(
            f"Generated with prompt {row['prompt_version']}; the current build uses {current_prompt}."
        )
    # The dataset comparison is only meaningful for patent-scope analyses: a
    # target analysis records the version of its own retrieval rows, not the
    # patent corpus version, and comparing the two would be a false alarm.
    if (
        scope in ("family", "document")
        and current_dataset
        and row["dataset_version"]
        and row["dataset_version"] not in (current_dataset, "mixed", "unknown")
    ):
        reasons.append(
            f"Generated from dataset {row['dataset_version']}; the deployment now reports "
            f"{current_dataset}."
        )
    return reasons


def _row_to_entry(row, *, stale_reasons: list[str]) -> dict:
    return {
        "analysis_id": row["id"],
        "scope": row["scope_kind"] or "family",
        "analysis_kind": row["analysis_kind"],
        "scope_label": _scope_label(row),
        "scope_query": _scope_query(row),
        "scope_id": row["family_id"] or row["document_id"] or row["target_id"],
        "provider": row["provider"],
        "model": row["model"],
        "mode": "llm" if row["model"] else "offline",
        "provenance_state": row["provenance_state"],
        "prompt_version": row["prompt_version"],
        "dataset_version": row["dataset_version"],
        "created_at": row["created_at"].isoformat(),
        "citation_count": row["citation_count"],
        "total_tokens": row["total_tokens"],
        "stale": bool(stale_reasons),
        "stale_reasons": stale_reasons,
        "exact_check": None,
    }


def _staleness_context(engine: Engine) -> dict:
    from spago_core.services import ai as ai_svc
    from spago_core.services import get_dataset_info, reference as reference_svc

    info = get_dataset_info(engine)
    return {
        "current_dataset": info["dataset_version"] if info else None,
        "current_policy_version": reference_svc.ACTIVITY_POLICY_VERSION,
        "prompt_versions": ai_svc.PROMPT_VERSION_BY_SCOPE,
    }


def list_analyses(
    engine: Engine,
    owner_id,
    *,
    scope: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = DEFAULT_PAGE,
) -> tuple[list[dict], int]:
    """This owner's stored analyses, newest first, with cheap staleness flags."""
    from spago_core.services import ai as ai_svc

    offset = max(0, offset)
    limit = max(1, min(limit, MAX_PAGE))
    if scope is not None and scope not in ai_svc.PROMPT_VERSION_BY_SCOPE:
        raise ValueError(f"Unknown summary scope {scope!r}.")

    where = [_owner_predicate()]
    params: dict = {"owner": owner_id, "limit": limit, "offset": offset}
    if scope is not None:
        where.append("a.scope_kind = :scope")
        params["scope"] = scope
    if search:
        # A label finder, nothing more: the owner searches by what they remember
        # (family key, publication number, target). Wildcards in the query are
        # escaped so a literal `%` cannot turn into "match everything".
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append(
            "(f.family_key ILIKE :search ESCAPE '\\' "
            "OR d.publication_number ILIKE :search ESCAPE '\\' "
            "OR t.target_key ILIKE :search ESCAPE '\\' "
            "OR t.name ILIKE :search ESCAPE '\\')"
        )
        params["search"] = f"%{escaped}%"
    clause = " AND ".join(where)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT {_SELECT_COLUMNS}
                {_FROM}
                WHERE {clause}
                ORDER BY a.created_at DESC, a.id
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
        total = int(
            conn.execute(text(f"SELECT count(*) {_FROM} WHERE {clause}"), params).scalar_one()
        )

    context = _staleness_context(engine)
    entries = [
        _row_to_entry(
            row,
            stale_reasons=_cheap_staleness(
                row,
                current_dataset=context["current_dataset"],
                current_policy_version=context["current_policy_version"],
                prompt_versions=context["prompt_versions"],
            ),
        )
        for row in rows
    ]
    return entries, total


def get_analysis(engine: Engine, analysis_id: uuid.UUID, owner_id) -> dict:
    """One stored analysis with its full text, citations and the exact check."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT {_SELECT_COLUMNS}, a.text, a.citations
                {_FROM}
                WHERE a.id = :id AND {_owner_predicate()}
                """
            ),
            {"id": analysis_id, "owner": owner_id},
        ).mappings().first()
    if row is None:
        raise NotFoundError(f"Analysis {analysis_id} not found")

    context = _staleness_context(engine)
    reasons = _cheap_staleness(row, **context)
    stored = _stored_snapshot(engine, analysis_id)
    exact = _exact_input_check(engine, row, stored)
    if exact.get("same_inputs") is not True:
        note = exact.get("note")
        if note:
            reasons.append(note[0].upper() + note[1:] + ".")
    entry = _row_to_entry(row, stale_reasons=reasons)
    entry["exact_check"] = exact
    entry["text"] = row["text"]
    entry["citations"] = _as_json(row["citations"]) or []
    entry["usage"] = _as_json(row["usage"])
    return entry


def _as_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def render_analysis_markdown(analysis: dict, *, current_dataset: str | None = None) -> str:
    """The analysis as a self-describing Markdown file.

    The header is the point of the export: a summary read later, out of the app,
    must state its scope, its provider and model, the prompt and policy that
    produced it, the data version it saw, and whether that is still the current
    one (AGENTS.md §9, §10, §25). Nothing here promotes an inference to a fact.
    """
    scope = analysis["scope"]
    lines = [
        f"# SPAgo {scope} analysis",
        "",
        f"- Analysis id: `{analysis['analysis_id']}`",
        f"- Scope: {scope} · `{analysis['scope_label']}`",
        f"- Generated: {analysis['created_at']}",
        f"- Provider: {analysis['provider']}",
        f"- Model: {analysis['model'] or 'none (offline, deterministic)'}",
        f"- Mode: {analysis['mode']}",
        f"- Provenance: {analysis['provenance_state']} — "
        + _PROVENANCE_SENTENCE.get(
            analysis["provenance_state"], "see SPAgo's provenance states (AGENTS.md §10)"
        ),
        f"- Prompt version: {analysis['prompt_version'] or 'not recorded'}",
        f"- Dataset version at generation: {analysis['dataset_version']}",
    ]
    if current_dataset:
        lines.append(
            f"- Dataset version now: {current_dataset}"
            + (
                " (unchanged)"
                if current_dataset == analysis["dataset_version"]
                else " (the deployment has moved since this analysis was generated)"
            )
        )
    if analysis.get("total_tokens"):
        lines.append(f"- Tokens billed: {analysis['total_tokens']}")
    lines.append(f"- Citations: {analysis['citation_count']}")
    exact = analysis.get("exact_check") or {}
    if exact:
        lines.append(
            "- Inputs unchanged since generation: "
            + {True: "yes", False: "no", None: "not checked"}[exact.get("same_inputs")]
        )
    if analysis["stale_reasons"]:
        lines.append("- Staleness:")
        for reason in analysis["stale_reasons"]:
            lines.append(f"  - {reason}")
    else:
        lines.append("- Staleness: no change detected against this deployment's current data.")
    lines += ["", "## Summary", "", analysis["text"], ""]
    citations = analysis.get("citations") or []
    lines.append(f"## Citations ({len(citations)})")
    lines.append("")
    if not citations:
        lines.append("No citations were recorded for this analysis.")
    for citation in citations:
        label = citation.get("label") or citation.get("fact_ref") or "citation"
        lines.append(f"- `{citation.get('fact_ref', '')}` — {citation.get('kind', '')}: {label}")
    lines += [
        "",
        "---",
        "",
        "Measurement citations refer to database records (source name, value, unit), not to "
        "patent text; evidence citations refer to the stored patent sections. Structures, "
        "values and patent numbers inside a model-generated analysis must be checked against "
        "those records before being relied on. Nothing here is legal advice (AGENTS.md §32).",
        "",
    ]
    return "\n".join(lines)
