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
    ff_rate_limit_recovery_per_hour: int = Field(default=5, ge=1)

    # media tools
    ff_enable_ytdlp: bool = False
    ff_enable_ffmpeg: bool = False

    # ---- Phase 2: credential vault, operator providers, quotas ----
    ff_credential_keys: str = ""  # "v1:<base64 32 bytes>[,v2:...]" — deployment secret kept outside the DB
    ff_credential_active_key: str = "v1"
    ff_enabled_providers: str = "ollama"  # operator-enabled provider ids offered to consumers
    ff_consumer_default_provider: str = ""  # default provider for new consumers ("" = first enabled)
    ff_byok_enabled: bool = True
    ff_daily_token_quota_default: int = Field(default=200_000, ge=0)
    ff_daily_call_quota_default: int = Field(default=200, ge=0)
    ff_daily_message_quota_default: int = Field(default=20, ge=0)
    ff_daily_spend_guard_usd: float = Field(default=5.0, ge=0.0)  # deployment-wide estimated AI spend per day
    ff_strict_cost_guard: bool = False  # block paid calls whose cost cannot be estimated
    # ---- Phase 2: account recovery mail (operator setup) ----
    ff_mail_mode: Literal["disabled", "capture", "smtp"] = "disabled"
    ff_smtp_host: str = ""
    ff_smtp_port: int = Field(default=587, ge=1, le=65535)
    ff_smtp_username: str = ""
    ff_smtp_password: str = ""  # noqa: S105
    ff_smtp_from: str = ""
    ff_smtp_starttls: bool = True
    ff_recovery_code_ttl_minutes: int = Field(default=15, ge=5, le=60)
    # ---- Phase 2: hosted collection ----
    ff_hosted_collection_enabled: bool = True
    ff_hosted_profiles_dir: str = ".focusfeed/hosted-profiles"
    ff_connect_session_ttl_minutes: int = Field(default=10, ge=2, le=30)
    ff_connect_frame_max_bytes: int = Field(default=150_000, ge=20_000, le=600_000)
    # ---- Phase 2: watches ----
    ff_watch_poll_minutes_default: int = Field(default=15, ge=5, le=1440)
    ff_public_app_url: str = "http://localhost:3000"
    # ---- Phase 2: WhatsApp (official Business Platform / Cloud API) ----
    ff_whatsapp_mode: Literal["disabled", "mock", "live"] = "disabled"
    wa_api_version: str = (
        "v23.0"  # confirm against Meta docs at deployment; not verifiable from the build environment
    )
    wa_verify_token: str = ""  # GET verification token (separate from the app secret)
    wa_app_secret: str = ""  # HMAC-SHA256 signature key for POST webhooks
    wa_access_token: str = ""  # system-user token for sending
    wa_phone_number_id: str = ""  # business sender id we send from and expect inbound on
    wa_business_account_id: str = ""
    wa_business_phone_e164: str = ""  # display number for wa.me deep links (digits only, e.g. 15551234567)
    wa_test_recipients: str = ""  # comma-separated allowlisted wa_ids for live tests
    wa_max_delivery_age_hours: int = Field(default=12, ge=1, le=72)
    wa_service_window_hours: int = Field(default=24, ge=1, le=24)

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
    def enabled_providers(self) -> list[str]:
        return [p.strip() for p in self.ff_enabled_providers.split(",") if p.strip()]

    @property
    def wa_test_recipient_list(self) -> list[str]:
        return [p.strip() for p in self.wa_test_recipients.split(",") if p.strip()]

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
            if not self.ff_credential_keys:
                problems.append("FF_CREDENTIAL_KEYS must be set in production (credential vault)")
            if self.ff_whatsapp_mode == "live" and not all(
                [self.wa_verify_token, self.wa_app_secret, self.wa_access_token, self.wa_phone_number_id]
            ):
                problems.append(
                    "FF_WHATSAPP_MODE=live requires WA_VERIFY_TOKEN, WA_APP_SECRET, WA_ACCESS_TOKEN and WA_PHONE_NUMBER_ID"
                )
            if self.ff_mail_mode == "capture":
                problems.append("FF_MAIL_MODE=capture is a development mode; use smtp or disabled")
            if self.ff_mail_mode == "smtp" and not (self.ff_smtp_host and self.ff_smtp_from):
                problems.append("FF_MAIL_MODE=smtp requires FF_SMTP_HOST and FF_SMTP_FROM")
            if problems:
                raise ValueError("Refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
