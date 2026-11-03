"""Explanations are rendered from the *actual* score components and evidence coverage — not generated praise."""

from __future__ import annotations

from focusfeed_api.pipeline.text import contains_term
from focusfeed_api.pipeline.types import Candidate, Intent, UserContext

COVERAGE_LABELS = {
    "metadata_only": "Based on title/caption only — not a full-video analysis.",
    "transcript_supported": "Based on the available transcript",
    "sampled_visual": "Based on a few sampled frames — not a full-video analysis.",
    "combined": "Based on transcript plus sampled frames — not a full-video analysis.",
}


def coverage_label(kind: str, coverage_ratio: float) -> str:
    base = COVERAGE_LABELS.get(kind, COVERAGE_LABELS["metadata_only"])
    if kind in ("transcript_supported", "combined") and coverage_ratio > 0:
        return f"{base} (~{int(round(coverage_ratio * 100))}% of the runtime)."
    return base if base.endswith(".") else base + "."


def explain(c: Candidate, ctx: UserContext, intent: Intent | None) -> str:
    parts: list[str] = []
    comps = c.components
    if intent is not None and intent.query:
        matched = [k for k in intent.keywords if k.lower() in {t.lower() for t in c.topics} or contains_term(c.text, k)]
        if matched:
            parts.append("Matches your request: " + ", ".join(matched[:4]) + ".")
        elif comps.get("intent_relevance", 0) > 0.2:
            parts.append("Semantically related to your request.")
        else:
            parts.append("Weak match to your request; kept because few candidates were available.")
    interests = [i for i in ctx.interests if i.lower() in {t.lower() for t in c.topics} or contains_term(c.text, i)]
    if interests:
        parts.append("Matches your interests: " + ", ".join(interests[:3]) + ".")
    fb = comps.get("feedback_signal", 0.5)
    if ctx.consent_feedback_learning and fb > 0.6:
        parts.append("You marked similar creators or topics as relevant.")
    elif ctx.consent_feedback_learning and fb < 0.4:
        parts.append("Note: you previously marked similar content as not relevant.")
    fresh = comps.get("freshness", 0)
    if fresh >= 0.7:
        parts.append("Published recently.")
    if comps.get("novelty", 1) == 0:
        parts.append("Recommended before.")
    parts.append(coverage_label(c.analysis_kind, c.dto.evidence.coverage_ratio))
    if not c.duration_known:
        parts.append("Duration unknown — a conservative estimate was used for your time budget.")
    if c.analysis_source == "unavailable":
        parts.append("Model analysis was unavailable; topics were extracted deterministically.")
    return " ".join(parts)[:1000]
