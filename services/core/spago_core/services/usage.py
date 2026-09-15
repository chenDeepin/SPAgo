"""Hosted usage accounting and quotas (ONLINE-04).

The plan requires an enforceable bound on paid model usage that does not depend
on browser controls, plus accounting that survives a restart. This module keeps
that in PostgreSQL — the same database as the rest of the state — because the
architecture already has it and a counter does not justify new infrastructure
(AGENTS.md §6, §22).

Design points:

- **Two limits, both required.** A per-user limit stops one account consuming the
  deployment's budget; a deployment-wide limit bounds the operator's spend even
  if invitations leak. Both are checked before the call, not after.
- **Reservations, not retroactive totals.** A request reserves an estimated
  token budget atomically; the actual usage is recorded when the call returns.
  An interrupted request leaves its reservation, which is the conservative
  direction. No row is ever silently forgotten.
- **Tokens, not currency.** When the operator has not configured a price, the
  report says so and reports tokens. Inventing a currency cost from an unstated
  price would be a fabricated number (AGENTS.md §10).
- **Explicit quota errors.** A refused request says which limit it hit and when
  the window resets, so the UI can explain it instead of showing a generic fault.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine


class QuotaExceededError(Exception):
    """A configured usage limit would be exceeded. Maps to HTTP 429."""

    status_code = 429

    def __init__(self, scope: str, limit: int, used: int, window: str) -> None:
        self.scope = scope
        self.limit = limit
        self.used = used
        self.window = window
        super().__init__(
            f"The {scope} model-usage limit for this {window} has been reached "
            f"({used} of {limit} tokens). It resets when the window rolls over; "
            "no model request was sent."
        )


@dataclass(frozen=True)
class UsageReport:
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

    def to_dict(self) -> dict:
        return {
            "window": self.window,
            "user_tokens": self.user_tokens,
            "user_limit": self.user_limit,
            "deployment_tokens": self.deployment_tokens,
            "deployment_limit": self.deployment_limit,
            "requests": self.requests,
            "failures": self.failures,
            "estimated_cost": self.estimated_cost,
            "currency": self.currency,
            "cost_note": self.cost_note,
        }


def _window_start(window: str) -> datetime:
    now = datetime.now(timezone.utc)
    if window == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window == "month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # "total" is the whole recorded history.
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def used_tokens(
    engine: Engine, window: str, owner_id: uuid.UUID | None = None
) -> tuple[int, int, int]:
    """(user_tokens, deployment_tokens, request_count) inside the window."""
    start = _window_start(window)
    clauses = ["created_at >= :start"]
    params: dict = {"start": start}
    if owner_id is not None:
        clauses.append("owner_id = :owner")
        params["owner"] = owner_id
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT coalesce(sum(coalesce(total_tokens, reserved_tokens)), 0) AS tokens,
                       count(*) AS requests
                FROM llm_usage WHERE {where}
                """
            ),
            params,
        ).mappings().one()
        deployment = conn.execute(
            text(
                """
                SELECT coalesce(sum(coalesce(total_tokens, reserved_tokens)), 0)
                FROM llm_usage WHERE created_at >= :start
                """
            ),
            {"start": start},
        ).scalar_one()
    return int(row["tokens"]), int(deployment), int(row["requests"])


def check_quota(
    engine: Engine,
    *,
    owner_id: uuid.UUID | None,
    user_limit: int,
    deployment_limit: int,
    window: str,
    estimated_tokens: int,
) -> None:
    """Refuse before the provider call when a limit would be crossed.

    Checked in both directions: the caller's own budget and the deployment's.
    """
    if user_limit <= 0 and deployment_limit <= 0:
        return
    user_tokens, deployment_tokens, _requests = used_tokens(engine, window, owner_id)
    if deployment_limit > 0 and deployment_tokens + estimated_tokens > deployment_limit:
        raise QuotaExceededError("deployment-wide", deployment_limit, deployment_tokens, window)
    if user_limit > 0 and user_tokens + estimated_tokens > user_limit:
        raise QuotaExceededError("per-user", user_limit, user_tokens, window)


