"""LLM adapter contract tests (LLM interface plan §8 step B).

All calls run against httpx MockTransport — the test suite never touches an
external endpoint. Real-endpoint smoke remains a separate, explicitly
configured deployment step.
"""
from __future__ import annotations

import json

import httpx
import pytest

from spago_core.adapters.llm import (
    LLMConfigProblem,
    OpenAICompatibleSummaryProvider,
    parse_endpoint,
)
from spago_core.services.ai import LLMTimeoutError, LLMUpstreamError


def _endpoint(base="https://provider.example/v1", model="demo-model", api_key=None):
    return parse_endpoint(
        type(
            "S",
            (),
            {
                "llm_base_url": base,
                "llm_model": model,
                "llm_api_key": api_key,
            },
        )()
    )


def _completion(content: str, finish_reason="stop", tool_calls=None, usage=None, model="demo-model"):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    body = {"choices": [{"message": message, "finish_reason": finish_reason}], "model": model}
    if usage is not None:
        body["usage"] = usage
    return body


VALID_OUTPUT = json.dumps(
    {
        "paragraphs": [
            {
                "text": "The family contains 10 compounds.",
                "fact_refs": ["family:x"],
            }
        ],
        "limitations": ["Bounded input."],
    }
)


class TestEndpointConfig:
    def test_complete_config_parses(self):
        ep = _endpoint(api_key=None)
        assert ep.chat_url == "https://provider.example/v1/chat/completions"
        assert ep.model == "demo-model"

    def test_trailing_slash_not_duplicated(self):
        assert _endpoint(base="https://provider.example/v1/").chat_url.endswith("/v1/chat/completions")

    def test_arbitrary_path_prefix_allowed(self):
        # CursorSwitch-style deployments keep plan/version segments in the URL.
        assert _endpoint(base="https://host.example/api/plan/v3").chat_url.endswith(
            "/api/plan/v3/chat/completions"
        )

    def test_missing_model_is_config_problem(self):
        with pytest.raises(LLMConfigProblem):
            _endpoint(model="")

    def test_missing_base_url_is_config_problem(self):
        with pytest.raises(LLMConfigProblem):
            _endpoint(base="")

    def test_userinfo_rejected(self):
        with pytest.raises(LLMConfigProblem):
            _endpoint(base="https://user:pass@provider.example/v1")

    def test_query_and_fragment_rejected(self):
        with pytest.raises(LLMConfigProblem):
            _endpoint(base="https://provider.example/v1?x=1")
        with pytest.raises(LLMConfigProblem):
            _endpoint(base="https://provider.example/v1#frag")

    def test_public_http_rejected_private_http_allowed(self):
        with pytest.raises(LLMConfigProblem):
            _endpoint(base="http://provider.example/v1")
        # local deployments may explicitly point at loopback/private endpoints
        assert _endpoint(base="http://localhost:11434/v1").chat_url.startswith("http://localhost")
        assert _endpoint(base="http://127.0.0.1:11434/v1").chat_url.startswith("http://127.0.0.1")
        assert _endpoint(base="http://172.17.0.1:8101/v1").chat_url.startswith("http://172.17.0.1")

    def test_fingerprint_excludes_key_and_is_stable(self):
        a = _endpoint(api_key=None)
        b = _endpoint(api_key="sk-secret")
        assert a.endpoint_fingerprint == b.endpoint_fingerprint


def _provider_with_handler(handler, base="https://provider.example/v1"):
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="")
    endpoint = _endpoint(base=base)
    return OpenAICompatibleSummaryProvider(endpoint, client=client)


SNAPSHOT = {
    "family": {"ref": "family:abc", "id": "abc", "family_key": "F"},
    "measurements": [],
    "evidence": [],
    "coverage": [],
    "dataset_version": "demo",
}


