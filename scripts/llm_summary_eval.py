"""ONLINE-01 evaluation baseline for LLM summaries against a live endpoint.

Purpose: turn "the summaries look fine" into a recorded number. The runner sends
the *shipped* provider input for each scope, applies the *shipped* retry policy,
and reports attempt-level compliance, latency and token usage. It records; it
does not judge — the residual classes that structural validation cannot see are
listed in the record under `benchmarks/`.

Run (operator tooling, like `scripts/mock_llm_endpoint.py`):
    docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
        python /app/scripts/llm_summary_eval.py --yes
    # keep a record: add --samples 3 --target-key TSLP and redirect the JSON
    docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app \
        python /app/scripts/llm_summary_eval.py --yes --samples 3 --out - \
        > benchmarks/online01-llm-eval-<date>.json
    # progress goes to stderr; stdout is the JSON record when --out - is used

What it deliberately does not do:
  * no write to PostgreSQL: no `ai_analyses` row (so the product cache is not
    populated) and no `llm_usage` row (so the demo ledger is not charged). The
    provider still bills these calls; the same is true of any manual `curl`;
  * no HTTP route: status mapping, quota refusal and owner scoping are tested in
    the suite, not measured here;
  * no prompt or snapshot rewriting: `services/ai.py` owns both, so a baseline
    cannot describe a request the product never makes. The recorded `input_hash`
    is the app's own cache key for that request — a matching hash in
    `ai_analyses` is proof that both sent the same payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from spago_core.adapters.llm import (
    LLMConfigProblem,
    OpenAICompatibleSummaryProvider,
    parse_endpoint,
)
from spago_core.config import get_settings
from spago_core.db.engine import make_engine
from spago_core.services import ai as ai_svc
from spago_core.services import core as core_svc
from spago_core.services import targets as targets_svc

SCOPES = ("family", "document", "target")


def _snapshot_bytes(snapshot: dict) -> int:
    return len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8"))


def _default_publication_number(engine) -> str:
    """The sample record when the operator names none: the first stored document."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT publication_number FROM patent_documents ORDER BY publication_number LIMIT 1")
        ).first()
    if row is None:
        raise SystemExit("No documents in the database; load a dataset first.")
    return str(row[0])


def _default_target_key(engine) -> str:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT target_key FROM targets ORDER BY target_key LIMIT 1")).first()
    if row is None:
        raise SystemExit("No targets in the database; investigate a target first.")
    return str(row[0])


def _resolve_scope_ids(
    engine, scopes, publication_number: str, target_key: str
) -> dict[str, tuple[uuid.UUID, str]]:
    """Resolve each measured scope through the shipped lookups, not raw SQL.

    `find_patent` is the same read the patent route serves, so the sample a
    baseline measures is the record the product opens; a missing record is an
    error, never a zero-result baseline.
    """
    resolved: dict[str, tuple[uuid.UUID, str]] = {}
    if "target" in scopes:
        resolved["target"] = (targets_svc.target_id_for_key(target_key), target_key)
    if "family" in scopes or "document" in scopes:
        document, overview = core_svc.find_patent(engine, publication_number)
        if "family" in scopes:
            resolved["family"] = (overview.family.id, overview.family.family_key)
        if "document" in scopes:
            resolved["document"] = (document.id, document.publication_number)
    return resolved


def _classify(result, snapshot: dict) -> tuple[str, str | None]:
    """Accepted or rejected, using the shipped validator (pure, no side effects)."""
    try:
        ai_svc._validate_llm_output(result, snapshot)
    except ai_svc.AIError as exc:
        return "rejected", f"{type(exc).__name__}: {exc.detail}"
    return "accepted", None


class _RecordingProvider:
    """Delegates to the real provider and records every attempt verbatim.

    The retry decision stays with `ai._generate_accepted`; this only observes, so
    the recorded compliance rate describes the shipped policy rather than a copy
    of it. Each attempt stores what the provider returned, the classification the
    shipped validator gives it, and the wall time of the call.
    """

    def __init__(self, inner: OpenAICompatibleSummaryProvider, snapshot: dict) -> None:
        self._inner = inner
        self._snapshot = snapshot
        self.attempts: list[dict] = []

    def __getattr__(self, item):  # model, endpoint_fingerprint, request flags
        # Any missing attribute is the decorated provider's; `__getattr__` must
        # not recurse into itself for the private state set above.
        if item.startswith("_"):
            raise AttributeError(item)
        return getattr(self._inner, item)

    def generate(self, snapshot: dict):
        started = time.monotonic()
        record: dict = {"attempt": len(self.attempts) + 1}
        try:
            result = self._inner.generate(snapshot)
        except Exception as exc:
            record.update(
                {
                    "outcome": "error",
                    "error": type(exc).__name__,
                    "detail": getattr(exc, "detail", str(exc)),
                    "latency_ms": int((time.monotonic() - started) * 1000),
                }
            )
            self.attempts.append(record)
            raise
        outcome, detail = _classify(result, snapshot)
        content = result.content or ""
        record.update(
            {
                "outcome": outcome,
                "detail": detail,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "finish_reason": result.finish_reason,
                "tool_calls": bool(result.tool_calls),
                "usage": result.usage,
                "content_chars": len(content),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
                "content": content,
            }
        )
        self.attempts.append(record)
        return result


