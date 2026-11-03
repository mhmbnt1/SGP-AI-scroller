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


class ScheduleOut(APIModel):
    id: uuid.UUID
    timezone: str
    local_time: str
    days_of_week: list[int]
    platforms: list[str]
    enabled: bool
    missed_run_policy: str
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


Platform_ = Platform  # re-export for routers
