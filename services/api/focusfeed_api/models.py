"""SQLAlchemy ORM models.

Conventions
-----------
* UUID primary keys, UTC ``timestamptz`` columns, ``created_at`` everywhere.
* Public catalog data (``content_items``) is separated from private
  observations (``user_observations``); everything private carries ``user_id``.
* Unique constraints make retries idempotent: one batch per job, one
  observation per (user, item, job), one evidence artifact per
  (user, item, job, kind).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


# --------------------------------------------------------------------------- identity


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    preference: Mapped[PreferenceProfile | None] = relationship(back_populates="user", uselist=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_kind: Mapped[str] = mapped_column(String(16))  # web | mobile
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PreferenceProfile(TimestampMixin, Base):
    __tablename__ = "preference_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    interests: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    exclusions: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    excluded_creators: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    languages: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    per_platform_limit: Mapped[int] = mapped_column(Integer, default=5, server_default=text("5"))
    total_budget_minutes: Mapped[int] = mapped_column(Integer, default=30, server_default=text("30"))
    consent_saved_signals: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    consent_feedback_learning: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    text_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped[User] = relationship(back_populates="preference")


# --------------------------------------------------------------------------- collectors


class CollectorEnrollment(Base):
    """Short-lived, one-use pairing code approved by the authenticated user."""

    __tablename__ = "collector_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collector_devices.id"), nullable=True)


class CollectorDevice(TimestampMixin, Base):
    __tablename__ = "collector_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Collector")
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    os_name: Mapped[str] = mapped_column(String(40), default="")
    collector_version: Mapped[str] = mapped_column(String(40), default="")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capabilities: Mapped[list[Any]] = mapped_column(JSONType, default=list)


class PlatformConnection(TimestampMixin, Base):
    """Health/capability record. Never stores social passwords or cookies."""

    __tablename__ = "platform_connections"
    __table_args__ = (UniqueConstraint("user_id", "platform", name="uq_platform_connection_user_platform"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("collector_devices.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(32), default="collector_offline")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status_detail: Mapped[str] = mapped_column(String(500), default="")


# --------------------------------------------------------------------------- jobs


class Schedule(TimestampMixin, Base):
    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    local_time: Mapped[str] = mapped_column(String(5), default="08:00")  # HH:MM
    days_of_week: Mapped[list[Any]] = mapped_column(JSONType, default=lambda: [0, 1, 2, 3, 4, 5, 6])
    platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    missed_run_policy: Mapped[str] = mapped_column(String(16), default="run_once")  # run_once | skip


class CollectionJob(Base):
    __tablename__ = "collection_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_job_user_idempotency"),
        Index("ix_jobs_state_created", "state", "created_at"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16))  # daily | search
    query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    budget: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    platform_states: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | schedule
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True)
    preferences_version: Mapped[int] = mapped_column(Integer, default=1)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)  # worker:<id> | device:<uuid>
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    stop_reason: Mapped[str] = mapped_column(String(500), default="")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    model_calls: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_event_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(String(1000), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


# --------------------------------------------------------------------------- content


class ContentItem(TimestampMixin, Base):
    """Public catalog record: platform metadata only, no private signal."""

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_item_platform_external"),
        Index("ix_items_canonical_url", "canonical_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(200))
    canonical_url: Mapped[str] = mapped_column(String(2000))
    creator_handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creator_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class UserObservation(Base):
    """Private: this user saw this item in this job (and where)."""

    __tablename__ = "user_observations"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", "job_id", name="uq_observation_user_item_job"),
        Index("ix_observations_user_item", "user_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"))
    collection_mode: Mapped[str] = mapped_column(String(32))
    feed_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"
    __table_args__ = (UniqueConstraint("user_id", "item_id", "job_id", "kind", name="uq_evidence_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))  # transcript | frames | caption
    transcript_source: Mapped[str] = mapped_column(String(24), default="none")
    coverage_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    segments: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    frames: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    extraction_method: Mapped[str] = mapped_column(String(120), default="metadata")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ItemEmbedding(Base):
    """Embeddings of *public* item text. Access is gated by user observations."""

    __tablename__ = "item_embeddings"
    __table_args__ = (UniqueConstraint("item_id", "model", name="uq_embedding_item_model"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


# --------------------------------------------------------------------------- recommendations


class RecommendationBatch(Base):
    __tablename__ = "recommendation_batches"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_batch_job"),
        Index("ix_batches_user_generated", "user_id", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("collection_jobs.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(16))
    query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    preferences_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    preferences_version: Mapped[int] = mapped_column(Integer, default=1)
    config_version: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(32), default="fake")
    model: Mapped[str] = mapped_column(String(120), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    completion_status: Mapped[str] = mapped_column(String(16), default="completed")  # completed | partial
    platform_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    total_estimated_seconds: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("batch_id", "rank", name="uq_recommendation_batch_rank"),
        UniqueConstraint("batch_id", "item_id", name="uq_recommendation_batch_item"),
        Index("ix_recommendations_user_item", "user_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendation_batches.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(20))
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    components: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    explanation: Mapped[str] = mapped_column(String(1000), default="")
    summary: Mapped[str] = mapped_column(String(2000), default="")
    topics: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    analysis_kind: Mapped[str] = mapped_column(String(32), default="metadata_only")
    evidence_artifact_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list)
    estimated_seconds: Mapped[int] = mapped_column(Integer, default=0)
    duration_known: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (Index("ix_feedback_user_item", "user_id", "item_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), nullable=True)
    action: Mapped[str] = mapped_column(String(24))  # relevant | not_relevant | not_interested | hide_creator | seen
    creator_handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="item")  # item | creator
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedItem(Base):
    __tablename__ = "saved_items"
    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_saved_user_item"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------------------- ops


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collection_jobs.id", ondelete="SET NULL"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    purpose: Mapped[str] = mapped_column(String(48))
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(24))  # ok | invalid_output | timeout | unavailable | error
    error_code: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # kept after deletion, minimized
    kind: Mapped[str] = mapped_column(String(48))
    request_id: Mapped[str] = mapped_column(String(64), default="")
    ip_hash: Mapped[str] = mapped_column(String(64), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


class IdempotencyRecord(Base):
    """Stores the response of state-changing requests keyed by (user, key)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    scope: Mapped[str] = mapped_column(String(128))  # e.g. "user:<id>:jobs"
    key: Mapped[str] = mapped_column(String(128))
    response: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
