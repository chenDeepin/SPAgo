"""LLM contract corrections LLM-05/06/07 (plan `2026-09-14-llm-interface.md`).

Three groups:
- LLM-05: the bounded input snapshot — the budget applies to the annotated
  body, whole optional items are dropped, irreducible metadata fails loudly.
- LLM-06: the declared timeout is attached to the outbound request and a slow
  endpoint is really cut off. This uses a controllable local HTTP server on
  127.0.0.1 (no external network, no provider credentials).
- LLM-07: upstream 429 is distinct from a generic 502 and carries a validated
  Retry-After through to the HTTP response.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from spago_core.adapters.llm import (
    OpenAICompatibleSummaryProvider,
    parse_endpoint,
    parse_retry_after,
)
from spago_core.services import ai


# --- LLM-05: bounded input snapshot -------------------------------------------


def _facts(**overrides) -> dict:
    base = {
        "family": {"ref": "family:abc", "id": "abc", "family_key": "DEMO-FAMILY"},
        "document_count": 2,
        "compound_count": 12,
        "scaffolds": [{"scaffold": "c1ccccc1", "compounds": 3}],
        "scaffold_total": 1,
        "measurements": [],
        "measurement_total": 0,
        "evidence": [],
        "evidence_total": 0,
        "coverage": [{"dataset_version": "demo-v1", "synthetic": True, "documents": 2,
                      "compounds": 12, "measurements": 0}],
        "dataset_version": "demo-v1",
    }
    base.update(overrides)
    return base


def _size(snapshot: dict) -> int:
    return len(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _measurement(i: int, pad: int = 0) -> dict:
    return {
        "ref": f"measurement:{i:04d}",
        "inchikey": f"INCHIKEY-{i:04d}",
        "standard_type": "IC50",
        "relation": "=",
        "value": float(i),
        "unit": "nM",
        "assay_key": f"assay-{i}",
        "assay_type": "biochemical",
        "target_name": "CDK4",
        "source_name": "fixture",
        "dataset_version": "demo-v1",
        "provenance_state": "database_curated",
        **({"note": "x" * pad} if pad else {}),
    }


def _evidence(i: int, pad: int = 0) -> dict:
    return {
        "ref": f"evidence:{i:04d}",
        "evidence_id": f"{i:04d}",
        "publication_number": "DEMO-1",
        "source_type": "example",
        "section": f"Example {i}",
        "page": i,
        "excerpt": ("x" * pad) if pad else None,
    }


class TestSnapshotBudget:
    def test_untouched_snapshot_is_annotated_and_reported_included(self):
        snapshot, delta = ai.finalize_snapshot(_facts(measurements=[_measurement(1)]))
        assert _size(snapshot) <= ai.MAX_BODY_BYTES
        assert delta["included"] is True and delta["truncated"] is False
        assert snapshot["input_note"] == ai.INPUT_NOTE
        assert "measurement_omitted" not in snapshot

    def test_oversized_snapshot_is_trimmed_below_budget_including_annotations(self):
        """LLM-05: the note and omission counters are part of the checked body."""
        facts = _facts(
            measurements=[_measurement(i, pad=900) for i in range(50)],
            evidence=[_evidence(i, pad=900) for i in range(50)],
            scaffold_total=40,
            scaffolds=[{"scaffold": "C" * 400, "compounds": i} for i in range(20)],
            measurement_total=50,
            evidence_total=50,
        )
        snapshot, delta = ai.finalize_snapshot(facts)
        assert _size(snapshot) <= ai.MAX_BODY_BYTES
        assert delta["truncated"] is True and delta["included"] is False
        assert delta["omitted_measurements"] + delta["omitted_evidence"] > 0
        # The counters are inside the measured body, and they are honest.
        assert snapshot["measurement_omitted"] == delta["omitted_measurements"]
        assert snapshot["evidence_omitted"] == delta["omitted_evidence"]
        assert snapshot["scaffold_omitted"] == delta["omitted_scaffolds"]
        # No scientific value was rewritten while trimming.
        for m in snapshot["measurements"]:
            assert m["value"] == float(m["ref"].split(":")[1])
            assert m["unit"] == "nM"

    def test_multi_version_and_cjk_metadata_extend_the_checked_body(self):
        facts = _facts(
            coverage=[
                {"dataset_version": f"版本-{i}-" + "長" * 60, "synthetic": True,
                 "documents": 1, "compounds": 1, "measurements": 0}
                for i in range(40)
            ],
            dataset_version="mixed",
        )
        snapshot, delta = ai.finalize_snapshot(facts)
        assert _size(snapshot) <= ai.MAX_BODY_BYTES
        # coverage is required metadata: it is never dropped to make room.
        assert len(snapshot["coverage"]) == 40
        assert delta["included"] is True  # required metadata alone fits here

    def test_single_oversized_required_object_fails_without_trimming_facts(self):
        """The irreducible part alone exceeds the budget → explicit failure."""
        facts = _facts(
            family={"ref": "family:abc", "id": "abc", "family_key": "K" * (ai.MAX_BODY_BYTES + 512)},
            measurements=[_measurement(1)],
        )
        with pytest.raises(ai.SnapshotBudgetError):
            ai.finalize_snapshot(facts)

    def test_all_optional_items_are_removable_when_required_metadata_fits(self):
        facts = _facts(
            measurements=[_measurement(i) for i in range(50)],
            evidence=[_evidence(i) for i in range(50)],
            # One scaffold string larger than the whole budget: dropping the last
            # optional list must still bring the snapshot under the limit.
            scaffolds=[{"scaffold": "C" * (ai.MAX_BODY_BYTES + 64), "compounds": 1}],
            measurement_total=50,
            evidence_total=50,
        )
        snapshot, delta = ai.finalize_snapshot(facts)
        assert _size(snapshot) <= ai.MAX_BODY_BYTES
        assert snapshot["scaffolds"] == []
        assert snapshot["scaffold_omitted"] == delta["omitted_scaffolds"] == 1

    def test_utf8_excerpt_truncation_is_byte_bounded_and_reported(self):
        """Non-ASCII excerpts: 1 KiB is a byte budget, not a character count."""
        excerpt = "结" * 2000  # 3 bytes per character in UTF-8
        facts = _facts(evidence=[_evidence(1) | {"excerpt": excerpt}])
        snapshot, delta = ai.finalize_snapshot(facts)
        bounded = snapshot["evidence"][0]["excerpt"]
        assert len(bounded.encode("utf-8")) <= ai.MAX_EXCERPT_BYTES
        assert snapshot["evidence"][0]["excerpt_truncated"] is True
        assert delta["truncated_excerpts"] == 1
        assert delta["included"] is False
        assert bounded.startswith("结结")  # no split character at the tail

    def test_boundary_snapshot_just_under_budget_is_not_trimmed(self):
        item = _measurement(1)
        snapshot, _delta = ai.finalize_snapshot(_facts(measurements=[item]))
        used = _size(snapshot)
        assert used <= ai.MAX_BODY_BYTES
        # Padding to just below the budget keeps everything: no trim, no omission.
        pad = ai.MAX_BODY_BYTES - used - 64
        snapshot2, delta2 = ai.finalize_snapshot(
            _facts(measurements=[_measurement(1, pad=pad)], measurement_total=1)
        )
        assert _size(snapshot2) <= ai.MAX_BODY_BYTES
        assert _size(snapshot2) > ai.MAX_BODY_BYTES - 1024  # genuinely near the limit
        assert delta2["truncated"] is False
        assert delta2["omitted_measurements"] == 0
        assert len(snapshot2["measurements"]) == 1

    def test_offline_text_reports_partially_trimmed_measurements(self):
        facts = _facts(
            measurements=[_measurement(i, pad=2000) for i in range(50)],
            measurement_total=50,
        )
        snapshot, delta = ai.finalize_snapshot(facts)
        assert delta["omitted_measurements"] > 0
        assert snapshot["measurements"], "largest-list trimming keeps a balanced selection"
        text = ai.OfflineExtractiveProvider().summarize(snapshot)
        assert "No typed measurements exist" not in text
        assert f"{50} typed measurement" in text
        assert "are listed" in text

    def test_offline_text_with_all_measurements_omitted_still_reports_them(self):
        """A trimmed-away list must never be described as an absent one."""
        facts = _facts(
            measurements=[_measurement(1, pad=ai.MAX_BODY_BYTES + 512)],
            measurement_total=1,
        )
        snapshot, delta = ai.finalize_snapshot(facts)
        assert snapshot["measurements"] == [] and delta["omitted_measurements"] == 1
        text = ai.OfflineExtractiveProvider().summarize(snapshot)
        assert "No typed measurements exist" not in text
        assert "were omitted from this bounded summary" in text


# --- LLM-06: real timeout, real slow endpoint ---------------------------------


class _SlowHandler(BaseHTTPRequestHandler):
    """Local endpoint with controllable slowness. Never leaves 127.0.0.1."""

    protocol_version = "HTTP/1.1"
    mode = "ok"
    delay = 0.0
    chunk_gap = 0.0
    request_count = 0

    def do_POST(self):  # noqa: N802 (http.server API)
        type(self).request_count += 1
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.mode == "slow_first_byte":
            time.sleep(self.delay)
            self._send_ok()
        elif self.mode == "slow_trickle":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "800")
            self.end_headers()
            for _ in range(80):
                time.sleep(self.chunk_gap)
                try:
                    self.wfile.write(b"x" * 10)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
        else:
            self._send_ok()

    def _send_ok(self):
        body = json.dumps(
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "{\"paragraphs\": []}"},
                     "finish_reason": "stop"}
                ],
                "model": "slow-model",
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client cut the call off at its deadline

    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture()
def slow_endpoint():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _SlowHandler.mode = "ok"
    _SlowHandler.delay = 0.0
    _SlowHandler.chunk_gap = 0.0
    _SlowHandler.request_count = 0
    host, port = server.server_address
    yield f"http://127.0.0.1:{port}/v1", server
    server.shutdown()
    server.server_close()


def _provider_for(base: str, deadline: float) -> OpenAICompatibleSummaryProvider:
    endpoint = parse_endpoint(
        type("S", (), {"llm_base_url": base, "llm_model": "slow-model", "llm_api_key": None})()
    )
    return OpenAICompatibleSummaryProvider(endpoint, total_deadline_s=deadline)


SNAPSHOT = {
    "family": {"ref": "family:abc", "id": "abc", "family_key": "F"},
    "measurements": [],
    "evidence": [],
    "coverage": [],
    "dataset_version": "demo",
}


class TestRequestTimeoutBudget:
    def test_declared_budget_is_attached_to_the_request(self):
        """LLM-06: the client default (5 s read) must not decide model timing."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["timeout"] = request.extensions.get("timeout")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        endpoint = parse_endpoint(
            type("S", (), {"llm_base_url": "https://provider.example/v1",
                           "llm_model": "m", "llm_api_key": None})()
        )
        OpenAICompatibleSummaryProvider(endpoint, client=client, total_deadline_s=42.0).generate(
            SNAPSHOT
        )
        assert seen["timeout"]["read"] == 42.0
        assert seen["timeout"]["connect"] == 5.0
        assert seen["timeout"]["write"] == 10.0

    def test_first_byte_slower_than_deadline_is_cut_off(self, slow_endpoint):
        base, _server = slow_endpoint
        _SlowHandler.mode = "slow_first_byte"
        _SlowHandler.delay = 5.0
        started = time.monotonic()
        with pytest.raises(ai.LLMTimeoutError):
            _provider_for(base, 1.0).generate(SNAPSHOT)
        elapsed = time.monotonic() - started
        assert elapsed < 4.0, f"deadline not enforced: waited {elapsed:.1f}s"

    def test_continuously_slow_stream_is_cut_off_at_the_deadline(self, slow_endpoint):
        base, _server = slow_endpoint
        _SlowHandler.mode = "slow_trickle"
        _SlowHandler.chunk_gap = 0.05
        started = time.monotonic()
        with pytest.raises(ai.LLMTimeoutError):
            _provider_for(base, 1.0).generate(SNAPSHOT)
        elapsed = time.monotonic() - started
        # Deadline plus at most one inter-chunk gap; never the 5 s client default
        # and never an unbounded wait.
        assert elapsed < 3.0, f"trickle not cut off: {elapsed:.1f}s"

    def test_failure_releases_the_connection_and_client_stays_usable(self, slow_endpoint):
        base, _server = slow_endpoint
        _SlowHandler.mode = "slow_first_byte"
        _SlowHandler.delay = 5.0
        provider = _provider_for(base, 1.0)
        with pytest.raises(ai.LLMTimeoutError):
            provider.generate(SNAPSHOT)
        _SlowHandler.mode = "ok"
        assert _SlowHandler.request_count == 1
        out = provider.generate(SNAPSHOT)  # self-built client was closed cleanly
        assert out.model == "slow-model"
        assert _SlowHandler.request_count == 2


