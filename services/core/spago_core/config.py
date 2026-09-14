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
    # LLM endpoint (LLM interface plan): all three unset → offline mode.
    # A SecretStr key is never logged or returned; empty key = unauthenticated
    # local endpoint (no Authorization header is sent).
    llm_base_url: str = ""
    llm_api_key: SecretStr | None = None
    llm_model: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
