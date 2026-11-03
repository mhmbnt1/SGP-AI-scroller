"""In-memory candidate representation used across pipeline stages."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ff_protocol import CandidateItem


@dataclass
class Candidate:
    """A candidate and everything the pipeline learns about it."""

    dto: CandidateItem
    item_id: uuid.UUID | None = None
    evidence_artifact_ids: list[str] = field(default_factory=list)
    text: str = ""  # title + caption + transcript (bounded) for cheap matching
    topics: list[str] = field(default_factory=list)
    summary: str = ""
    analysis_kind: str = "metadata_only"
    analysis_source: str = "deterministic"  # deterministic | model | unavailable
    embedding: list[float] | None = None
    components: dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    exclusion_reason: str | None = None
    estimated_seconds: int = 0
    duration_known: bool = False
    language: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.dto.platform.value, self.dto.external_id)


@dataclass
class UserContext:
    user_id: uuid.UUID
    interests: list[str]
    exclusions: list[str]
    excluded_creators: list[str]
    languages: list[str]
    per_platform_limit: int
    total_budget_minutes: int
    consent_feedback_learning: bool
    hidden_creators: set[str] = field(default_factory=set)  # from feedback hide_creator
    not_interested_keys: set[tuple[str, str]] = field(default_factory=set)  # (platform, external_id)
    relevant_creators: dict[str, int] = field(default_factory=dict)  # creator -> +count
    not_relevant_creators: dict[str, int] = field(default_factory=dict)
    relevant_topics: dict[str, int] = field(default_factory=dict)
    not_relevant_topics: dict[str, int] = field(default_factory=dict)
    previously_recommended_keys: set[tuple[str, str]] = field(default_factory=set)
    saved_topics: dict[str, int] = field(default_factory=dict)  # only with consent_saved_signals


@dataclass
class Intent:
    """Explicit current intent for search mode (takes priority over interests)."""

    query: str | None
    keywords: list[str] = field(default_factory=list)
    max_duration_seconds: int | None = None
    must_exclude: list[str] = field(default_factory=list)
    embedding: list[float] | None = None


@dataclass
class PipelineConfig:
    weights: dict[str, float]
    now: datetime
    max_model_calls: int
    max_enrich_candidates: int = 20
    config_version: str = "ranking-v1"
    prompt_version: str = "analyze-v1"


@dataclass
class PipelineOutcome:
    selected: list[Candidate]
    excluded: list[Candidate]
    model_calls: int
    model_outcomes: dict[str, int]
    notes: list[str]
    summary: dict[str, Any]
