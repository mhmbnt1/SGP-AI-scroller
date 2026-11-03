"""Eligibility: user exclusions, source permissions, explicit constraints — before any scoring."""

from __future__ import annotations

from focusfeed_api.pipeline.text import contains_term
from focusfeed_api.pipeline.types import Candidate, Intent, UserContext

ALLOWED_MODES = {"personalized_feed", "public_search", "public_url", "user_import", "synthetic_fixture"}


def _build_text(c: Candidate) -> str:
    d = c.dto
    parts = [d.title or "", d.caption or ""]
    if d.evidence.transcript_segments:
        parts.append(" ".join(s.text for s in d.evidence.transcript_segments[:200]))
    return " ".join(parts)[:20000]


def apply_eligibility(cands: list[Candidate], ctx: UserContext, intent: Intent | None) -> None:
    """Sets ``exclusion_reason`` on ineligible candidates (in place)."""
    excluded_creators = {c.lower() for c in ctx.excluded_creators} | {c.lower() for c in ctx.hidden_creators}
    langs = {lang.lower() for lang in ctx.languages}
    for c in cands:
        d = c.dto
        c.text = _build_text(c)
        c.language = d.language or d.evidence.transcript_language
        if d.collection_mode.value not in ALLOWED_MODES:
            c.exclusion_reason = "source_not_permitted"
            continue
        handle = (d.creator_handle or "").lower().lstrip("@")
        if handle and (handle in excluded_creators or f"@{handle}" in excluded_creators):
            c.exclusion_reason = "excluded_creator"
            continue
        if c.key in ctx.not_interested_keys:
            c.exclusion_reason = "not_interested"
            continue
        hit = next((term for term in ctx.exclusions if contains_term(c.text, term)), None)
        if hit:
            c.exclusion_reason = f"exclusion:{hit[:40]}"
            continue
        if (
            langs
            and c.language
            and c.language.lower().split("-")[0] not in {lang.split("-")[0] for lang in langs}
        ):
            c.exclusion_reason = f"language:{c.language}"
            continue
        if intent is not None:
            bad = next((term for term in intent.must_exclude if contains_term(c.text, term)), None)
            if bad:
                c.exclusion_reason = f"intent_exclude:{bad[:40]}"
                continue
            if intent.max_duration_seconds is not None and d.duration_seconds is not None:
                if d.duration_seconds > intent.max_duration_seconds:
                    c.exclusion_reason = "intent_duration"
                    continue