class TestGenerate:
    def test_success_returns_text_usage_model(self):
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        provider = _provider_with_handler(
            lambda request: httpx.Response(200, json=_completion(VALID_OUTPUT, usage=usage))
        )
        out = provider.generate(SNAPSHOT)
        assert out.finish_reason == "stop"
        assert out.usage == usage
        assert out.model == "demo-model"
        assert "family contains" in out.content

    def test_request_sends_only_allowed_fields(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json=_completion(VALID_OUTPUT))

        provider = _provider_with_handler(handler, base="https://provider.example/v1")
        provider.generate(SNAPSHOT)
        assert seen["url"] == "https://provider.example/v1/chat/completions"
        assert seen["auth"] is None  # no key configured → no Authorization header
        assert set(seen["body"].keys()) == {"model", "messages", "stream", "max_tokens"}
        assert seen["body"]["stream"] is False

    def test_api_key_sent_as_bearer(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json=_completion(VALID_OUTPUT))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        endpoint = _endpoint(api_key="sk-secret")
        OpenAICompatibleSummaryProvider(endpoint, client=client).generate(SNAPSHOT)
        assert seen["auth"] == "Bearer sk-secret"

    def test_auth_failure_raises_auth_error(self):
        provider = _provider_with_handler(lambda request: httpx.Response(401, json={}))
        with pytest.raises(__import__("spago_core.services.ai", fromlist=["LLMAuthError"]).LLMAuthError):
            provider.generate(SNAPSHOT)

    def test_rate_limit_surfaces_retry_after(self):
        """LLM-07: upstream throttling is its own 429-mapped error carrying a
        validated Retry-After, not a generic 502."""
        from spago_core.services.ai import LLMUpstreamError, LLMUpstreamRateLimitError

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "7"})

        provider = _provider_with_handler(handler)
        with pytest.raises(LLMUpstreamRateLimitError) as exc:
            provider.generate(SNAPSHOT)
        assert exc.value.retry_after == 7
        assert exc.value.status_code == 429
        assert not issubclass(LLMUpstreamRateLimitError, LLMUpstreamError)
        assert "Retry-After: 7s" in exc.value.detail

    def test_400_reports_protocol_mismatch(self):
        provider = _provider_with_handler(lambda r: httpx.Response(400, json={"error": "bad"}))
        with pytest.raises(LLMUpstreamError, match="Chat Completions subset"):
            provider.generate(SNAPSHOT)

    def test_timeout_raises_deadline_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        provider = _provider_with_handler(handler)
        with pytest.raises(LLMTimeoutError):
            provider.generate(SNAPSHOT)

    def test_oversized_response_rejected(self):
        big = VALID_OUTPUT + " " * (256 * 1024 + 10)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_completion(big))

        provider = _provider_with_handler(handler)
        with pytest.raises(LLMUpstreamError, match="size limit"):
            provider.generate(SNAPSHOT)

    def test_invalid_json_rejected(self):
        provider = _provider_with_handler(lambda r: httpx.Response(200, text="<html>nope</html>"))
        with pytest.raises(LLMUpstreamError, match="invalid JSON"):
            provider.generate(SNAPSHOT)

    def test_empty_content_rejected(self):
        provider = _provider_with_handler(lambda r: httpx.Response(200, json=_completion("")))
        with pytest.raises(LLMUpstreamError, match="empty content"):
            provider.generate(SNAPSHOT)

    def test_tool_calls_rejected(self):
        provider = _provider_with_handler(
            lambda r: httpx.Response(
                200,
                json=_completion(VALID_OUTPUT, tool_calls=[{"id": "t"}], finish_reason="tool_calls"),
            )
        )
        with pytest.raises(LLMUpstreamError, match="tool calls"):
            provider.generate(SNAPSHOT)

    def test_non_stop_finish_rejected(self):
        provider = _provider_with_handler(
            lambda r: httpx.Response(200, json=_completion(VALID_OUTPUT, finish_reason="length"))
        )
        with pytest.raises(LLMUpstreamError, match="did not finish"):
            provider.generate(SNAPSHOT)

    def test_missing_usage_is_none_not_estimated(self):
        provider = _provider_with_handler(lambda r: httpx.Response(200, json=_completion(VALID_OUTPUT)))
        assert provider.generate(SNAPSHOT).usage is None

    def test_redirect_not_followed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://elsewhere.example/v1/chat/completions"})

        provider = _provider_with_handler(handler)
        with pytest.raises(LLMUpstreamError):
            provider.generate(SNAPSHOT)


class TestOutputValidation:
    def _result(self, content, **kw):
        from spago_core.adapters.llm import ProviderOutput

        return ProviderOutput(content=content, finish_reason="stop", tool_calls=False, usage=None, model="m")

    def test_unknown_fact_ref_rejected(self):
        bad = json.dumps(
            {
                "paragraphs": [
                    {"text": "Something.", "fact_refs": ["measurement:does-not-exist"]}
                ],
                "limitations": [],
            }
        )
        from spago_core.services.ai import _validate_llm_output

        with pytest.raises(LLMUpstreamError, match="outside the allowed"):
            _validate_llm_output(self._result(bad), SNAPSHOT)

    def test_paragraph_without_refs_rejected(self):
        bad = json.dumps({"paragraphs": [{"text": "Something.", "fact_refs": []}], "limitations": []})
        from spago_core.services.ai import _validate_llm_output

        with pytest.raises(LLMUpstreamError, match="schema validation"):
            _validate_llm_output(self._result(bad), SNAPSHOT)

    def test_valid_refs_pass(self):
        good = json.dumps(
            {
                "paragraphs": [{"text": "Something.", "fact_refs": ["family:abc"]}],
                "limitations": ["Bounded input."],
            }
        )
        from spago_core.services.ai import _validate_llm_output

        out = _validate_llm_output(self._result(good), SNAPSHOT)
        assert out.paragraphs[0].fact_refs == ["family:abc"]