def _measure(provider, snapshot: dict, scope: str, label: str, input_hash: str) -> dict:
    """One request through the shipped bounded-retry path."""
    recorder = _RecordingProvider(provider, snapshot)
    started = time.monotonic()
    failure: dict | None = None
    try:
        accepted = ai_svc._generate_accepted(recorder, snapshot)
    except Exception as exc:
        accepted = None
        failure = {"error": type(exc).__name__, "detail": getattr(exc, "detail", str(exc))}
    wall_ms = int((time.monotonic() - started) * 1000)
    usages = [a.get("usage") for a in recorder.attempts] if recorder.attempts else []
    billed = ai_svc._combine_usage(usages, attempts=len(usages))
    return {
        "scope": scope,
        "scope_label": label,
        "input_hash": input_hash,
        "input_bytes": _snapshot_bytes(snapshot),
        "allowed_refs": len(ai_svc.allowed_refs(snapshot)),
        "wall_ms": wall_ms,
        "requests": 1,
        "attempts": recorder.attempts,
        "accepted": accepted is not None,
        "re_sample": bool(accepted and accepted.attempts > 1),
        "stored_text": accepted.text if accepted else None,
        "stored_usage": ai_svc._combine_usage(usages, attempts=len(usages)) if accepted else None,
        # Every completed call is billed, including the ones the validator
        # refused and the re-sample they caused. Measured 2026-09-15: reporting
        # only the accepted attempt's usage understated a 2-call request as
        # "unknown", hiding the cost of the rejection classes this run exists to
        # count.
        "billed_usage": billed,
        "failure": failure,
    }


def _log(message: str = "") -> None:
    """Human progress goes to stderr, so `--out -` can emit pure JSON on stdout."""
    print(message, file=sys.stderr, flush=True)


def _provider_for(scope: str, endpoint) -> OpenAICompatibleSummaryProvider:
    return OpenAICompatibleSummaryProvider(
        endpoint,
        scope=scope,
        prompt_version=ai_svc.PROMPT_VERSION_BY_SCOPE.get(scope, ai_svc.PROMPT_VERSION),
    )