def reserve(
    engine: Engine,
    *,
    owner_id: uuid.UUID | None,
    provider: str,
    model: Optional[str],
    scope: str,
    input_hash: str,
    estimated_tokens: int,
) -> uuid.UUID:
    """Record the reservation and return its id. Written before the call."""
    usage_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO llm_usage (id, owner_id, provider, model, scope, input_hash,
                                       reserved_tokens, outcome)
                VALUES (:id, :owner, :provider, :model, :scope, :hash, :reserved, 'reserved')
                """
            ),
            {
                "id": usage_id,
                "owner": owner_id,
                "provider": provider,
                "model": model,
                "scope": scope,
                "hash": input_hash,
                "reserved": estimated_tokens,
            },
        )
    return usage_id


def settle(
    engine: Engine,
    usage_id: uuid.UUID,
    *,
    outcome: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    error: Optional[str] = None,
) -> None:
    """Record the real outcome. A failure keeps its reservation, which is the
    conservative direction: an interrupted request may still have been billed."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE llm_usage SET
                    outcome = :outcome,
                    prompt_tokens = :prompt,
                    completion_tokens = :completion,
                    total_tokens = :total,
                    error = :error,
                    settled_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": usage_id,
                "outcome": outcome,
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
                # Truncated: operational error identifiers only, never a provider
                # payload or a credential (AGENTS.md §12).
                "error": (error or "")[:300] or None,
            },
        )


def report(
    engine: Engine,
    *,
    window: str,
    user_limit: int,
    deployment_limit: int,
    owner_id: uuid.UUID | None,
    price_per_million_tokens: Optional[float] = None,
    currency: str = "USD",
) -> UsageReport:
    user_tokens, deployment_tokens, requests = used_tokens(engine, window, owner_id)
    with engine.connect() as conn:
        # A rejected answer (`invalid_output`) is a failure the user saw, so the
        # report counts it; the outcome vocabulary still distinguishes it in the
        # event log. Found 2026-09-15: the report said failures=0 while calls
        # were being refused.
        failures = int(
            conn.execute(
                text(
                    """
                    SELECT count(*) FROM llm_usage
                    WHERE created_at >= :start
                      AND outcome IN ('failed', 'auth_failed', 'rate_limited', 'timeout',
                                      'invalid_output')
                    """
                ),
                {"start": _window_start(window)},
            ).scalar_one()
        )
    cost = None
    note = (
        "No price is configured for this deployment, so no currency cost is reported. The token "
        "counts above are the measured usage."
    )
    if price_per_million_tokens is not None:
        cost = round(deployment_tokens / 1_000_000 * price_per_million_tokens, 4)
        note = (
            f"Estimated from the configured rate of {price_per_million_tokens} {currency} per "
            "million tokens and the recorded token usage; the provider's invoice is authoritative."
        )
    return UsageReport(
        window=window,
        user_tokens=user_tokens,
        user_limit=user_limit,
        deployment_tokens=deployment_tokens,
        deployment_limit=deployment_limit,
        requests=requests,
        failures=failures,
        estimated_cost=cost,
        currency=currency if cost is not None else None,
        cost_note=note,
    )


def recent_usage(engine: Engine, limit: int = 50) -> list[dict]:
    """Operational usage log: identifiers, scope, outcome, tokens. No payloads."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, owner_id, provider, model, scope, outcome,
                       reserved_tokens, prompt_tokens, completion_tokens, total_tokens,
                       error, created_at, settled_at
                FROM llm_usage ORDER BY created_at DESC LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
    return [
        {
            "id": str(r["id"]),
            "owner": str(r["owner_id"]) if r["owner_id"] else None,
            "provider": r["provider"],
            "model": r["model"],
            "scope": r["scope"],
            "outcome": r["outcome"],
            "reserved_tokens": r["reserved_tokens"],
            "prompt_tokens": r["prompt_tokens"],
            "completion_tokens": r["completion_tokens"],
            "total_tokens": r["total_tokens"],
            "error": r["error"],
            "created_at": r["created_at"].isoformat(),
            "settled_at": r["settled_at"].isoformat() if r["settled_at"] else None,
        }
        for r in rows
    ]