# --- LLM-07: upstream 429 ------------------------------------------------------


class TestRetryAfterParsing:
    def test_delta_seconds(self):
        assert parse_retry_after("7") == 7
        assert parse_retry_after(" 12 ") == 12
        assert parse_retry_after("0") == 0

    def test_http_date(self):
        now = 1_700_000_000.0
        assert parse_retry_after("Tue, 14 Nov 2023 22:13:30 GMT", now=now) == 10

    def test_absent_or_invalid_values_are_not_guessed(self):
        assert parse_retry_after(None) is None
        assert parse_retry_after("") is None
        assert parse_retry_after("soon") is None
        assert parse_retry_after("7.5") is None
        assert parse_retry_after("-3") is None


def _endpoint(base="https://provider.example/v1", model="demo-model"):
    return parse_endpoint(
        type("S", (), {"llm_base_url": base, "llm_model": model, "llm_api_key": None})()
    )


class TestUpstreamRateLimit:
    def _provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return OpenAICompatibleSummaryProvider(_endpoint(), client=client)

    def test_429_is_distinct_from_generic_upstream_failure(self):
        provider = self._provider(lambda r: httpx.Response(429, headers={"Retry-After": "7"}))
        with pytest.raises(ai.LLMUpstreamRateLimitError) as exc:
            provider.generate(SNAPSHOT)
        assert exc.value.status_code == 429
        assert exc.value.retry_after == 7
        assert "7s" in exc.value.detail

    def test_missing_or_invalid_retry_after_keeps_429_without_a_delay_claim(self):
        for headers in ({}, {"Retry-After": "later"}):
            provider = self._provider(lambda r: httpx.Response(429, headers=headers))
            with pytest.raises(ai.LLMUpstreamRateLimitError) as exc:
                provider.generate(SNAPSHOT)
            assert exc.value.retry_after is None
            assert "Retry-After" not in exc.value.detail

    def test_429_is_not_retried_automatically(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "3"})

        with pytest.raises(ai.LLMUpstreamRateLimitError):
            self._provider(handler).generate(SNAPSHOT)
        assert calls["n"] == 1

    def test_500_stays_a_generic_upstream_error(self):
        provider = self._provider(lambda r: httpx.Response(500))
        with pytest.raises(ai.LLMUpstreamError) as exc:
            provider.generate(SNAPSHOT)
        assert not isinstance(exc.value, ai.LLMUpstreamRateLimitError)
        assert exc.value.status_code == 502


