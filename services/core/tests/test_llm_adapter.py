"""LLM adapter contract tests (LLM interface plan §8 step B).

All calls run against httpx MockTransport — the test suite never touches an
external endpoint. Real-endpoint smoke remains a separate, explicitly
configured deployment step.
"""
from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from spago_core.adapters.llm import (
    LLMConfigProblem,
    OpenAICompatibleSummaryProvider,
    parse_endpoint,
)
from spago_core.services import ai as ai_svc
from spago_core.services.ai import LLMTimeoutError, LLMUpstreamError


def _endpoint(
    base="https://provider.example/v1",
    model="demo-model",
    api_key=None,
    disable_thinking=None,
    json_mode=None,
):
    settings = {
        "llm_base_url": base,
        "llm_model": model,
        "llm_api_key": api_key,
    }
    if disable_thinking is not None:
        settings["llm_disable_thinking"] = disable_thinking
    if json_mode is not None:
        settings["llm_json_mode"] = json_mode
    return parse_endpoint(type("S", (), settings)())


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

    def test_thinking_switch_defaults_off(self):
        """The minimal request subset stays the default: a stricter endpoint
        would reject an unknown parameter instead of ignoring it."""
        assert _endpoint().disable_thinking is False

    def test_thinking_switch_is_opt_in(self):
        assert _endpoint(disable_thinking=True).disable_thinking is True

    def test_json_mode_switch_defaults_off_and_is_opt_in(self):
        assert _endpoint().json_mode is False
        assert _endpoint(json_mode=True).json_mode is True


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


class TestPromptContract:
    def test_every_scope_states_the_schema_limits(self):
        """Live finding 2026-09-15: DeepSeek returned 6–9 limitation strings
        against the 5-item cap in 3/3 calls, because the instructions never
        stated it. Prompt and model must share one source of truth."""
        for scope in ("family", "document", "target"):
            prompt = OpenAICompatibleSummaryProvider(_endpoint(), scope=scope)._system_prompt()
            assert f"at most {ai_svc.MAX_PARAGRAPHS} paragraphs" in prompt
            assert f"at most {ai_svc.MAX_LIMITATIONS} limitation strings" in prompt
            assert f"at most {ai_svc.MAX_LIMITATIONS}." in prompt
            # Headroom guidance: the target scope sat exactly on the paragraph
            # cap in 6/6 measured calls and broke it in 1 (2026-09-15).
            assert "merge closely related facts" in prompt

        # The schema rejects exactly what the instructions cap.
        with pytest.raises(ValidationError):
            ai_svc.LlmSummaryOutput.model_validate(
                {
                    "paragraphs": [{"text": "t", "fact_refs": ["family:x"]}],
                    "limitations": ["x"] * (ai_svc.MAX_LIMITATIONS + 1),
                }
            )


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

    def test_thinking_disabled_adds_only_the_documented_parameter(self):
        """Opt-in finding 2026-09-15: a model that reasons by default spent the
        whole output budget on hidden reasoning and returned empty content."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json=_completion(VALID_OUTPUT))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleSummaryProvider(
            _endpoint(disable_thinking=True), client=client
        )
        provider.generate(SNAPSHOT)
        assert seen["body"]["thinking"] == {"type": "disabled"}
        assert set(seen["body"].keys()) == {
            "model", "messages", "stream", "max_tokens", "thinking",
        }
        assert provider.disable_thinking is True

    def test_json_mode_adds_the_response_format_parameter(self):
        """Live finding 2026-09-15: the model dropped the closing bracket of the
        final array in 2/6 family calls; JSON decoding mode removes that class of
        malformed output."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json=_completion(VALID_OUTPUT))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleSummaryProvider(_endpoint(json_mode=True), client=client)
        provider.generate(SNAPSHOT)
        assert seen["body"]["response_format"] == {"type": "json_object"}
        assert set(seen["body"].keys()) == {
            "model", "messages", "stream", "max_tokens", "response_format",
        }
        assert provider.json_mode is True

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

    def test_rejection_detail_names_the_failing_rule(self):
        """A rejected answer must say which rule broke.

        The detail reaches the operator's 502 and the usage ledger; the generic
        message cost a manual diff of the raw answer on 2026-09-15, when a
        dropped closing delimiter looked the same as an over-long list.
        """
        from spago_core.services.ai import _validate_llm_output

        # Malformed JSON: the model closed the object before the last array and
        # appended the leftovers (the class observed live on the target scope).
        malformed = '{"paragraphs":[{"text":"T.","fact_refs":["family:abc"]}],"limitations":["x."}]}'
        with pytest.raises(LLMUpstreamError, match=r"schema validation \(json_invalid\)"):
            _validate_llm_output(self._result(malformed), SNAPSHOT)

        # A well-formed answer that breaks a declared bound says so too.
        too_long = json.dumps(
            {
                "paragraphs": [{"text": "T.", "fact_refs": ["family:abc"]}],
                "limitations": ["a.", "b.", "c.", "d.", "e.", "f."],
            }
        )
        with pytest.raises(LLMUpstreamError, match=r"schema validation \(too_long\)"):
            _validate_llm_output(self._result(too_long), SNAPSHOT)

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


