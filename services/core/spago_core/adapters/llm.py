"""OpenAI-compatible Chat Completions summary provider (LLM interface plan).

Deliberately small: one active endpoint, one model, a fixed request subset
(model / messages / stream:false / max_tokens, plus two opt-in compatibility
switches: `thinking: {"type": "disabled"}` for models that reason by default,
and `response_format: {"type": "json_object"}` for strict JSON decoding), strict
response validation, and hard budgets. Credentials go only to the configured endpoint; no cookie
or Authorization forwarding, no redirect following, and no transport retry of any kind
(a read timeout may already have been billed upstream, and throttling must not be hammered).
The only re-attempt in the system is one content re-sample performed by the service after a
*completed, billed* response was rejected — see `LLMOutputRejectedError`.

The declared budgets are attached to the outbound request (LLM-06): connect 5 s
and a read bound equal to the total deadline, so a stalled endpoint cannot hang
on a client default. The wall-clock deadline is checked before the call and
between stream chunks, so an endpoint that keeps trickling bytes cannot exceed
the deadline by more than one read window. Upstream rate limiting raises a
429-mapped error carrying a validated Retry-After (LLM-07).

base_url convention (verified against the CursorSwitch source, see plan §2):
the configured URL carries the full API prefix (usually including the version
segment); this adapter appends exactly `/chat/completions`.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from spago_core.domain import ProvenanceState
from spago_core.services.ai import (
    LLMAuthError,
    LLMOutputRejectedError,
    LLMTimeoutError,
    LLMUpstreamError,
    LLMUpstreamRateLimitError,
    MAX_LIMITATIONS,
    MAX_OUTPUT_TOKENS,
    MAX_PARAGRAPHS,
)

# Budgets (plan §4). read timeout is a per-read bound, not the total deadline;
# the deadline is enforced around the whole call.
CONNECT_TIMEOUT_S = 5.0
TOTAL_DEADLINE_S = 60.0
MAX_RESPONSE_BYTES = 256 * 1024

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "host.docker.internal"}


def parse_retry_after(value: str | None, *, now: float | None = None) -> int | None:
    """Validated Retry-After in whole seconds; None when absent or unusable.

    Accepts delta-seconds or an HTTP-date (RFC 9110). An unparseable value
    yields None rather than a guessed wait, so the API never advertises a
    fabricated delay.
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{1,9}", raw):
        return int(raw)
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc)
    return max(0, int((parsed - reference).total_seconds()))


def _is_private_or_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host in _LOOPBACK_HOSTS or host.endswith(".localhost"):
        return True
    # RFC1918 / CGNAT / link-local / docker-style private ranges count as
    # trusted intranet for explicitly configured plain-HTTP endpoints.
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        o = [int(p) for p in parts]
        if o[0] in (10, 127) or (o[0] == 172 and 16 <= o[1] <= 31) or (o[0] == 192 and o[1] == 168) or o[0] == 169 and o[1] == 254:
            return True
    return False


@dataclass(frozen=True)
class LLMEndpointConfig:
    base_url: str
    api_key: SecretStr | None
    model: str
    #: Opt-in, default off: send `thinking: {"type": "disabled"}`. Only for
    #: providers that document the parameter; unknown parameters are rejected
    #: by stricter OpenAI-compatible endpoints.
    disable_thinking: bool = False
    #: Opt-in, default off: send `response_format: {"type": "json_object"}`.
    json_mode: bool = False

    @property
    def chat_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @property
    def endpoint_fingerprint(self) -> str:
        """Sanitized identity of the target for cache keys: never includes the key."""
        parts = urlsplit(self.base_url)
        return hashlib.sha256(
            f"{parts.scheme}://{parts.netloc}{parts.path}".encode("utf-8")
        ).hexdigest()[:16]


class LLMConfigProblem(ValueError):
    """Raised when the configured endpoint is incomplete or violates the
    URL rules. Maps to HTTP 503 with the reason surfaced to the deployer."""


def parse_endpoint(settings) -> LLMEndpointConfig:
    base_url = (settings.llm_base_url or "").strip()
    model = (settings.llm_model or "").strip()
    api_key = settings.llm_api_key
    if isinstance(api_key, str):
        api_key = SecretStr(api_key) if api_key else None

    if not base_url and not model:
        raise LLMConfigProblem("No LLM endpoint configured (offline mode).")
    if bool(base_url) != bool(model):
        missing = "SPAGO_LLM_MODEL" if base_url else "SPAGO_LLM_BASE_URL"
        raise LLMConfigProblem(f"LLM configuration is incomplete: {missing} is missing.")

    parts = urlsplit(base_url)
    if parts.username or parts.password:
        raise LLMConfigProblem("LLM base URL must not contain userinfo.")
    if parts.query or parts.fragment:
        raise LLMConfigProblem("LLM base URL must not contain a query or fragment.")
    if parts.scheme == "https":
        pass
    elif parts.scheme == "http":
        # Plain HTTP is allowed only for explicitly configured loopback or
        # trusted intranet targets (local deployments); public HTTP is rejected.
        if not _is_private_or_loopback(parts.hostname or ""):
            raise LLMConfigProblem(
                "Plain HTTP is only allowed for loopback or private-network endpoints."
            )
    else:
        raise LLMConfigProblem("LLM base URL must use http or https.")

    return LLMEndpointConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        # getattr keeps the parser usable by callers that build a minimal
        # settings object (tests, embedded use).
        disable_thinking=bool(getattr(settings, "llm_disable_thinking", False)),
        json_mode=bool(getattr(settings, "llm_json_mode", False)),
    )


