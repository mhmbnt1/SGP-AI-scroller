"""Deduplication: exact keys first, then canonical URL, then bounded semantic near-duplicates."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit, urlunsplit

from focusfeed_api.pipeline.text import cosine, normalize
from focusfeed_api.pipeline.types import Candidate

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "feature", "si", "igsh", "ref"}
NEAR_DUP_COSINE = 0.97


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("m.youtube.com", "youtube.com", "youtu.be"):
        host = "youtube.com"
    query = parse_qs(parts.query, keep_blank_values=False)
    kept = {k: v for k, v in query.items() if k not in TRACKING_PARAMS}
    if host == "youtube.com" and "v" in kept:
        return f"https://youtube.com/watch?v={kept['v'][0]}"
    if parts.hostname == "youtu.be":
        return f"https://youtube.com/watch?v={parts.path.strip('/')}"
    q = "&".join(f"{k}={v[0]}" for k, v in sorted(kept.items()))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, q, ""))


def deduplicate(cands: list[Candidate]) -> list[Candidate]:
    """Return unique candidates; duplicates get an ``exclusion_reason`` and are dropped from the result.

    Evidence is merged into the kept candidate when the duplicate carries more.
    """
    by_key: dict[tuple[str, str], Candidate] = {}
    by_url: dict[str, Candidate] = {}
    kept: list[Candidate] = []
    for c in cands:
        if c.exclusion_reason:
            continue
        url = canonicalize_url(str(c.dto.canonical_url))
        existing = by_key.get(c.key) or by_url.get(url)
        if existing is not None:
            _merge_evidence(existing, c)
            c.exclusion_reason = "duplicate"
            continue
        by_key[c.key] = c
        by_url[url] = c
        kept.append(c)
    # semantic near-duplicates (only when embeddings exist, same platform, and titles are also close)
    final: list[Candidate] = []
    for c in kept:
        dup = False
        for k in final:
            if k.dto.platform != c.dto.platform or not c.embedding or not k.embedding:
                continue
            if normalize(c.dto.title) and normalize(c.dto.title) == normalize(k.dto.title):
                dup = True
            elif cosine(c.embedding, k.embedding) >= NEAR_DUP_COSINE and (
                (c.dto.creator_handle or "") == (k.dto.creator_handle or "")
            ):
                dup = True
            if dup:
                _merge_evidence(k, c)
                c.exclusion_reason = "near_duplicate"
                break
        if not dup:
            final.append(c)
    return final


def _merge_evidence(keep: Candidate, drop: Candidate) -> None:
    if len(drop.dto.evidence.transcript_segments) > len(keep.dto.evidence.transcript_segments):
        keep.dto.evidence = drop.dto.evidence
    if keep.dto.duration_seconds is None and drop.dto.duration_seconds is not None:
        keep.dto.duration_seconds = drop.dto.duration_seconds