class TestRetryClassification:
    """Only a completed, billed answer whose content is unusable may be
    re-sampled (owner decision 2026-09-15; see
    docs/archive/2026-09-15-llm-live-smoke.md §9). Everything else stays
    single-attempt: an unknown charge must not be multiplied."""

    def test_unusable_content_of_a_completed_response_is_re_samplable(self):
        empty = _provider_with_handler(lambda r: httpx.Response(200, json=_completion("")))
        with pytest.raises(ai_svc.LLMOutputRejectedError, match="empty content"):
            empty.generate(SNAPSHOT)

        truncated = _provider_with_handler(
            lambda r: httpx.Response(200, json=_completion(VALID_OUTPUT, finish_reason="length"))
        )
        with pytest.raises(ai_svc.LLMOutputRejectedError, match="did not finish"):
            truncated.generate(SNAPSHOT)

    def test_service_validation_rejections_are_re_samplable(self):
        bad = json.dumps(
            {
                "paragraphs": [{"text": "x", "fact_refs": ["family:not-here"]}],
                "limitations": [],
            }
        )
        with pytest.raises(ai_svc.LLMOutputRejectedError, match="outside the allowed"):
            ai_svc._validate_llm_output(TestOutputValidation()._result(bad), SNAPSHOT)

    def test_protocol_and_transport_failures_are_not_re_samplable(self):
        big = VALID_OUTPUT + " " * (256 * 1024 + 10)

        def unanswered(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("too slow")

        handlers = {
            "body not JSON": lambda r: httpx.Response(200, text="<html>nope</html>"),
            "no choices": lambda r: httpx.Response(200, json={"choices": []}),
            "tool calls": lambda r: httpx.Response(
                200,
                json=_completion(VALID_OUTPUT, tool_calls=[{"id": "t"}], finish_reason="tool_calls"),
            ),
            "http 400": lambda r: httpx.Response(400, json={"error": "bad"}),
            "http 500": lambda r: httpx.Response(500),
            "response too large": lambda r: httpx.Response(200, json=_completion(big)),
            "timeout": unanswered,
        }
        for label, handler in handlers.items():
            provider = _provider_with_handler(handler)
            with pytest.raises(ai_svc.AIError) as exc:
                provider.generate(SNAPSHOT)
            assert not isinstance(exc.value, ai_svc.LLMOutputRejectedError), label

    def test_a_tool_calls_violation_is_not_re_sampled_even_in_the_service(self):
        """Re-asking a model that tried to use tools invites the same violation
        (AGENTS.md §12), so this rejection stays outside the retry class."""
        from spago_core.adapters.llm import ProviderOutput

        result = ProviderOutput(
            content=VALID_OUTPUT, finish_reason="stop", tool_calls=True, usage=None, model="m"
        )
        with pytest.raises(ai_svc.LLMUpstreamError) as exc:
            ai_svc._validate_llm_output(result, SNAPSHOT)
        assert not isinstance(exc.value, ai_svc.LLMOutputRejectedError)