@dataclass(frozen=True)
class ProviderOutput:
    """Raw provider result before citation validation (ai.py owns that step)."""

    content: str
    finish_reason: str | None
    tool_calls: bool
    usage: dict | None
    model: str | None


class OpenAICompatibleSummaryProvider:
    """Chat Completions subset provider. Sync httpx; bounded timeouts; a
    256 KiB response cap; no transport retry (the service may re-sample one
    rejected answer, see `LLMOutputRejectedError`)."""

    name = "llm-openai-compatible"
    provenance_state = ProvenanceState.LLM_INFERRED

    def __init__(
        self,
        endpoint: LLMEndpointConfig,
        client: httpx.Client | None = None,
        #: Fallback only: the service passes PROMPT_VERSION_BY_SCOPE explicitly,
        #: and this must not drift from it (it was two versions stale).
        prompt_version: str = "family-summary-v6",
        total_deadline_s: float = TOTAL_DEADLINE_S,
        scope: str = "family",
    ) -> None:
        self.endpoint = endpoint
        self.model = endpoint.model
        self.endpoint_fingerprint = endpoint.endpoint_fingerprint
        #: Mirrored onto the provider so the cache key can include it: output
        #: produced with thinking is not the same analysis as output without it.
        self.disable_thinking = endpoint.disable_thinking
        self.json_mode = endpoint.json_mode
        self._client = client
        self._prompt_version = prompt_version
        self._deadline_s = total_deadline_s
        #: The summary scope this provider instance was configured for. It
        #: selects the instructions; the service records which scope was used.
        self.scope = scope

    @property
    def request_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=5.0, read=self._deadline_s, write=10.0, pool=5.0)

    #: Shared rules for every scope. Kept in one place so a new scope cannot
    #: silently drop a constraint that another scope already had to obey.
    _COMMON_RULES = (
        "1. Use ONLY the facts in the provided JSON input. Never invent "
        "structures, values, patent numbers, targets, assays or claims.\n"
        "2. Answer with a single JSON object, no markdown fences, of the form:\n"
        '{"paragraphs":[{"text":"...","fact_refs":["..."]}],"limitations":["..."]}\n'
        f"   Use at most {MAX_PARAGRAPHS} paragraphs and at most "
        f"{MAX_LIMITATIONS} limitation strings; prefer 6-10 short paragraphs "
        "and merge closely related facts rather than adding another one.\n"
        "3. Every fact paragraph must cite at least one fact_ref copied exactly "
        "from the input's refs; never emit an empty fact_refs list. Only the `ref` "
        "fields inside the input are fact refs: an input key such as `coverage`, "
        "`measurement_total` or `modality_breakdown` is not a ref, and an identifier "
        "you did not read in the input does not exist. For a coverage or totals "
        "statement (dataset version, per-source status, counts, breakdowns, bounded "
        "input), cite the input's root ref (`family:…`, `document:…` or `target:…`).\n"
        "4. Never treat a measurement record as patent-text evidence.\n"
        "5. Do not rank values across different assays or compute selectivity.\n"
        "6. Never state or imply that a target has no inhibitors, or that a "
        "compound is inactive, because a record is missing. Missing data is a "
        "coverage statement, not a scientific conclusion.\n"
        "7. List honest limitations (missing measurements, bounded input, "
        f"sources that failed or were not queried), at most {MAX_LIMITATIONS}."
    )

    def _system_prompt(self) -> str:
        if self.scope == "document":
            return (
                "You are a medicinal-chemistry patent analysis assistant. You write a "
                "structured summary of ONE patent document from the provided facts only.\n"
                "The facts cover this document alone: never mention or imply facts from "
                "other documents in the family, and never describe the document's family "
                "as a whole.\n"
                "If the input says claims were not assessed, state plainly that claims "
                "were not assessed; do not infer claim scope.\n"
                "Rules:\n" + self._COMMON_RULES
            )
        if self.scope == "target":
            return (
                "You are a medicinal-chemistry target analyst. You write a structured "
                "summary of a target investigation from open-database facts only.\n"
                "The input carries a per-source retrieval status. Treat it as part of the "
                "result: a source that returned nothing, failed, or was not queried is "
                "reported as such and is NOT evidence that no inhibitors exist.\n"
                "Each entry in `sources` (and its row in `coverage`) carries its own ref "
                "`source:<name>`: state that source's status, counts, exclusions, warnings "
                "or dataset version against that ref. Scope-level totals and the other "
                "aggregate fields belong to the target ref.\n"
                "Distinguish measured direct binding, interaction disruption, functional "
                "effects and screening data; a percent-inhibition readout is not proof of "
                "binding. Distinguish small molecules from peptides and biologics. A "
                "patent occurrence is not proof of inhibition, and its absence is not "
                "proof that a compound is unclaimed.\n"
                "Rules:\n" + self._COMMON_RULES
            )
        return (
            "You are a medicinal-chemistry patent analysis assistant. You write a "
            "structured summary of a patent family from the provided facts only.\n"
            "Rules:\n" + self._COMMON_RULES
        )

    def _user_prompt(self, snapshot: dict) -> str:
        subject = {
            "document": "patent document facts",
            "target": "target investigation facts",
        }.get(self.scope, "patent family facts")
        return (
            f"Summarize the following {subject}. Copy fact_ref values "
            "exactly from the input.\n\n"
            + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )

    def generate(self, snapshot: dict) -> ProviderOutput:
        started = time.monotonic()
        deadline = started + self._deadline_s
        client = self._client or httpx.Client()
        owns_client = self._client is None
        headers = {"Content-Type": "application/json", "User-Agent": "SPAgo/0.1"}
        key = self.endpoint.api_key
        if key is not None and key.get_secret_value():
            headers["Authorization"] = f"Bearer {key.get_secret_value()}"

        body = {
            "model": self.endpoint.model,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(snapshot)},
            ],
            "stream": False,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if self.endpoint.disable_thinking:
            # Documented DeepSeek-style switch. Required for models that reason
            # by default: hidden reasoning consumed the whole output budget and
            # the call returned no content at all (live finding 2026-09-15).
            body["thinking"] = {"type": "disabled"}
        if self.endpoint.json_mode:
            # OpenAI-standard decoding constraint. Live finding 2026-09-15:
            # without it the model sometimes dropped the closing bracket of the
            # final array and the whole summary was refused as invalid JSON.
            body["response_format"] = {"type": "json_object"}
        # The declared budget travels with the request; the client default
        # (5 s read) must not silently decide how long a model may think (LLM-06).
        request = client.build_request(
            "POST",
            self.endpoint.chat_url,
            json=body,
            headers=headers,
            timeout=self.request_timeout,
        )
        try:
            # Never follow redirects: an auth header must not be replayed elsewhere.
            response = client.send(request, stream=True, follow_redirects=False)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError("Model endpoint connection/read timed out.") from exc
        except httpx.HTTPError as exc:
            raise LLMUpstreamError(f"Model endpoint request failed: {type(exc).__name__}") from exc

        try:
            if response.status_code == 401 or response.status_code == 403:
                raise LLMAuthError("Model endpoint rejected authentication.")
            if response.status_code == 429:
                # Upstream throttling is not a generic upstream failure (LLM-07).
                raise LLMUpstreamRateLimitError(
                    parse_retry_after(response.headers.get("Retry-After"))
                )
            if response.status_code == 400:
                raise LLMUpstreamError(
                    "Model endpoint rejected the request parameters; this endpoint may "
                    "not support the required Chat Completions subset."
                )
            if response.status_code >= 400:
                raise LLMUpstreamError(f"Model endpoint returned HTTP {response.status_code}.")

            # Bounded read: never buffer more than MAX_RESPONSE_BYTES, and never
            # keep reading past the total deadline.
            chunks = []
            received = 0
            try:
                for chunk in response.iter_bytes():
                    if time.monotonic() > deadline:
                        raise LLMTimeoutError("Model response exceeded the total deadline.")
                    received += len(chunk)
                    if received > MAX_RESPONSE_BYTES:
                        raise LLMUpstreamError("Model response exceeded the size limit.")
                    chunks.append(chunk)
            except httpx.TimeoutException as exc:
                raise LLMTimeoutError("Model response read timed out.") from exc
            raw = b"".join(chunks)
        finally:
            response.close()
            if owns_client:
                client.close()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMUpstreamError("Model endpoint returned invalid JSON.") from exc

        choices = payload.get("choices") or []
        if not choices:
            raise LLMUpstreamError("Model response contains no choices.")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            # A completed response with unusable content: re-sampling is allowed
            # once by the service (`LLMOutputRejectedError`), since the call was
            # answered and billed (live finding 2026-09-15: a reasoning model
            # spent its whole budget and returned no content).
            raise LLMOutputRejectedError("Model returned empty content.")
        if message.get("tool_calls"):
            # Never retried: re-asking a model that tried to use tools invites
            # the same violation (tool use is not allowed, AGENTS.md §12).
            raise LLMUpstreamError("Model attempted tool calls; tool use is not allowed.")
        if choices[0].get("finish_reason") != "stop":
            # `length` and other non-stop finishes are answers SPAgo cannot use;
            # the response was received and billed, so one re-sample is allowed.
            raise LLMOutputRejectedError("Model did not finish normally.")
        tool_calls = False

        usage_raw = payload.get("usage")
        usage = None
        if isinstance(usage_raw, dict):
            usage = {
                k: usage_raw[k]
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                if isinstance(usage_raw.get(k), int)
            } or None

        return ProviderOutput(
            content=content,
            finish_reason=choices[0].get("finish_reason"),
            tool_calls=tool_calls,
            usage=usage,
            model=payload.get("model"),
        )
