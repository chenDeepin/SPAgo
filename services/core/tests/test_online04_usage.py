"""ONLINE-04 tests: usage accounting, quotas, readiness.

The accounting is the part that must not lie: a limit is enforced before a paid
call, a failed call keeps its reservation, a cache hit consumes nothing, and the
report never invents a currency cost when no price is configured.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from spago_core.main import create_app
from spago_core.services import ai, usage
from spago_core.services import auth as auth_svc


@pytest.fixture(scope="module")
def online_engine(seeded_engine):
    with seeded_engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_usage CASCADE"))
    return seeded_engine


@pytest.fixture(autouse=True)
def clean_usage(online_engine):
    with online_engine.begin() as conn:
        conn.execute(text("TRUNCATE llm_usage CASCADE"))
    yield


class TestQuotaEnforcement:
    def test_a_refused_request_says_which_limit_it_hit(self, online_engine):
        with pytest.raises(usage.QuotaExceededError) as exc:
            usage.check_quota(
                online_engine,
                owner_id=None,
                user_limit=100,
                deployment_limit=0,
                window="month",
                estimated_tokens=200,
            )
        assert exc.value.scope == "per-user"
        assert exc.value.limit == 100
        assert "no model request was sent" in str(exc.value)

    def test_the_deployment_limit_bounds_everyone(self, online_engine):
        with pytest.raises(usage.QuotaExceededError) as exc:
            usage.check_quota(
                online_engine,
                owner_id=None,
                user_limit=1_000_000,
                deployment_limit=50,
                window="month",
                estimated_tokens=100,
            )
        assert exc.value.scope == "deployment-wide"

    def test_the_user_limit_is_per_owner(self, online_engine):
        # Real users: the foreign key is a safety net against accounting rows
        # that belong to nobody.
        ada = auth_svc.create_user(online_engine, "quota-ada@example.org")
        bob = auth_svc.create_user(online_engine, "quota-bob@example.org")
        usage.reserve(
            online_engine,
            owner_id=ada,
            provider="recorded",
            model="m",
            scope="target",
            input_hash="h1",
            estimated_tokens=500,
        )
        usage.settle(online_engine, usage.recent_usage(online_engine, 1)[0]["id"], outcome="succeeded", total_tokens=500)
        # Ada is at her limit; Bob is unaffected.
        with pytest.raises(usage.QuotaExceededError):
            usage.check_quota(
                online_engine, owner_id=ada, user_limit=600, deployment_limit=0,
                window="month", estimated_tokens=200,
            )
        usage.check_quota(
            online_engine, owner_id=bob, user_limit=600, deployment_limit=0,
            window="month", estimated_tokens=200,
        )

    def test_an_unsettled_request_keeps_consuming_budget(self, online_engine):
        """An interrupted call may still have been billed, so its reservation
        must not silently free budget."""
        usage.reserve(
            online_engine,
            owner_id=None,
            provider="recorded",
            model="m",
            scope="family",
            input_hash="interrupted",
            estimated_tokens=1500,
        )
        user_tokens, deployment_tokens, requests = usage.used_tokens(online_engine, "month")
        assert user_tokens == 1500
        assert deployment_tokens == 1500
        assert requests == 1
        with pytest.raises(usage.QuotaExceededError):
            usage.check_quota(
                online_engine, owner_id=None, user_limit=1600, deployment_limit=0,
                window="month", estimated_tokens=200,
            )

    def test_settling_replaces_the_reservation_with_real_usage(self, online_engine):
        usage_id = usage.reserve(
            online_engine,
            owner_id=None,
            provider="recorded",
            model="m",
            scope="family",
            input_hash="settled",
            estimated_tokens=2000,
        )
        usage.settle(
            online_engine,
            usage_id,
            outcome="succeeded",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        user_tokens, _deployment, _requests = usage.used_tokens(online_engine, "month")
        assert user_tokens == 150

    def test_the_report_does_not_invent_a_cost(self, online_engine):
        usage.reserve(
            online_engine,
            owner_id=None,
            provider="recorded",
            model="m",
            scope="family",
            input_hash="cost",
            estimated_tokens=1000,
        )
        report = usage.report(
            online_engine, window="month", user_limit=10, deployment_limit=20, owner_id=None
        )
        assert report.estimated_cost is None
        assert report.currency is None
        assert "No price is configured" in report.cost_note

    def test_the_report_uses_the_configured_rate_when_given(self, online_engine):
        usage.reserve(
            online_engine,
            owner_id=None,
            provider="recorded",
            model="m",
            scope="family",
            input_hash="priced",
            estimated_tokens=1_000_000,
        )
        report = usage.report(
            online_engine,
            window="month",
            user_limit=0,
            deployment_limit=0,
            owner_id=None,
            price_per_million_tokens=3.0,
            currency="USD",
        )
        assert report.estimated_cost == 3.0
        assert report.currency == "USD"


class TestQuotaOnTheSummaryPath:
    def test_a_summary_over_quota_is_refused_before_the_provider(self, online_engine, monkeypatch):
        """The provider must not be called when the budget is exhausted."""
        calls = []

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "fp"

            def generate(self, snapshot):
                calls.append(snapshot)
                raise AssertionError("the provider must not be called when over quota")

        monkeypatch.setenv("SPAGO_LLM_USER_TOKEN_LIMIT", "10")
        monkeypatch.setenv("SPAGO_LLM_RESERVE_TOKENS", "1000")
        from spago_core.config import get_settings

        get_settings.cache_clear()
        try:
            with online_engine.connect() as conn:
                family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
            from spago_core.services import NotFoundError  # noqa: F401

            with pytest.raises(usage.QuotaExceededError):
                ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())
            assert calls == []
        finally:
            get_settings.cache_clear()

    def test_a_failed_call_records_why(self, online_engine):
        """The outcome vocabulary keeps failures distinguishable in the log.

        `invalid_output` means one specific thing: an answer arrived and SPAgo
        refused its *content*. A transport failure is `failed` (2026-09-16: the
        H8 drill recorded a `ConnectError` as `invalid_output`, which reads as
        "the model's answer was rejected" when the endpoint was never
        reached)."""
        assert ai._usage_outcome(ai.LLMAuthError()) == "auth_failed"
        assert ai._usage_outcome(ai.LLMTimeoutError()) == "timeout"
        assert ai._usage_outcome(ai.LLMUpstreamRateLimitError(5)) == "rate_limited"
        assert ai._usage_outcome(ai.LLMOutputRejectedError()) == "invalid_output"
        assert ai._usage_outcome(ai.LLMTransportError()) == "failed"
        assert ai._usage_outcome(ai.LLMUpstreamError()) == "failed"
        assert ai._usage_outcome(ai.AIError()) == "failed"

    def test_a_rejected_answer_settles_the_reservation(self, online_engine):
        """A provider answer that fails validation is a failed paid call.

        Regression for live finding 2026-09-15: validation ran outside the
        guarded region, so the row stayed at outcome='reserved' with a NULL
        settle time and kept consuming quota (used_tokens falls back to
        reserved_tokens)."""
        from spago_core.adapters.llm import ProviderOutput

        calls = []

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "fp"
            disable_thinking = True
            json_mode = True

            def generate(self, snapshot):
                calls.append(snapshot)
                # Valid JSON envelope, unknown fact ref: rejected by citations.
                return ProviderOutput(
                    content='{"paragraphs":[{"text":"x","fact_refs":["family:not-here"]}]}',
                    finish_reason="stop",
                    tool_calls=False,
                    usage={"total_tokens": 42},
                    model="recorded-model",
                )

        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        with pytest.raises(ai.LLMUpstreamError):
            ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())

        assert len(calls) == ai.MAX_LLM_ATTEMPTS, "the re-sample is bounded to one extra call"
        rows = usage.recent_usage(online_engine)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "invalid_output"
        assert rows[0]["settled_at"] is not None
        # The provider reported usage on both billed attempts, so the refused
        # pair settles with their sum (2 × 42) rather than only the reservation
        # — measured 2026-09-16: keeping the reservation let repeated refusals
        # under-count real spend on a target-sized prompt.
        assert rows[0]["total_tokens"] == 84
        # ...and the operator-facing report counts it as a failure.
        report = usage.report(
            online_engine, window="month", user_limit=200_000,
            deployment_limit=2_000_000, owner_id=None,
        )
        assert report.failures == 1

    def test_the_usage_log_holds_no_payload(self, online_engine):
        usage.reserve(
            online_engine,
            owner_id=None,
            provider="recorded",
            model="m",
            scope="family",
            input_hash="no-payload",
            estimated_tokens=100,
        )
        rows = usage.recent_usage(online_engine)
        allowed = {
            "id", "owner", "provider", "model", "scope", "outcome", "reserved_tokens",
            "prompt_tokens", "completion_tokens", "total_tokens", "error", "created_at",
            "settled_at",
        }
        assert set(rows[0]) == allowed


class TestBoundedRetry:
    """One re-sample after a content rejection of a completed response.

    Owner decision 2026-09-15 (docs/archive/2026-09-15-llm-live-smoke.md §9): both
    attempts were billed, so the settled row reports their sum and `attempts`;
    every failure that may not have been billed stays single-attempt.
    """

    @staticmethod
    def _provider(calls, answers, fingerprint="retry-fp"):
        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = fingerprint
            disable_thinking = True
            json_mode = True

            def generate(self, snapshot):
                calls.append(snapshot)
                return answers[min(len(calls) - 1, len(answers) - 1)](snapshot)

        return Provider()

    @staticmethod
    def _answer(content: str, total: int):
        from spago_core.adapters.llm import ProviderOutput

        return ProviderOutput(
            content=content,
            finish_reason="stop",
            tool_calls=False,
            usage={"prompt_tokens": total - 20, "completion_tokens": 20, "total_tokens": total},
            model="recorded-model",
        )

    def test_a_rejected_answer_is_re_sampled_once_and_both_calls_are_billed(self, online_engine):
        calls = []
        rejected = '{"paragraphs":[{"text":"x","fact_refs":["family:not-here"]}]}'

        def accepted(snapshot):
            refs = sorted(ai.allowed_refs(snapshot))
            return json.dumps(
                {
                    "paragraphs": [{"text": "Accepted on the second attempt.", "fact_refs": [refs[0]]}],
                    "limitations": ["Bounded input."],
                }
            )

        provider = self._provider(
            calls,
            [
                lambda snapshot: self._answer(rejected, 120),
                lambda snapshot: self._answer(accepted(snapshot), 140),
            ],
        )
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()

        result = ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=provider)

        assert len(calls) == 2, "the rejected answer must be re-sampled exactly once"
        assert result["cached"] is False
        assert "Accepted on the second attempt." in result["text"]
        assert result["usage"]["attempts"] == 2
        assert result["usage"]["total_tokens"] == 260  # both billed calls, summed
        rows = usage.recent_usage(online_engine)
        assert len(rows) == 1, "one user request keeps one reservation"
        assert rows[0]["outcome"] == "succeeded"
        assert rows[0]["total_tokens"] == 260

    def test_the_re_sample_is_bounded_and_the_row_still_settles(self, online_engine):
        calls = []
        rejected = '{"paragraphs":[{"text":"x","fact_refs":["family:not-here"]}]}'
        provider = self._provider(
            calls, [lambda snapshot: self._answer(rejected, 100)], fingerprint="bounded-fp"
        )
        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
            analyses_before = conn.execute(text("SELECT count(*) FROM ai_analyses")).scalar_one()

        with pytest.raises(ai.LLMOutputRejectedError):
            ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=provider)

        assert len(calls) == ai.MAX_LLM_ATTEMPTS == 2
        rows = usage.recent_usage(online_engine)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "invalid_output"
        assert rows[0]["settled_at"] is not None
        # The same provider answer (usage 100) was billed twice, so the refused
        # run settles with the measured 200 — not the pre-call reservation.
        assert rows[0]["total_tokens"] == 200
        with online_engine.connect() as conn:
            analyses_after = conn.execute(text("SELECT count(*) FROM ai_analyses")).scalar_one()
        assert analyses_after == analyses_before, "a rejected answer is never persisted"

    def test_an_unknown_attempt_usage_keeps_the_reservation_instead_of_a_partial_sum(
        self, online_engine
    ):
        """A partial sum would understate a real invoice (AGENTS.md §10)."""
        calls = []
        rejected = '{"paragraphs":[{"text":"x","fact_refs":["family:not-here"]}]}'

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "partial-fp"
            disable_thinking = True
            json_mode = True

            def generate(self, snapshot):
                calls.append(snapshot)
                if len(calls) == 1:
                    # First attempt: rejected, usage not reported by the provider.
                    from spago_core.adapters.llm import ProviderOutput

                    return ProviderOutput(
                        content=rejected, finish_reason="stop", tool_calls=False,
                        usage=None, model="recorded-model",
                    )
                refs = sorted(ai.allowed_refs(snapshot))
                return TestBoundedRetry._answer(
                    json.dumps(
                        {
                            "paragraphs": [{"text": "Retried.", "fact_refs": [refs[0]]}],
                            "limitations": [],
                        }
                    ),
                    140,
                )

        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        result = ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())

        assert len(calls) == 2
        assert result["usage"] is None
        rows = usage.recent_usage(online_engine)
        assert rows[0]["outcome"] == "succeeded"
        assert rows[0]["total_tokens"] is None
        # The reservation still covers the spend that could not be measured.
        user_tokens, _deployment, _requests = usage.used_tokens(online_engine, "month")
        assert user_tokens == rows[0]["reserved_tokens"] > 0

    def test_a_timeout_is_never_re_sampled(self, online_engine):
        calls = []

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "timeout-fp"

            def generate(self, snapshot):
                calls.append(snapshot)
                raise ai.LLMTimeoutError()

        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        with pytest.raises(ai.LLMTimeoutError):
            ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())

        assert len(calls) == 1, "a timed-out call may already have been billed"
        rows = usage.recent_usage(online_engine)
        assert rows[0]["outcome"] == "timeout"

    def test_an_upstream_429_is_never_re_sampled(self, online_engine):
        calls = []

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "throttled-fp"

            def generate(self, snapshot):
                calls.append(snapshot)
                raise ai.LLMUpstreamRateLimitError(7)

        with online_engine.connect() as conn:
            family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
        with pytest.raises(ai.LLMUpstreamRateLimitError):
            ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())

        assert len(calls) == 1, "throttling must not be hammered"
        rows = usage.recent_usage(online_engine)
        assert rows[0]["outcome"] == "rate_limited"

    def test_a_concurrent_refusal_leaves_no_reservation(self, online_engine, monkeypatch):
        """A request refused for concurrency never reached the provider, so it
        must not consume budget. Regression for the ordering defect found
        2026-09-15 while adding the retry (live-smoke record §9.3)."""
        calls = []

        class Provider:
            name = "recorded"
            provenance_state = ai.ProvenanceState.LLM_INFERRED
            model = "recorded-model"
            endpoint_fingerprint = "in-flight-fp"

            def generate(self, snapshot):  # pragma: no cover - must not be reached
                calls.append(snapshot)
                raise AssertionError("the provider must not be called")

        monkeypatch.setattr(ai, "compute_input_hash", lambda *a, **k: "in-flight-key")
        ai.clear_inflight()
        with ai._INFLIGHT_LOCK:
            ai._INFLIGHT.add("in-flight-key")
        try:
            with online_engine.connect() as conn:
                family_id = conn.execute(text("SELECT id FROM patent_families LIMIT 1")).scalar_one()
            with pytest.raises(ai.ContentInFlightError):
                ai.summarize_family(online_engine, family_id, mode="llm", llm_provider=Provider())
        finally:
            ai.clear_inflight()

        assert calls == []
        assert usage.recent_usage(online_engine) == []


class TestReadinessAndUsageApi:
    def test_readiness_reports_each_check(self, online_engine):
        app = create_app()
        app.state.engine = online_engine
        body = TestClient(app).get("/api/v1/readyz").json()
        assert body["status"] in {"ready", "not_ready"}
        assert set(body["checks"]) >= {
            "database",
            "chemistry",
            "migrations_applied",
            "rdkit_cartridge",
            "model_quota_configured",
        }

    def test_readiness_notes_an_unsafe_hosted_cookie_setting(self, online_engine, monkeypatch):
        """Readiness detail is operator-only: it names configuration problems, so
        it sits behind the session gate. The anonymous platform check is
        /healthz, which reveals nothing sensitive."""
        monkeypatch.setenv("SPAGO_AUTH_MODE", "required")
        monkeypatch.setenv("SPAGO_COOKIE_SECURE", "false")
        from spago_core.config import get_settings

        get_settings.cache_clear()
        try:
            app = create_app()
            app.state.engine = online_engine
            anonymous = TestClient(app)
            assert anonymous.get("/api/v1/readyz").status_code == 401

            admin_id = auth_svc.create_user(
                online_engine, "operator@example.org", is_admin=True
            )
            _invitation_id, token = auth_svc.create_invitation(online_engine, "operator@example.org")
            client = TestClient(app)
            redeemed = client.post("/api/v1/auth/invitations/redeem", json={"token": token})
            assert redeemed.status_code == 200, redeemed.text
            assert redeemed.json()["is_admin"] is True

            body = client.get("/api/v1/readyz").json()
            assert any("Secure flag" in note for note in body["notes"])
            # The public health endpoint stays reachable for the platform.
            assert client.get("/healthz").status_code == 200
            assert admin_id is not None
        finally:
            get_settings.cache_clear()

    def test_usage_endpoint_reports_the_callers_window(self, online_engine):
        app = create_app()
        app.state.engine = online_engine
        body = TestClient(app).get("/api/v1/usage").json()
        assert body["window"]
        assert body["user_limit"] > 0 and body["deployment_limit"] > 0
        assert body["estimated_cost"] is None

    def test_the_usage_event_log_is_admin_only(self, online_engine, monkeypatch):
        monkeypatch.setenv("SPAGO_AUTH_MODE", "required")
        from spago_core.config import get_settings

        get_settings.cache_clear()
        try:
            app = create_app()
            app.state.engine = online_engine
            client = TestClient(app)
            auth_svc.create_user(online_engine, "plain-user@example.org")
            _invitation, token = auth_svc.create_invitation(
                online_engine, "plain-user@example.org"
            )
            client.post("/api/v1/auth/invitations/redeem", json={"token": token})
            assert client.get("/api/v1/usage").status_code == 200
            assert client.get("/api/v1/usage/events").status_code == 403
        finally:
            get_settings.cache_clear()
