"""B-11 (ungated half): the refusal class and the retry budget are visible.

The classes stay distinct server-side (transport, content rejection, throttle,
timeout); what this pins is the *reader-facing* statement — a 502 names which
class failed and whether another call will be billed, instead of a bare
"failed validation". A content rejection after the one allowed re-sample says
the budget is used; a transport failure says nothing was returned or billed.
"""
from __future__ import annotations

import pytest


class TestRefusalDetailMapping:
    """API-level mapping with the service call stubbed: the route's refusal
    wording is under test, not the provider (covered by test_llm_contract)."""

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

    def test_double_content_rejection_states_the_used_budget(self, monkeypatch):
        from spago_core.services import ai

        exc = ai.LLMOutputRejectedError("Model output failed JSON/schema validation (json_invalid).")
        exc.attempts = 2
        res = self._post(self._client(monkeypatch, exc))
        assert res.status_code == 502
        detail = res.json()["detail"]
        assert "Both attempts were rejected" in detail
        assert "retry budget" in detail
        assert "new billed call" in detail, "the reader must know another click costs"
        assert "no automatic retry" in detail

    def test_single_content_rejection_also_states_the_budget(self, monkeypatch):
        from spago_core.services import ai

        exc = ai.LLMOutputRejectedError("Model produced an empty paragraph.")
        exc.attempts = 1
        detail = self._post(self._client(monkeypatch, exc)).json()["detail"]
        assert "Both attempts" not in detail
        assert "retry budget" in detail and "billed call" in detail

    def test_transport_failure_says_nothing_was_billed(self, monkeypatch):
        from spago_core.services import ai

        exc = ai.LLMTransportError("Model endpoint request failed: ConnectError")
        exc.attempts = 1
        res = self._post(self._client(monkeypatch, exc))
        assert res.status_code == 502
        detail = res.json()["detail"]
        assert "never reached" in detail
        assert "nothing was returned or billed" in detail
        assert "billed call" in detail, "a retry is still a new call the reader chooses"

    def test_throttle_stays_429_and_distinct(self, monkeypatch):
        from spago_core.services import ai

        res = self._post(self._client(monkeypatch, ai.LLMUpstreamRateLimitError(7)))
        assert res.status_code == 429
        assert res.headers.get("Retry-After") == "7"

    def test_unshaped_upstream_failure_keeps_its_plain_detail(self, monkeypatch):
        """A generic upstream error (a tool-call violation, say) is not
        re-worded into a billing statement it cannot support."""
        from spago_core.services import ai

        exc = ai.LLMUpstreamError("Model attempted tool calls; tool use is not allowed.")
        detail = self._post(self._client(monkeypatch, exc)).json()["detail"]
        assert detail == "Model attempted tool calls; tool use is not allowed."


class TestAttemptAttachment:
    def test_attach_records_the_attempt_count_even_without_usage(self):
        from spago_core.services import ai

        exc = ai.LLMOutputRejectedError("Model produced an empty paragraph.")
        ai._attach_observed_usage(exc, [None], attempts=2)
        assert exc.attempts == 2, "the budget statement must not depend on observed usage"