def _print_row(run: dict) -> None:
    attempts = run["attempts"]
    marks = " ".join(
        f"#{a['attempt']}:{a['outcome'][:8]}({a.get('latency_ms', 0)}ms)"
        for a in attempts
    )
    usage = run.get("stored_usage") or {}
    total = usage.get("total_tokens")
    _log(
        f"  {run['scope']:8s} {run['scope_label']:16s} "
        f"attempts={len(attempts)} {marks} "
        f"tokens={total if total is not None else 'unknown'} "
        f"chars={len(run['stored_text'] or '')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scope", action="append", choices=SCOPES, help="repeatable; default all")
    parser.add_argument("--samples", type=int, default=1, help="requests per scope")
    parser.add_argument(
        "--publication-number",
        default=None,
        help="family/document sample; default: the first stored document",
    )
    parser.add_argument(
        "--target-key",
        default=None,
        help="target sample; default: the first stored target",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="write the JSON record to this path; '-' writes it to stdout "
        "(human progress always goes to stderr)",
    )
    parser.add_argument("--dry-run", action="store_true", help="show the plan, call nothing")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required: these calls are billed by the provider",
    )
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be at least 1")

    settings = get_settings()
    try:
        endpoint = parse_endpoint(settings)
    except LLMConfigProblem as exc:
        print(f"LLM endpoint not usable: {exc}", file=sys.stderr)
        return 2

    scopes = tuple(args.scope) if args.scope else SCOPES
    engine = make_engine()
    publication_number = args.publication_number or _default_publication_number(engine)
    target_key = args.target_key or _default_target_key(engine)
    scope_ids = _resolve_scope_ids(engine, scopes, publication_number, target_key)
    plan = []
    for scope in scopes:
        scope_id, label = scope_ids[scope]
        snapshot = ai_svc.build_summary_snapshot(engine, scope, scope_id)
        plan.append((scope, scope_id, label, snapshot))

    print(
        f"model={endpoint.model} endpoint={endpoint.endpoint_fingerprint} "
        f"thinking_disabled={endpoint.disable_thinking} json_mode={endpoint.json_mode} "
        f"max_output_tokens={ai_svc.MAX_OUTPUT_TOKENS} "
        f"prompt_versions={[ai_svc.PROMPT_VERSION_BY_SCOPE[s] for s in scopes]}",
        file=sys.stderr,
    )
    _log(f"planned provider calls: {len(plan) * args.samples} request(s), "
         f"at most {len(plan) * args.samples * ai_svc.MAX_LLM_ATTEMPTS} call(s)")
    for scope, _sid, label, snapshot in plan:
        _log(
            f"  {scope:8s} {label:16s} input_bytes={_snapshot_bytes(snapshot)} "
            f"allowed_refs={len(ai_svc.allowed_refs(snapshot))} prompt_version="
            f"{ai_svc.PROMPT_VERSION_BY_SCOPE[scope]}"
        )
    if args.dry_run:
        _log("dry run: no provider call made.")
        return 0
    if not args.yes:
        _log("refusing to spend provider tokens without --yes (or use --dry-run).")
        return 2

    runs: list[dict] = []
    for scope, scope_id, label, snapshot in plan:
        provider = _provider_for(scope, endpoint)
        input_hash = ai_svc.compute_input_hash(
            snapshot,
            scope=scope,
            mode="llm",
            provider_name=provider.name,
            model=provider.model,
            endpoint_fingerprint=provider.endpoint_fingerprint,
            thinking_disabled=bool(endpoint.disable_thinking),
            json_mode=bool(endpoint.json_mode),
        )
        _log(f"{scope} {label} input_hash={input_hash}")
        for _ in range(args.samples):
            run = _measure(provider, snapshot, scope, label, input_hash)
            runs.append(run)
            _print_row(run)

    attempts = [a for r in runs for a in r["attempts"]]
    rejected = [a for a in attempts if a["outcome"] == "rejected"]
    errors = [a for a in attempts if a["outcome"] == "error"]
    # Billed, not stored: a refused call costs the same as an accepted one.
    tokens = sum((r.get("billed_usage") or {}).get("total_tokens") or 0 for r in runs)
    known_tokens = all(
        any(a.get("usage") for a in r["attempts"]) or not r["attempts"] for r in runs
    )
    latencies = [a["latency_ms"] for a in attempts] or [0]
    _log(
        f"\n{len(runs)} request(s), {len(attempts)} provider call(s): "
        f"{sum(1 for r in runs if r['accepted'])}/{len(runs)} answered "
        f"(re-sampled: {sum(1 for r in runs if r['re_sample'])}), "
        f"rejected: {len(rejected)}, transport/upstream errors: {len(errors)}"
    )
    _log(
        f"tokens: {tokens if known_tokens else 'unknown (a call reported no usage)'} "
        f"· median call latency: {int(statistics.median(latencies))} ms "
        f"· max: {max(latencies)} ms"
    )
    for a in rejected + errors:
        _log(f"  ! {a['outcome']}: {a.get('detail')}")

    if args.out:
        record = {
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": endpoint.model,
            "endpoint_fingerprint": endpoint.endpoint_fingerprint,
            "thinking_disabled": bool(endpoint.disable_thinking),
            "json_mode": bool(endpoint.json_mode),
            "max_output_tokens": ai_svc.MAX_OUTPUT_TOKENS,
            "max_attempts": ai_svc.MAX_LLM_ATTEMPTS,
            "prompt_versions": {s: ai_svc.PROMPT_VERSION_BY_SCOPE[s] for s in scopes},
            "samples_per_scope": args.samples,
            "scopes": {
                scope: {
                    "scope_id": str(scope_id),
                    "label": label,
                    "input_bytes": _snapshot_bytes(snapshot),
                    "allowed_refs": len(ai_svc.allowed_refs(snapshot)),
                    # The exact provider input, once per scope: without it a later
                    # run can only see that the hash changed, not what changed
                    # (learned 2026-09-15 while explaining a target-hash drift).
                    "input_snapshot": snapshot,
                }
                for scope, scope_id, label, snapshot in plan
            },
            "runs": runs,
        }
        if args.out == "-":
            # stdout stays pure JSON so the operator can redirect it to a file
            # owned by the host user (the container writes as root otherwise).
            json.dump(record, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            with open(args.out, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
            _log(f"wrote {args.out}")
    return 0 if not errors and all(r["accepted"] for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
