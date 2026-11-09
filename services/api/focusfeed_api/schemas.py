"""Request/response models for the versioned API (bounded, explicit)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from ff_protocol import JobBudget, Platform
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Str120 = Annotated[str, Field(max_length=120)]
Str200 = Annotated[str, Field(max_length=200)]
Str500 = Annotated[str, Field(max_length=500)]

PLATFORM_CHOICES = ("youtube", "instagram", "tiktok", "x", "linkedin", "demo")


DeliveryChannel = Literal["app", "whatsapp"]
AvailabilityState = Literal[
    "ready", "not_configured", "disclosure_required", "quota_exhausted", "unavailable"
]


def _default_channels() -> list[DeliveryChannel]:
    return ["app"]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


# ---------------------------------------------------------------- auth / identity


class RegisterRequest(APIModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]
    display_name: Str120 = ""
    client: Literal["web", "mobile"] = "web"


class LoginRequest(APIModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=256)]
    client: Literal["web", "mobile"] = "web"


class UserOut(APIModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    onboarding_completed: bool
    created_at: datetime


class AuthResponse(APIModel):
    user: UserOut
    csrf_token: str | None = None
    access_token: str | None = None  # mobile clients only
    expires_at: datetime


class SessionOut(APIModel):
    id: uuid.UUID
    client_kind: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class MeOut(APIModel):
    user: UserOut
    mode: Literal["test", "demo", "live"]
    onboarding_state: Literal["new", "preferences_set", "complete"]
    has_preferences: bool
    has_collector: bool
    connected_platforms: list[str]


# ---------------------------------------------------------------- preferences


class PreferencesIn(APIModel):
    interests: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=30
    )
    exclusions: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=50
    )
    excluded_creators: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        default_factory=list, max_length=100
    )
    languages: list[Annotated[str, Field(min_length=2, max_length=16)]] = Field(
        default_factory=list, max_length=8
    )
    platforms: list[Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"]] = Field(
        default_factory=list, max_length=6
    )
    per_platform_limit: int = Field(default=5, ge=1, le=10)
    total_budget_minutes: int = Field(default=30, ge=5, le=240)
    consent_saved_signals: bool = False
    consent_feedback_learning: bool = True
    text_model: Str120 | None = None
    embedding_model: Str120 | None = None

    @field_validator("interests", "exclusions", "excluded_creators", "languages")
    @classmethod
    def _dedupe_strip(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for x in v:
            s = x.strip()
            if s and s.lower() not in {y.lower() for y in seen}:
                seen.append(s)
        return seen


class PreferencesOut(APIModel):
    interests: list[str]
    exclusions: list[str]
    excluded_creators: list[str]
    languages: list[str]
    platforms: list[str]
    per_platform_limit: int
    total_budget_minutes: int
    consent_saved_signals: bool
    consent_feedback_learning: bool
    text_model: str | None
    embedding_model: str | None
    version: int
    updated_at: datetime


# ---------------------------------------------------------------- platforms / connections


class PlatformCapabilityOut(APIModel):
    platform: str
    display_name: str
    personalized_feed: bool
    public_search: bool
    extract_item: bool
    captions: bool
    status: Literal["implemented", "contract_only", "disabled", "synthetic"]
    live_verified: bool
    notes: str


class ConnectionOut(APIModel):
    id: uuid.UUID
    platform: str
    status: str
    status_detail: str
    enabled: bool
    device_id: uuid.UUID | None
    last_checked_at: datetime | None
    next_step: str


class ConnectionUpdate(APIModel):
    enabled: bool


# ---------------------------------------------------------------- collectors


class EnrollmentCreate(APIModel):
    display_name: Str120 = "My PC"


class EnrollmentOut(APIModel):
    enrollment_id: uuid.UUID
    code: str  # shown once to the authenticated user
    expires_at: datetime
    instructions: str


class EnrollmentExchange(APIModel):
    code: Annotated[str, Field(min_length=16, max_length=24)]
    os_name: Annotated[str, Field(max_length=40)] = ""
    collector_version: Annotated[str, Field(max_length=40)] = ""


class EnrollmentExchangeOut(APIModel):
    device_id: uuid.UUID
    device_credential: str  # shown once; collector stores it in OS keyring
    display_name: str
    api_base_hint: str


class DeviceOut(APIModel):
    id: uuid.UUID
    display_name: str
    os_name: str
    collector_version: str
    last_heartbeat_at: datetime | None
    revoked_at: datetime | None
    online: bool
    created_at: datetime


class HeartbeatIn(APIModel):
    collector_version: Annotated[str, Field(max_length=40)] = ""
    platform_status: dict[str, Annotated[str, Field(max_length=32)]] = Field(default_factory=dict)
    capabilities: list[dict[str, Any]] = Field(default_factory=list, max_length=8)

    @field_validator("platform_status")
    @classmethod
    def _known_platforms(cls, v: dict[str, str]) -> dict[str, str]:
        for k in v:
            if k not in PLATFORM_CHOICES:
                raise ValueError(f"unknown platform {k}")
        return v


class HeartbeatOut(APIModel):
    ok: bool
    server_time: datetime
    poll_seconds: int


class ClaimRequest(APIModel):
    platforms: list[Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"]] = Field(
        min_length=1, max_length=6
    )


class LeaseRenewIn(APIModel):
    lease_token: Annotated[str, Field(min_length=16, max_length=128)]


class LeaseOut(APIModel):
    job_id: uuid.UUID
    lease_expires_at: datetime
    cancel_requested: bool


class CollectorEventIn(APIModel):
    lease_token: Annotated[str, Field(min_length=16, max_length=128)]
    kind: Annotated[str, Field(min_length=1, max_length=48)]
    message: Annotated[str, Field(max_length=500)] = ""
    platform: Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"] | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- jobs


class JobCreate(APIModel):
    mode: Literal["daily", "search"] = "daily"
    query: Annotated[str, Field(min_length=2, max_length=500)] | None = None
    platforms: list[Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"]] | None = Field(
        default=None, max_length=6
    )
    budget: JobBudget | None = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)] | None = None


class JobAccepted(APIModel):
    job_id: uuid.UUID
    state: str
    created: bool
    poll_url: str


class JobOut(APIModel):
    id: uuid.UUID
    mode: str
    query: str | None
    platforms: list[str]
    state: str
    platform_states: dict[str, Any]
    source: str
    attempts: int
    stop_reason: str
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    batch_id: uuid.UUID | None
    progress: int  # 0..100 derived from state
    next_step: str


class JobEventOut(APIModel):
    seq: int
    kind: str
    message: str
    data: dict[str, Any]
    created_at: datetime


class JobDetailOut(JobOut):
    events: list[JobEventOut]
    budget: dict[str, Any]


class Page(APIModel):
    next_cursor: str | None = None


class JobListOut(Page):
    items: list[JobOut]


# ---------------------------------------------------------------- batches / recommendations


class ItemSummaryOut(APIModel):
    id: uuid.UUID
    platform: str
    external_id: str
    canonical_url: str
    creator_handle: str | None
    creator_name: str | None
    title: str | None
    caption: str | None
    language: str | None
    duration_seconds: int | None
    published_at: datetime | None
    thumbnail_url: str | None
    is_synthetic: bool


class RecommendationOut(APIModel):
    id: uuid.UUID
    rank: int
    platform: str
    score: float
    components: dict[str, float]
    explanation: str
    summary: str
    topics: list[str]
    analysis_kind: str
    estimated_seconds: int
    duration_known: bool
    seen: bool
    hidden: bool
    saved: bool
    item: ItemSummaryOut


class BatchOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    mode: str
    query: str | None
    generated_at: datetime
    completion_status: str
    platform_summary: dict[str, Any]
    total_estimated_seconds: int
    is_synthetic: bool
    consumed_at: datetime | None
    recommendations: list[RecommendationOut]


class BatchSummaryOut(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    mode: str
    query: str | None
    generated_at: datetime
    completion_status: str
    recommendation_count: int
    total_estimated_seconds: int
    is_synthetic: bool
    consumed_at: datetime | None


class BatchListOut(Page):
    items: list[BatchSummaryOut]


class TodayOut(APIModel):
    batch: BatchOut | None
    active_job: JobOut | None
    collector_status: Literal["not_paired", "online", "offline", "not_required"]
    message: str


# ---------------------------------------------------------------- items / evidence


class EvidenceOut(APIModel):
    id: uuid.UUID
    kind: str
    transcript_source: str
    coverage_ratio: float
    segments: list[dict[str, Any]]
    frames: list[dict[str, Any]]
    extraction_method: str
    language: str | None


class ItemDetailOut(APIModel):
    item: ItemSummaryOut
    evidence: list[EvidenceOut]
    analysis_kind: str
    coverage_label: str
    recommendation: RecommendationOut | None
    saved: bool
    feedback: list[str]


# ---------------------------------------------------------------- saved / feedback


class SaveIn(APIModel):
    item_id: uuid.UUID


class SavedOut(APIModel):
    item: ItemSummaryOut
    saved_at: datetime


class SavedListOut(Page):
    items: list[SavedOut]


class FeedbackIn(APIModel):
    item_id: uuid.UUID | None = None
    action: Literal["relevant", "not_relevant", "not_interested", "hide_creator", "seen"]
    creator_handle: Str200 | None = None
    platform: Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"] | None = None
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)] | None = None


class FeedbackOut(APIModel):
    id: uuid.UUID
    action: str
    item_id: uuid.UUID | None
    creator_handle: str | None
    created_at: datetime
    revoked_at: datetime | None


# ---------------------------------------------------------------- schedules


class ScheduleIn(APIModel):
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    local_time: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = "08:00"
    days_of_week: list[Annotated[int, Field(ge=0, le=6)]] = Field(
        default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], max_length=7
    )
    platforms: list[Literal["youtube", "instagram", "tiktok", "x", "linkedin", "demo"]] = Field(
        default_factory=list, max_length=6
    )
    enabled: bool = True
    missed_run_policy: Literal["run_once", "skip"] = "run_once"
    ready_by_time: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] | None = None
    lead_minutes: int = Field(default=60, ge=10, le=720)
    deliver_time: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] | None = None
    deliver_channels: list[DeliveryChannel] = Field(default_factory=_default_channels, max_length=2)


class ScheduleOut(APIModel):
    id: uuid.UUID
    timezone: str
    local_time: str
    days_of_week: list[int]
    platforms: list[str]
    enabled: bool
    missed_run_policy: str
    ready_by_time: str | None
    lead_minutes: int
    deliver_time: str | None
    deliver_channels: list[str]
    last_batch_id: uuid.UUID | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_job_id: uuid.UUID | None


# ---------------------------------------------------------------- models


class ModelOptionOut(APIModel):
    name: str
    purpose: Literal["text", "embedding", "vision"]
    available: bool
    is_default: bool
    capabilities: dict[str, Any]


class ModelsOut(APIModel):
    provider: str
    provider_healthy: bool
    provider_detail: str
    options: list[ModelOptionOut]
    resource_note: str


# ---------------------------------------------------------------- privacy


class DeleteAccountIn(APIModel):
    password: Annotated[str, Field(min_length=1, max_length=256)]
    confirm: Literal["DELETE"]


class ExportOut(APIModel):
    exported_at: datetime
    user: dict[str, Any]
    preferences: dict[str, Any] | None
    saved_items: list[dict[str, Any]]
    feedback: list[dict[str, Any]]
    batches: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    schedules: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    connections: list[dict[str, Any]]
    evidence_count: int
    note: str


class OkOut(APIModel):
    ok: bool = True
    message: str = ""


class RecoveryStatusOut(APIModel):
    available: bool
    note: str


class RecoveryRequestIn(APIModel):
    email: EmailStr


class RecoveryRequestOut(APIModel):
    ok: bool = True
    delivery: Literal["sent", "unavailable"]
    message: str


class RecoveryConfirmIn(APIModel):
    email: EmailStr
    code: Annotated[str, Field(min_length=6, max_length=16)]
    new_password: Annotated[str, Field(min_length=1, max_length=256)]


Platform_ = Platform  # re-export for routers


# ================================================================ Phase 2: AI providers


class ProviderOptionOut(APIModel):
    provider: str
    display_name: str
    help: str
    configured: bool
    external: bool
    models: list[dict[str, Any]]


class AiSelectionOut(APIModel):
    provider: str | None
    credential_mode: Literal["operator", "byok"]
    chat_model: str | None
    summary_model: str | None
    vision_model: str | None
    embedding_model: str | None
    byok_connection_id: uuid.UUID | None
    allow_fallback_to: list[str]
    external_disclosure_acknowledged: bool
    effective_label: str
    availability: AvailabilityState
    availability_detail: str


class AiSelectionIn(APIModel):
    provider: Literal["openai", "anthropic", "gemini", "xai", "ollama", "fake"]
    credential_mode: Literal["operator", "byok"] = "operator"
    chat_model: Str120 | None = None
    summary_model: Str120 | None = None
    vision_model: Str120 | None = None
    embedding_model: Str120 | None = None
    byok_connection_id: uuid.UUID | None = None
    allow_fallback_to: list[Annotated[str, Field(min_length=3, max_length=160)]] = Field(
        default_factory=list, max_length=3
    )
    acknowledge_external_processing: bool = False


class AiOptionsOut(APIModel):
    providers: list[ProviderOptionOut]
    selection: AiSelectionOut
    byok_enabled: bool
    disclosure_text: str


class UsageOut(APIModel):
    tokens_today: int
    calls_today: int
    messages_today: int
    cost_estimate_today_usd: float
    cost_unknown_calls_today: int
    token_quota: int
    call_quota: int
    message_quota: int
    cost_quota_usd: float | None
    note: str


class ConnectionCreateIn(APIModel):
    provider: Literal["openai", "anthropic", "gemini", "xai"]
    api_key: Annotated[str, Field(min_length=8, max_length=512)]
    label: Str120 = ""
    enabled_models: list[Str120] = Field(default_factory=list, max_length=20)


class ProviderConnectionOut(APIModel):
    id: uuid.UUID
    scope: str
    provider: str
    display_name: str
    label: str
    key_hint: str
    status: str
    last_tested_at: datetime | None
    last_error: str
    enabled_models: list[str]
    created_at: datetime


class ConnectionTestIn(APIModel):
    model: Str120 | None = None


class ConnectionTestOut(APIModel):
    ok: bool
    status: str
    model: str
    latency_ms: int | None = None
    request_id: str | None = None
    error: str | None = None


class EntitlementIn(APIModel):
    daily_token_quota: int = Field(ge=0, le=50_000_000)
    daily_call_quota: int = Field(ge=0, le=100_000)
    daily_message_quota: int = Field(ge=0, le=10_000)
    daily_cost_quota_usd: float | None = Field(default=None, ge=0)
    allowed_providers: list[Str120] = Field(default_factory=list, max_length=6)
    trial_until: datetime | None = None
    note: Str500 = ""


class EntitlementOut(EntitlementIn):
    user_id: uuid.UUID


class AdminProvidersOut(APIModel):
    enabled_providers: list[str]
    connections: list[ProviderConnectionOut]
    env_keys_present: dict[str, bool]
    catalog: list[dict[str, Any]]
    deployment_cost_today_usd: float
    daily_spend_guard_usd: float
    vault_key_version: str


# ================================================================ Phase 2: sources / hosted connect


class SourceOut(APIModel):
    platform: str
    display_name: str
    implemented: bool
    personalized_feed: bool
    hosted_status: str
    next_step: str
    phone_only_support: str
    support_note: str
    live_verified: bool
    consent_at: datetime | None
    last_login_at: datetime | None
    last_checked_at: datetime | None
    collection_location: str


class CollectionLocationIn(APIModel):
    location: Literal["hosted", "local"]


class ConnectSessionCreateIn(APIModel):
    consent: bool = False


class ConnectSessionOut(APIModel):
    id: uuid.UUID
    platform: str
    state: str
    expires_at: datetime
    frame_seq: int
    frame_at: datetime | None
    current_url_host: str
    result_status: str
    ended_reason: str
    pending_inputs: int


class ConnectSessionStartOut(APIModel):
    session: ConnectSessionOut
    token: str
    poll_ms: int
    notice: str


class ConnectInputIn(APIModel):
    kind: Literal["tap", "type", "key", "scroll", "back"]
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    text: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    key: Annotated[str, Field(max_length=20)] | None = None
    dy: int | None = Field(default=None, ge=-2000, le=2000)


# ================================================================ Phase 2: watches


class WatchSourceIn(APIModel):
    type: Literal["rss"] = "rss"
    url: Annotated[str, Field(min_length=8, max_length=2000)]


class WatchIn(APIModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    topics: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=20
    )
    exclusions: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=20
    )
    languages: list[Annotated[str, Field(min_length=2, max_length=16)]] = Field(
        default_factory=list, max_length=8
    )
    sources: list[WatchSourceIn] = Field(default_factory=list, max_length=10)
    relevance_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    mode: Literal["digest", "alert"] = "digest"
    max_alerts_per_day: int = Field(default=3, ge=1, le=20)
    quiet_hours_start: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] | None = None
    quiet_hours_end: Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] | None = None
    poll_minutes: int = Field(default=15, ge=5, le=1440)
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "UTC"
    enabled: bool = True


class WatchOut(APIModel):
    id: uuid.UUID
    name: str
    topics: list[str]
    exclusions: list[str]
    languages: list[str]
    sources: list[dict[str, Any]]
    relevance_threshold: float
    mode: str
    max_alerts_per_day: int
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    poll_minutes: int
    timezone: str
    enabled: bool
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    last_error: str
    baseline_done: bool


class WatchDiscoveryOut(APIModel):
    id: uuid.UUID
    item_id: uuid.UUID
    title: str | None
    url: str
    relevance: float
    matched_terms: list[str]
    source_published_at: datetime | None
    discovered_at: datetime
    disposition: str
    source_name: str | None


# ================================================================ Phase 2: WhatsApp


class WhatsAppStatusOut(APIModel):
    transport_mode: str
    linked: bool
    display_hint: str | None
    linked_at: datetime | None
    proactive_opt_in: bool
    digest_enabled: bool
    alerts_enabled: bool
    paused_until: datetime | None
    opt_out_at: datetime | None
    in_service_window: bool
    templates_approved: dict[str, bool]
    eligibility_note: str
    external_disclosure_acknowledged: bool


class WhatsAppLinkStartOut(APIModel):
    code: str
    expires_at: datetime
    deep_link: str | None
    message_text: str
    instructions: str


class WhatsAppPreferencesIn(APIModel):
    proactive_opt_in: bool
    digest_enabled: bool = True
    alerts_enabled: bool = True
    paused_until: datetime | None = None
    acknowledge_external_processing: bool = False


class NotificationOut(APIModel):
    id: uuid.UUID
    kind: str
    proactive: bool
    state: str
    body_preview: str
    created_at: datetime
    not_before: datetime | None
    sent_at: datetime | None
    status_at: datetime | None
    attempts: int
    last_error: str
    related_batch_id: uuid.UUID | None
