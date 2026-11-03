"""Small deterministic text utilities shared by pipeline stages."""

from __future__ import annotations

import math
import re

from focusfeed_api.providers.fake import STOPWORDS, keyword_topics, tokens

_NORM = re.compile(r"[^a-z0-9]+")

__all__ = ["STOPWORDS", "keyword_topics", "tokens", "normalize", "jaccard", "cosine", "contains_term"]


def normalize(text: str | None) -> str:
    return _NORM.sub(" ", (text or "").lower()).strip()


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def contains_term(haystack: str, term: str) -> bool:
    """Whole-word, case-insensitive containment (so 'ai' does not match 'said')."""
    h = f" {normalize(haystack)} "
    t = f" {normalize(term)} "
    return bool(t.strip()) and t in h
