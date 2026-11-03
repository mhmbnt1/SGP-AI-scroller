"""Typed DTOs shared by the API, worker and the local collector.

Design notes
------------
* Every string/array is bounded. The API validates results from collectors
  as untrusted input: a compromised collector must not be able to inject
  unbounded payloads or references to objects it does not own.
* ``CollectorResultState`` is the explicit, closed set of adapter outcomes the
  brief requires. ``partial`` carries whatever was extracted before the stop.
* ``EvidenceBundle`` describes what was *actually* analysed (coverage), so the
  ranking/summary stage can label analysis as metadata-only, transcript-
  supported, sampled-visual or combined — never "full video understanding".
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

ShortStr = Annotated[str, Field(min_length=1, max_length=200)]
MediumStr = Annotated[str, Field(max_length=2000)]
LongStr = Annotated[str, Field(max_length=20000)]


class Platform(StrEnum):
    youtube = "youtube"
    instagram = "instagram"
    tiktok = "tiktok"
    x = "x"
    linkedin = "linkedin"
    demo = "demo"


class CollectionMode(StrEnum):
    """Which capability produced a candidate. Never conflate these."""

    personalized_feed = "personalized_feed"  # authenticated home / recommendations feed
    public_search = "public_search"  # public search results
    public_url = "public_url"  # user-supplied URL ingestion
    user_import = "user_import"  # user-imported saved/shared content (opt-in)
    synthetic_fixture = "synthetic_fixture"  # demo / test fixtures, visibly labeled


class SessionStatus(StrEnum):
    available = "available"
    unsupported = "unsupported"
    needs_login = "needs_login"
    collector_offline = "collector_offline"
    rate_limited = "rate_limited"
    challenge_required = "challenge_required"
    upstream_changed = "upstream_changed"
    timeout = "timeout"
    cancelled = "cancelled"
    partial = "partial"
    failed = "failed"


class CollectorResultState(StrEnum):
    """Outcome of one platform within a collector job."""

    available = "available"
    unsupported = "unsupported"
    needs_login = "needs_login"
    collector_offline = "collector_offline"
    rate_limited = "rate_limited"
    challenge_required = "challenge_required"
    upstream_changed = "upstream_changed"
    timeout = "timeout"
    cancelled = "cancelled"
    partial = "partial"
    failed = "failed"


class TranscriptSource(StrEnum):
    platform_captions = "platform_captions"
    auto_captions = "auto_captions"
    local_asr = "local_asr"
    fixture = "fixture"
    none = "none"


class AnalysisKind(StrEnum):
    metadata_only = "metadata_only"
    transcript_supported = "transcript_supported"
    sampled_visual = "sampled_visual"
    combined = "combined"


class JobBudget(BaseModel):
    """Hard limits enforced *outside* any model. Conservative defaults."""

    model_config = ConfigDict(extra="forbid")

    max_candidates_per_platform: int = Field(default=40, ge=1, le=200)
    max_scroll_steps_per_platform: int = Field(default=12, ge=1, le=100)
    max_wall_clock_seconds: int = Field(default=600, ge=30, le=3600)
    per_stage_timeout_seconds: int = Field(default=120, ge=10, le=1800)
    max_model_calls: int = Field(default=60, ge=0, le=500)
    max_input_tokens: int = Field(default=60_000, ge=0, le=2_000_000)
    max_media_items: int = Field(default=10, ge=0, le=100)
    max_frames_per_item: int = Field(default=4, ge=0, le=24)
    max_download_bytes: int = Field(default=50_000_000, ge=0, le=2_000_000_000)
    max_analyzed_seconds: int = Field(default=600, ge=0, le=7200)
    max_retry_attempts: int = Field(default=2, ge=0, le=5)


class AdapterCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    personalized_feed: bool = False
    public_search: bool = False
    extract_item: bool = False
    captions: bool = False
    status: Literal["implemented", "contract_only", "disabled"] = "contract_only"
    notes: Annotated[str, Field(max_length=500)] = ""


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    text: Annotated[str, Field(max_length=2000)]

    @field_validator("end_s")
    @classmethod
    def _end_after_start(cls, v: float, info):  # type: ignore[no-untyped-def]
        start = info.data.get("start_s", 0.0)
        if v < start:
            raise ValueError("end_s must be >= start_s")
        return v


class FrameSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_s: float = Field(ge=0)
    observation: Annotated[str, Field(max_length=1000)] = ""
    sha256: Annotated[str | None, Field(max_length=64)] = None


class EvidenceBundle(BaseModel):
    """What was actually analysed for a candidate.

    ``coverage_ratio`` is the fraction of the item's duration covered by the
    transcript segments (0 when unknown).
    """

    model_config = ConfigDict(extra="forbid")

    transcript_source: TranscriptSource = TranscriptSource.none
    transcript_language: Annotated[str | None, Field(max_length=16)] = None
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list, max_length=2000)
    coverage_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    frame_samples: list[FrameSample] = Field(default_factory=list, max_length=64)
    missing_fields: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=32)
    extraction_method: Annotated[str, Field(max_length=120)] = "metadata"

    @property
    def analysis_kind(self) -> AnalysisKind:
        has_t = bool(self.transcript_segments)
        has_f = bool(self.frame_samples)
        if has_t and has_f:
            return AnalysisKind.combined
        if has_t:
            return AnalysisKind.transcript_supported
        if has_f:
            return AnalysisKind.sampled_visual
        return AnalysisKind.metadata_only


class CandidateItem(BaseModel):
    """One extracted content item with provenance and evidence."""

    model_config = ConfigDict(extra="forbid")

    platform: Platform
    external_id: Annotated[str, Field(min_length=1, max_length=200)]
    canonical_url: HttpUrl
    creator_handle: Annotated[str | None, Field(max_length=200)] = None
    creator_name: Annotated[str | None, Field(max_length=200)] = None
    title: Annotated[str | None, Field(max_length=1000)] = None
    caption: Annotated[str | None, Field(max_length=5000)] = None
    language: Annotated[str | None, Field(max_length=16)] = None
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)
    published_at: datetime | None = None
    observed_at: datetime
    collection_mode: CollectionMode
    feed_position: int | None = Field(default=None, ge=0, le=100_000)
    thumbnail_url: HttpUrl | None = None
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    raw_fingerprint: Annotated[str | None, Field(max_length=64)] = None

    @field_validator("canonical_url", "thumbnail_url")
    @classmethod
    def _https_only(cls, v: HttpUrl | None) -> HttpUrl | None:
        if v is not None and v.scheme not in ("https", "http"):
            raise ValueError("only http(s) URLs are allowed")
        return v


class PlatformResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Platform
    state: CollectorResultState
    collection_mode: CollectionMode
    items: list[CandidateItem] = Field(default_factory=list, max_length=200)
    scroll_steps: int = Field(default=0, ge=0, le=1000)
    stop_reason: Annotated[str, Field(max_length=500)] = ""
    checkpoint_external_ids: list[Annotated[str, Field(max_length=200)]] = Field(
        default_factory=list, max_length=1000
    )
    diagnostics: dict[str, Annotated[str, Field(max_length=500)]] = Field(default_factory=dict)

    @field_validator("diagnostics")
    @classmethod
    def _bounded_diag(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 32:
            raise ValueError("too many diagnostic keys")
        return v


class CollectorJobInstruction(BaseModel):
    """What the API hands to a collector when it claims a job.

    This is a *typed instruction*, never free text. The collector refuses
    anything it cannot validate.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = "1.0"
    job_id: str
    lease_token: Annotated[str, Field(min_length=16, max_length=128)]
    lease_expires_at: datetime
    mode: Literal["daily", "search"]
    platforms: list[Platform] = Field(min_length=1, max_length=6)
    query: Annotated[str | None, Field(max_length=500)] = None
    preferred_languages: list[Annotated[str, Field(max_length=16)]] = Field(default_factory=list, max_length=8)
    budget: JobBudget = Field(default_factory=JobBudget)
    checkpoint_external_ids: dict[str, list[str]] = Field(default_factory=dict)
    allowed_domains: list[Annotated[str, Field(max_length=100)]] = Field(default_factory=list, max_length=32)


class CollectorJobResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal["1.0"] = "1.0"
    job_id: str
    lease_token: Annotated[str, Field(min_length=16, max_length=128)]
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)]
    results: list[PlatformResult] = Field(min_length=1, max_length=6)
    collector_version: Annotated[str, Field(max_length=40)] = "0.1.0"
    started_at: datetime
    finished_at: datetime
