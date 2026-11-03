"""Transparent baseline scoring with documented, normalized components.

Components (each in [0, 1]):
* intent_relevance  — explicit query match (keywords + embedding cosine). In daily mode
                       this equals interest_match so weights still sum sensibly.
* interest_match    — declared interests found in title/caption/transcript/topics.
* feedback_signal   — opt-in: +creator/topic marked relevant, -marked not relevant.
* freshness         — exponential decay on publish age (half-life 7 days); unknown -> 0.4.
* novelty           — 1 if never recommended before, else 0.
* evidence_quality  — metadata_only 0.25, transcript 0.6 + coverage bonus, combined up to 1.0.

Initial weights are engineering heuristics, configurable via FF_RANKING_WEIGHTS_JSON.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from focusfeed_api.pipeline.text import contains_term, cosine
from focusfeed_api.pipeline.types import Candidate, Intent, PipelineConfig, UserContext

DEFAULT_DURATION_BY_PLATFORM = {  # conservative estimates when the duration is unknown
    "youtube": 10 * 60,
    "instagram": 90,
    "tiktok": 60,
    "x": 60,
    "linkedin": 120,
    "demo": 5 * 60,
}


def _match_ratio(text: str, topics: list[str], terms: list[str]) -> float:
    if not terms:
        return 0.0
    hits = 0
    topic_set = {t.lower() for t in topics}
    for term in terms:
        if term.lower() in topic_set or contains_term(text, term):
            hits += 1
    return hits / len(terms)


def _freshness(published_at: datetime | None, now: datetime) -> float:
    if published_at is None:
        return 0.4
    age_days = max(0.0, (now - published_at.astimezone(UTC)).total_seconds() / 86400.0)
    return math.exp(-math.log(2) * age_days / 7.0)


def _evidence_quality(c: Candidate) -> float:
    kind = c.dto.evidence.analysis_kind.value
    cov = c.dto.evidence.coverage_ratio
    if kind == "combined":
        return min(1.0, 0.8 + 0.2 * cov)
    if kind == "transcript_supported":
        return min(0.9, 0.6 + 0.3 * cov)
    if kind == "sampled_visual":
        return 0.5
    return 0.25


def _feedback(c: Candidate, ctx: UserContext) -> float:
    if not ctx.consent_feedback_learning:
        return 0.5
    handle = (c.dto.creator_handle or "").lower().lstrip("@")
    pos = ctx.relevant_creators.get(handle, 0)
    neg = ctx.not_relevant_creators.get(handle, 0)
    for t in c.topics:
        pos += ctx.relevant_topics.get(t, 0)
        neg += ctx.not_relevant_topics.get(t, 0)
        pos += ctx.saved_topics.get(t, 0)
    if pos == 0 and neg == 0:
        return 0.5
    return max(0.0, min(1.0, 0.5 + 0.5 * (pos - neg) / float(pos + neg)))


def score_candidates(cands: list[Candidate], ctx: UserContext, intent: Intent | None, cfg: PipelineConfig) -> None:
    w = cfg.weights
    for c in cands:
        if c.exclusion_reason:
            continue
        interest = _match_ratio(c.text, c.topics, ctx.interests)
        if intent is not None and intent.query:
            kw = _match_ratio(c.text, c.topics, intent.keywords) if intent.keywords else 0.0
            emb = cosine(c.embedding, intent.embedding) if (c.embedding and intent.embedding) else 0.0
            emb = max(0.0, emb)
            relevance = min(1.0, 0.7 * kw + 0.3 * emb) if intent.keywords else emb
        else:
            relevance = interest
        comps = {
            "intent_relevance": round(relevance, 4),
            "interest_match": round(interest, 4),
            "feedback_signal": round(_feedback(c, ctx), 4),
            "freshness": round(_freshness(c.dto.published_at, cfg.now), 4),
            "novelty": 0.0 if c.key in ctx.previously_recommended_keys else 1.0,
            "evidence_quality": round(_evidence_quality(c), 4),
        }
        c.components = comps
        c.score = round(sum(w.get(k, 0.0) * v for k, v in comps.items()), 4)
        if c.dto.duration_seconds is not None:
            c.estimated_seconds = int(c.dto.duration_seconds)
            c.duration_known = True
        else:
            c.estimated_seconds = DEFAULT_DURATION_BY_PLATFORM.get(c.dto.platform.value, 300)
            c.duration_known = False
