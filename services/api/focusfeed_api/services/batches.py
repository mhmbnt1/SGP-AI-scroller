"""Run the ranking pipeline for a job and persist exactly one batch per job."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from ff_protocol import (
    CandidateItem,
    CollectionMode,
    EvidenceBundle,
    FrameSample,
    Platform,
    TranscriptSegment,
    TranscriptSource,
)
from pydantic import HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.models import (
    CollectionJob,
    ContentItem,
    EvidenceArtifact,
    ModelRun,
    PreferenceProfile,
    Recommendation,
    RecommendationBatch,
    UserObservation,
)
from focusfeed_api.pipeline.intent import interpret_intent
from focusfeed_api.pipeline.run import explanation_for, run_pipeline
from focusfeed_api.pipeline.types import Candidate, PipelineConfig
from focusfeed_api.providers.base import CancelToken, Provider
from focusfeed_api.services.ingest import load_job_candidates
from focusfeed_api.services.preferences import build_user_context, get_or_create_profile, snapshot


def candidate_from_rows(
    item: ContentItem, obs: UserObservation, evidence: list[EvidenceArtifact]
) -> Candidate:
    bundle = EvidenceBundle()
    ev_ids: list[str] = []
    for ev in evidence:
        ev_ids.append(str(ev.id))
        if ev.kind == "transcript":
            bundle.transcript_source = (
                TranscriptSource(ev.transcript_source)
                if ev.transcript_source in TranscriptSource.__members__
                else TranscriptSource.none
            )
            bundle.transcript_segments = [TranscriptSegment(**s) for s in (ev.segments or [])][:2000]
            bundle.coverage_ratio = ev.coverage_ratio
            bundle.transcript_language = ev.language
            bundle.extraction_method = ev.extraction_method
        elif ev.kind == "frames":
            bundle.frame_samples = [FrameSample(**f) for f in (ev.frames or [])][:64]
    dto = CandidateItem(
        platform=Platform(item.platform),
        external_id=item.external_id,
        canonical_url=HttpUrl(item.canonical_url),
        creator_handle=item.creator_handle,
        creator_name=item.creator_name,
        title=item.title,
        caption=item.caption,
        language=item.language,
        duration_seconds=item.duration_seconds,
        published_at=item.published_at,
        observed_at=obs.observed_at,
        collection_mode=CollectionMode(obs.collection_mode),
        feed_position=obs.feed_position,
        thumbnail_url=HttpUrl(item.thumbnail_url) if item.thumbnail_url else None,
        evidence=bundle,
    )
    return Candidate(dto=dto, item_id=item.id, evidence_artifact_ids=ev_ids)


def existing_batch(db: Session, job: CollectionJob) -> RecommendationBatch | None:
    return db.scalar(select(RecommendationBatch).where(RecommendationBatch.job_id == job.id))


def build_batch(
    db: Session,
    job: CollectionJob,
    *,
    provider: Provider | None,
    cancel: CancelToken | None = None,
    completion_status: str = "completed",
) -> tuple[RecommendationBatch, dict[str, Any]]:
    """Idempotent: returns the existing batch if one was already persisted for this job."""
    found = existing_batch(db, job)
    if found is not None:
        return found, {"reused": True}
    settings = get_settings()
    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == job.user_id))
    if prof is None:
        from focusfeed_api.models import User

        user = db.get(User, job.user_id)
        assert user is not None
        prof = get_or_create_profile(db, user)
    ctx = build_user_context(db, job.user_id, prof)
    rows = load_job_candidates(db, job)
    cands = [candidate_from_rows(item, obs, ev) for item, obs, ev in rows]

    runs: list[ModelRun] = []

    def record_run(purpose: str, outcome: str, latency_ms: int, in_tok, out_tok, error_code: str) -> None:
        runs.append(
            ModelRun(
                user_id=job.user_id,
                job_id=job.id,
                provider=(provider.name if provider else "none"),
                model=text_model,
                purpose=purpose,
                prompt_version="analyze-v1",
                latency_ms=latency_ms,
                input_tokens=in_tok,
                output_tokens=out_tok,
                outcome=outcome,
                error_code=error_code[:64],
            )
        )

    text_model = prof.text_model or (
        settings.ff_default_text_model if provider and provider.name == "ollama" else "fake-text"
    )
    embedding_model = prof.embedding_model or (
        settings.ff_default_embedding_model if provider and provider.name == "ollama" else "fake-embed"
    )
    budget = job.budget or {}
    cfg = PipelineConfig(
        weights=settings.ranking_weights.model_dump(),
        now=datetime.now(UTC),
        max_model_calls=int(budget.get("max_model_calls", 60)),
        max_enrich_candidates=min(20, int(budget.get("max_media_items", 10)) * 2),
    )
    intent = None
    if job.mode == "search" and job.query:
        intent = interpret_intent(
            job.query,
            provider=provider,
            model=text_model,
            timeout_seconds=settings.ff_model_timeout_seconds,
            cancel=cancel,
        )
        if provider is not None:
            cfg.max_model_calls = max(0, cfg.max_model_calls - 1)
    outcome = run_pipeline(
        cands,
        ctx=ctx,
        intent=intent,
        cfg=cfg,
        provider=provider,
        text_model=text_model,
        embedding_model=embedding_model,
        timeout_seconds=settings.ff_model_timeout_seconds,
        cancel=cancel,
        record_run=record_run,
    )
    is_synthetic = (
        all(c.dto.collection_mode == CollectionMode.synthetic_fixture for c in cands)
        if cands
        else (settings.ff_mode != "live")
    )
    batch = RecommendationBatch(
        user_id=job.user_id,
        job_id=job.id,
        mode=job.mode,
        query=job.query,
        preferences_snapshot=snapshot(prof),
        preferences_version=prof.version,
        config_version=cfg.config_version,
        provider=(provider.name if provider else "none"),
        model=text_model,
        completion_status=completion_status,
        platform_summary={
            **outcome.summary,
            "notes": outcome.notes,
            "model_outcomes": outcome.model_outcomes,
        },
        total_estimated_seconds=sum(c.estimated_seconds for c in outcome.selected),
        is_synthetic=is_synthetic,
    )
    db.add(batch)
    db.flush()
    for rank, c in enumerate(outcome.selected, start=1):
        assert c.item_id is not None
        db.add(
            Recommendation(
                batch_id=batch.id,
                user_id=job.user_id,
                item_id=c.item_id,
                platform=c.dto.platform.value,
                rank=rank,
                score=c.score,
                components={k: float(v) for k, v in c.components.items()},
                explanation=explanation_for(c, ctx, intent),
                summary=c.summary[:2000],
                topics=c.topics,
                analysis_kind=c.analysis_kind,
                evidence_artifact_ids=c.evidence_artifact_ids,
                estimated_seconds=c.estimated_seconds,
                duration_known=c.duration_known,
            )
        )
    for r in runs:
        db.add(r)
    job.model_calls = (job.model_calls or 0) + outcome.model_calls
    job.batch_id = batch.id
    db.flush()
    return batch, {
        "reused": False,
        "selected": len(outcome.selected),
        "candidates": len(cands),
        "notes": outcome.notes,
        "model_outcomes": outcome.model_outcomes,
    }


def batch_owned(db: Session, user_id: uuid.UUID, batch_id: uuid.UUID) -> RecommendationBatch | None:
    b = db.get(RecommendationBatch, batch_id)
    if b is None or b.user_id != user_id:
        return None
    return b
