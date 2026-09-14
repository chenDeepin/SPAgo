"""OpenAI-compatible Chat Completions summary provider (LLM interface plan).

Deliberately small: one active endpoint, one model, a fixed request subset
(model / messages / stream:false / max_tokens), strict response validation,
and hard budgets. Credentials go only to the configured endpoint; no cookie
or Authorization forwarding, no redirect following, no automatic retries
(read timeout may already have been billed upstream).

base_url convention (verified against the CursorSwitch source, see plan §2):
the configured URL carries the full API prefix (usually including the version
segment); this adapter appends exactly `/chat/completions`.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from spago_core.domain import ProvenanceState
from spago_core.services.ai import (
    LLMAuthError,
    LLMTimeoutError,
    LLMUpstreamError,
    MAX_OUTPUT_TOKENS,
)

# Budgets (plan §4). read timeout is a per-read bound, not the total deadline;
# the deadline is enforced around the whole call.
CONNECT_TIMEOUT_S = 5.0
TOTAL_DEADLINE_S = 60.0
MAX_RESPONSE_BYTES = 256 * 1024

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "host.docker.internal"}


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

    return LLMEndpointConfig(base_url=base_url, api_key=api_key, model=model)


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
    256 KiB response cap; zero automatic retries."""

    name = "llm-openai-compatible"
    provenance_state = ProvenanceState.LLM_INFERRED

    def __init__(
        self,
        endpoint: LLMEndpointConfig,
        client: httpx.Client | None = None,
        prompt_version: str = "family-summary-v2",
        total_deadline_s: float = TOTAL_DEADLINE_S,
    ) -> None:
        self.endpoint = endpoint
        self.model = endpoint.model
        self.endpoint_fingerprint = endpoint.endpoint_fingerprint
        self._client = client
        self._prompt_version = prompt_version
        self._deadline_s = total_deadline_s

    @property
    def request_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(connect=5.0, read=self._deadline_s, write=10.0, pool=5.0)

    def _system_prompt(self) -> str:
        return (
            "You are a medicinal-chemistry patent analysis assistant. You write a "
            "structured summary of a patent family from the provided facts only.\n"
            "Rules:\n"
            "1. Use ONLY the facts in the provided JSON input. Never invent "
            "structures, values, patent numbers, targets, or claims.\n"
            "2. Answer with a single JSON object, no markdown fences, of the form:\n"
            '{"paragraphs":[{"text":"...","fact_refs":["..."]}],"limitations":["..."]}\n'
            "3. Every fact paragraph must cite at least one fact_ref copied exactly "
            "from the input's refs (family:..., measurement:..., evidence:...).\n"
            "4. Never treat a measurement record as patent-text evidence.\n"
            "5. Do not rank values across different assays or compute selectivity.\n"
            "6. List honest limitations (e.g. missing measurements, bounded input)."
        )

    def _user_prompt(self, snapshot: dict) -> str:
        return (
            "Summarize the following patent family facts. Copy fact_ref values "
            "exactly from the input.\n\n"
            + json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )

    def generate(self, snapshot: dict) -> ProviderOutput:
        started = time.monotonic()
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
        request = client.build_request(
            "POST",
            self.endpoint.chat_url,
            json=body,
            headers=headers,
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
                retry_after = response.headers.get("Retry-After")
                raise LLMUpstreamError(
                    f"Model endpoint rate limited the request"
                    + (f" (Retry-After: {retry_after}s)" if retry_after else "")
                )
            if response.status_code == 400:
                raise LLMUpstreamError(
                    "Model endpoint rejected the request parameters; this endpoint may "
                    "not support the required Chat Completions subset."
                )
            if response.status_code >= 400:
                raise LLMUpstreamError(f"Model endpoint returned HTTP {response.status_code}.")

            # Bounded read: never buffer more than MAX_RESPONSE_BYTES.
            chunks = []
            received = 0
            try:
                for chunk in response.iter_bytes():
                    received += len(chunk)
                    if received > MAX_RESPONSE_BYTES:
                        raise LLMUpstreamError("Model response exceeded the size limit.")
                    chunks.append(chunk)
                    if time.monotonic() - started > self._deadline_s:
                        raise LLMTimeoutError("Model response exceeded the total deadline.")
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
            raise LLMUpstreamError("Model returned empty content.")
        if message.get("tool_calls"):
            raise LLMUpstreamError("Model attempted tool calls; tool use is not allowed.")
        if choices[0].get("finish_reason") != "stop":
            raise LLMUpstreamError("Model did not finish normally.")
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
