"""Application settings.

Three explicit modes (test/demo/live) and two environments (development/
production). Production refuses insecure defaults at import time so a
misconfigured deployment fails closed instead of running with a demo secret.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRETS = {"", "change-me", "change-me-development-only", "secret", "dev", "test"}


class RankingWeights(BaseSettings):
    """Initial weights are engineering heuristics, not learned parameters."""

    intent_relevance: float = 0.35
    interest_match: float = 0.25
    feedback_signal: float = 0.10
    freshness: float = 0.10
    novelty: float = 0.10
    evidence_quality: float = 0.10


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ff_mode: Literal["test", "demo", "live"] = "demo"
    ff_env: Literal["development", "production"] = "development"
    ff_secret_key: str = "change-me-development-only"  # noqa: S105

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/focusfeed"
    test_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/focusfeed_test"

    ff_allowed_origins: str = "http://localhost:3000"
    ff_cookie_secure: bool = False
    ff_cookie_name: str = "ff_session"
    ff_csrf_cookie_name: str = "ff_csrf"
    ff_session_ttl_hours: int = Field(default=168, ge=1, le=24 * 90)

    # providers
    ff_llm_provider: Literal["fake", "ollama"] = "fake"
    ollama_base_url: str = "http://localhost:11434"
    ff_text_models: str = "qwen2.5:7b-instruct,llama3.2:3b"
    ff_embedding_models: str = "nomic-embed-text"
    ff_vision_models: str = ""
    ff_default_text_model: str = "qwen2.5:7b-instruct"
    ff_default_embedding_model: str = "nomic-embed-text"
    ff_model_timeout_seconds: int = Field(default=180, ge=5, le=3600)
    ff_model_concurrency: int = Field(default=1, ge=1, le=8)
    ff_external_providers_enabled: bool = False

    # worker / jobs
    ff_worker_poll_seconds: float = Field(default=2.0, ge=0.1, le=60)
    ff_job_lease_seconds: int = Field(default=120, ge=15, le=3600)
    ff_retention_days: int = Field(default=30, ge=1, le=3650)
    ff_max_jobs_per_user_active: int = Field(default=2, ge=1, le=10)
    ff_ranking_weights_json: str = ""

    # rate limits (requests per window, in-process token buckets)
    ff_rate_limit_login_per_minute: int = Field(default=10, ge=1)
    ff_rate_limit_enroll_per_minute: int = Field(default=5, ge=1)
    ff_rate_limit_jobs_per_minute: int = Field(default=10, ge=1)

    # media tools
    ff_enable_ytdlp: bool = False
    ff_enable_ffmpeg: bool = False

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ff_allowed_origins.split(",") if o.strip()]

    @property
    def text_models(self) -> list[str]:
        return [m.strip() for m in self.ff_text_models.split(",") if m.strip()]

    @property
    def embedding_models(self) -> list[str]:
        return [m.strip() for m in self.ff_embedding_models.split(",") if m.strip()]

    @property
    def vision_models(self) -> list[str]:
        return [m.strip() for m in self.ff_vision_models.split(",") if m.strip()]

    @property
    def is_production(self) -> bool:
        return self.ff_env == "production"

    @property
    def ranking_weights(self) -> RankingWeights:
        if self.ff_ranking_weights_json:
            return RankingWeights(**json.loads(self.ff_ranking_weights_json))
        return RankingWeights()

    @field_validator("ff_secret_key")
    @classmethod
    def _secret_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("FF_SECRET_KEY must not be empty")
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.is_production:
            problems: list[str] = []
            if self.ff_secret_key in INSECURE_SECRETS or len(self.ff_secret_key) < 32:
                problems.append("FF_SECRET_KEY must be a random value of at least 32 characters")
            if not self.ff_cookie_secure:
                problems.append("FF_COOKIE_SECURE must be true")
            if self.ff_mode != "live":
                problems.append("FF_MODE must be 'live' in production (demo/test are development modes)")
            if "postgres:postgres@" in self.database_url:
                problems.append("DATABASE_URL must not use the default postgres/postgres credentials")
            if any(o.startswith("http://") for o in self.allowed_origins):
                problems.append("FF_ALLOWED_ORIGINS must be https in production")
            if problems:
                raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