class TestSummaryApiRateLimitMapping:
    """API-level mapping with the service call stubbed: the defect under test is
    the route's status/header mapping, not the provider (covered above)."""

    @pytest.fixture(autouse=True)
    def _configured_env(self, monkeypatch):
        from spago_core.config import get_settings

        monkeypatch.setenv("SPAGO_LLM_BASE_URL", "https://provider.example/v1")
        monkeypatch.setenv("SPAGO_LLM_MODEL", "demo-model")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def _client(self, monkeypatch, exc: Exception):
        from fastapi.testclient import TestClient

        from spago_core.services import ai as ai_module

        def _raise(*args, **kwargs):
            raise exc

        monkeypatch.setattr(ai_module, "summarize_family", _raise)

        from spago_core.main import create_app

        app = create_app()
        app.state.engine = object()  # never touched: the service call is stubbed
        return TestClient(app, raise_server_exceptions=False)

    def _post(self, client):
        return client.post(
            "/api/v1/families/00000000-0000-0000-0000-000000000001/summary",
            json={"mode": "llm"},
        )

    def test_upstream_429_returns_429_with_retry_after_header(self, monkeypatch):
        client = self._client(monkeypatch, ai.LLMUpstreamRateLimitError(7))
        res = self._post(client)
        assert res.status_code == 429
        assert res.headers.get("Retry-After") == "7"
        assert "7s" in res.json()["detail"]

    def test_upstream_429_without_valid_retry_after_has_no_header(self, monkeypatch):
        client = self._client(monkeypatch, ai.LLMUpstreamRateLimitError(None))
        res = self._post(client)
        assert res.status_code == 429
        assert "Retry-After" not in res.headers

    def test_snapshot_budget_failure_is_reported_and_not_a_502(self, monkeypatch):
        client = self._client(monkeypatch, ai.SnapshotBudgetError())
        res = self._post(client)
        assert res.status_code == 500
        assert "budget" in res.json()["detail"]

    def test_timeout_still_maps_to_504(self, monkeypatch):
        client = self._client(monkeypatch, ai.LLMTimeoutError())
        assert self._post(client).status_code == 504
