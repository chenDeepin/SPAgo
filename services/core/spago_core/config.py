"""Application configuration from environment variables (SPAGO_ prefix)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPAGO_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://spago:spago@localhost:5432/spago"
    fixture_dir: Path = APP_ROOT / "data" / "fixtures"
    depiction_cache_dir: Path = APP_ROOT / "data" / "cache" / "depictions"
    migrations_dir: Path = APP_ROOT / "migrations"
    default_page_size: int = 100
    max_page_size: int = 500
    cors_origins: str = "http://localhost:5173,http://localhost:8000"
    # Deployment separation (PROD-01): "demo" loads the synthetic fixture at
    # startup so `docker compose up` works out of the box; "none" applies
    # migrations only — real deployments import source packages explicitly.
    seed_mode: str = "demo"
    # LLM endpoint (LLM interface plan): all three unset → offline mode.
    # A SecretStr key is never logged or returned; empty key = unauthenticated
    # local endpoint (no Authorization header is sent).
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = None
    llm_model: str = ""
    #: Opt-in request parameter for reasoning models that accept a `thinking`
    #: object (DeepSeek-style). Off by default: an unknown parameter makes
    #: stricter OpenAI-compatible endpoints reject the request, so the minimal
    #: subset stays the default. Live finding 2026-09-15: `deepseek-flash`
    #: reasons by default and spent the entire output budget on hidden
    #: reasoning, returning empty content. See
    #: docs/plans/2026-09-15-llm-live-smoke.md.
    llm_disable_thinking: bool = False
    #: Opt-in OpenAI-standard `response_format: {"type": "json_object"}`.
    #: Live finding 2026-09-15: without it the model occasionally dropped the
    #: closing `]` of the final array, producing invalid JSON that the adapter
    #: correctly refused. Off by default like every compatibility switch.
    llm_json_mode: bool = False

    # Hosted access (ONLINE-03, ADR-0002). "disabled" is the local
    # single-user product: one implicit local identity, unchanged behaviour and
    # unchanged existing rows. "required" is the hosted mode where every
    # workspace request needs a valid session and anonymous callers fail closed.
    auth_mode: str = "disabled"
    session_ttl_hours: int = 12
    invitation_ttl_hours: int = 72
    # Set true when the deployment is served over HTTPS so cookies are Secure.
    cookie_secure: bool = False
    #: Extra origin allowed to call the API from a browser (the hosted UI's own
    #: origin is same-origin and needs nothing here).
    cors_origins_extra: str = ""

    # Model-usage limits (ONLINE-04). Both default to a small non-zero bound so
    # a misconfigured deployment does not offer unlimited paid usage. 0 disables
    # a limit, which must be a deliberate choice.
    llm_user_token_limit: int = 200_000
    llm_deployment_token_limit: int = 2_000_000
    llm_quota_window: str = "month"
    #: Reserved before each call so a stalled request cannot consume unbounded
    #: budget; settled with the real usage afterwards.
    llm_reserve_tokens: int = 2_000
    #: Optional price for reporting an estimate. Unset = tokens only, no invented
    #: currency figure.
    llm_price_per_million_tokens: float | None = None
    llm_price_currency: str = "USD"

    # Potency reference policy (ONLINE-06). Both are part of the reported policy,
    # so a verdict and an export can be read back against the rule that produced
    # them. The threshold is the potency at or below which a compound counts as a
    # starting point; 10 µM matches the review convention this workflow uses.
    activity_threshold_nm: float = 10_000.0
    #: Below this many compounds a set with no active is described as sparse
    #: rather than merely negative. Shaping the reason only: one potent compound
    #: still qualifies.
    activity_min_compounds: int = 10

    @property
    def auth_required(self) -> bool:
        return (self.auth_mode or "disabled").strip().lower() == "required"

    @property
    def all_cors_origins(self) -> list[str]:
        return self.cors_origin_list + [
            o.strip() for o in (self.cors_origins_extra or "").split(",") if o.strip()
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
