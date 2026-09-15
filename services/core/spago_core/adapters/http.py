"""Shared bounded HTTP access for open-data adapters (ONLINE-00).

Every external source adapter needs the same guarantees (AGENTS.md §16):
timeout, rate limit, bounded retries that are safe for idempotent GETs,
a freshness-bounded response cache, and source identification. Centralizing
them here keeps each adapter's own code about *science*, not transport.

Deliberate limits:
- retries are GET/HEAD only, bounded, with exponential backoff and jitter, and
  only for connection errors, 429 and 5xx (never for 4xx);
- the cache is process-local and TTL-bounded: it is a rate-limit aid, not a
  scientific record. Durable records are written to PostgreSQL by the services;
- failures raise `SourceUnavailableError` so a caller records "failed" rather
  than an empty successful retrieval.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

DEFAULT_TIMEOUT_S = 25.0
DEFAULT_MAX_ATTEMPTS = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class SourceUnavailableError(RuntimeError):
    """The source could not answer. Callers must record this as `failed`, never
    as an empty result set (online-llm plan §2 ONLINE-00 C).

    `status_code` is preserved so a caller can treat a *documented* 404 (for
    example "no assay registered for this gene symbol") as an empty result
    rather than a failure — but only when the source semantics are known."""

    def __init__(self, source_name: str, message: str, status_code: int | None = None) -> None:
        self.source_name = source_name
        self.status_code = status_code
        super().__init__(f"{source_name}: {message}")


@dataclass
class _CacheEntry:
    expires_at: float
    status_code: int
    headers: dict[str, str]
    content: bytes


@dataclass
class SourceClient:
    """A rate-limited, cached, retrying GET client for one source."""

    source_name: str
    base_url: str = ""
    user_agent: str = "SPAgo/0.1 (+https://github.com/spago; research use)"
    timeout_s: float = DEFAULT_TIMEOUT_S
    min_interval_s: float = 0.2
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    cache_ttl_s: float = 900.0
    accept: str = "application/json"
    _client: Optional[httpx.Client] = None
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)
    _last_request_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    #: Number of upstream requests actually issued (cache hits excluded).
    request_count: int = 0

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout_s,
                follow_redirects=False,
                headers={"Accept": self.accept, "User-Agent": self.user_agent},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.min_interval_s:
                time.sleep(self.min_interval_s - elapsed)
            self._last_request_at = time.monotonic()

    def _cache_get(self, key: str) -> Optional[_CacheEntry]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.monotonic():
            self._cache.pop(key, None)
            return None
        return entry

    def get_json(self, url: str, params: Optional[dict[str, Any]] = None) -> Any:
        """GET JSON with caching, throttling and bounded retries.

        Raises `SourceUnavailableError` on any non-2xx or transport failure.
        A 404 is *not* special-cased into an empty result: the caller decides,
        and the status is preserved in the message.
        """
        key = url + "?" + repr(sorted((params or {}).items()))
        cached = self._cache_get(key)
        if cached is not None:
            return _decode_json(cached.content, self.source_name, cached.status_code)

        client = self._get_client()
        last_error: Optional[str] = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            self.request_count += 1
            try:
                response = client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_attempts:
                    _sleep_backoff(attempt)
                    continue
                raise SourceUnavailableError(self.source_name, last_error) from exc

            if response.status_code == 429 or 500 <= response.status_code < 600:
                last_error = f"HTTP {response.status_code}"
                if attempt < self.max_attempts:
                    _sleep_backoff(attempt, response.headers.get("Retry-After"))
                    continue
                raise SourceUnavailableError(
                    self.source_name, last_error, status_code=response.status_code
                )

            if response.status_code >= 400:
                raise SourceUnavailableError(
                    self.source_name,
                    f"HTTP {response.status_code} for {url}",
                    status_code=response.status_code,
                )

            content = response.content
            if len(content) > MAX_RESPONSE_BYTES:
                raise SourceUnavailableError(
                    self.source_name,
                    f"response of {len(content)} bytes exceeds the {MAX_RESPONSE_BYTES}-byte bound",
                )
            self._cache[key] = _CacheEntry(
                expires_at=time.monotonic() + self.cache_ttl_s,
                status_code=response.status_code,
                headers=dict(response.headers),
                content=content,
            )
            return _decode_json(content, self.source_name, response.status_code)
        raise SourceUnavailableError(self.source_name, last_error or "unknown failure")


def _decode_json(content: bytes, source_name: str, status_code: int) -> Any:
    import json

    if not content:
        raise SourceUnavailableError(source_name, f"empty response body (HTTP {status_code})")
    try:
        return json.loads(content)
    except ValueError as exc:
        # Sources in this family return HTML error pages with HTTP 200; that is
        # a source failure, not "no records" (observed for BindingDB IL6R).
        raise SourceUnavailableError(
            source_name,
            f"response was not JSON (HTTP {status_code}); the source may be unavailable "
            "or require a different access path",
        ) from exc


def _sleep_backoff(attempt: int, retry_after: Optional[str] = None) -> None:
    delay = min(8.0, 0.5 * (2 ** (attempt - 1)))
    if retry_after:
        try:
            delay = min(8.0, max(delay, float(retry_after)))
        except ValueError:
            pass
    time.sleep(delay + random.uniform(0, 0.2))
