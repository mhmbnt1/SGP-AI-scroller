"""Deterministic fake provider for tests and demo mode.

It never contacts the network. Outputs are derived from the *input* using
simple, inspectable rules, so tests can assert on them and the demo never
pretends a model produced real analysis. Batches generated with it are
labelled synthetic by the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any

from focusfeed_api.providers.base import (
    CancelToken,
    GenerationResult,
    InvalidOutput,
    ModelInfo,
    ProviderHealth,
)

_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9'-]{2,}")
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "you",
    "your",
    "are",
    "from",
    "have",
    "how",
    "what",
    "why",
    "into",
    "about",
    "just",
    "than",
    "then",
    "them",
    "they",
    "will",
    "can",
    "all",
    "our",
    "out",
    "more",
    "most",
    "not",
    "but",
    "its",
    "it's",
    "was",
    "were",
    "has",
    "had",
    "one",
    "two",
    "get",
    "got",
    "like",
    "make",
    "made",
    "over",
    "under",
    "when",
    "where",
    "who",
    "which",
    "there",
    "here",
    "also",
    "very",
    "really",
    "some",
    "any",
    "video",
    "watch",
    "today",
    "new",
    "best",
    "top",
    "every",
    "much",
    "many",
    "been",
    "being",
    "does",
    "did",
}

EMBED_DIM = 64


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "") if t.lower() not in STOPWORDS]


def keyword_topics(text: str, limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for t in tokens(text):
        counts[t] = counts.get(t, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ranked[:limit]]


def hashed_embedding(text: str, dim: int = EMBED_DIM) -> list[float]:
    vec = [0.0] * dim
    for t in tokens(text):
        h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeProvider:
    name = "fake"

    def __init__(self, *, fail_mode: str | None = None) -> None:
        # fail_mode: None | "invalid_json" | "unavailable" | "timeout" | "invented_refs"
        self.fail_mode = fail_mode
        self.calls = 0

    def health(self) -> ProviderHealth:
        models = [
            ModelInfo(name="fake-text", purposes={"text"}, json_output=True, context_window=8192),
            ModelInfo(
                name="fake-embed", purposes={"embedding"}, embeddings=True, embedding_dimensions=EMBED_DIM
            ),
        ]
        return ProviderHealth(healthy=True, detail="deterministic fake provider (no network)", models=models)

    def supports_vision(self, model: str) -> bool:
        return False

    def describe_image(self, *, model: str, image_bytes: bytes, prompt: str, timeout_seconds: float) -> str:
        return "visual analysis unavailable (fake provider)"

    def embed(self, *, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        from focusfeed_api.providers.base import ProviderUnavailable

        if self.fail_mode == "unavailable":
            raise ProviderUnavailable("fake provider configured unavailable")
        return [hashed_embedding(t) for t in texts]

    def generate_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        timeout_seconds: float,
        max_output_tokens: int = 800,
        cancel: CancelToken | None = None,
    ) -> GenerationResult:
        from focusfeed_api.providers.base import ProviderTimeout, ProviderUnavailable

        if cancel is not None:
            cancel.raise_if_cancelled()
        self.calls += 1
        start = time.perf_counter()
        if self.fail_mode == "unavailable":
            raise ProviderUnavailable("fake provider configured unavailable")
        if self.fail_mode == "timeout":
            raise ProviderTimeout("fake provider configured to time out")
        if self.fail_mode == "invalid_json":
            raise InvalidOutput("fake provider returned non-JSON")
        try:
            payload = json.loads(user)
        except json.JSONDecodeError:
            payload = {"task": "unknown"}
        task = payload.get("task")
        if task == "analyze_candidate":
            parsed = self._analyze(payload)
        elif task == "interpret_intent":
            parsed = self._intent(payload)
        else:
            parsed = {}
        latency = int((time.perf_counter() - start) * 1000)
        return GenerationResult(
            parsed=parsed,
            raw_text=json.dumps(parsed),
            input_tokens=len(user) // 4,
            output_tokens=len(json.dumps(parsed)) // 4,
            latency_ms=latency,
            model=model,
        )

    # ------------------------------------------------------------------ tasks

    def _analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        cand = payload.get("candidate", {})
        title = cand.get("title") or ""
        caption = cand.get("caption") or ""
        segments = cand.get("transcript_segments") or []
        allowed_refs = payload.get("allowed_evidence_refs") or []
        text = " ".join([title, caption] + [s.get("text", "") for s in segments])
        topics = keyword_topics(text, 5)
        if segments:
            first = " ".join(s.get("text", "") for s in segments[:2]).strip()
            summary = f'Transcript opens with: "{first[:220]}"'
            refs = allowed_refs[: min(2, len(allowed_refs))]
        else:
            summary = f"Metadata only: {title[:160]}" if title else "Metadata only: no title available."
            refs = []
        if self.fail_mode == "invented_refs":
            refs = ["seg:9999"]
            summary += " (invented evidence)"
        return {
            "topics": topics,
            "summary": summary,
            "relevance_evidence": [{"evidence_ref": r, "quote": ""} for r in refs],
            "uncertainty": "low" if segments else "high",
            "language": cand.get("language") or "unknown",
        }

    def _intent(self, payload: dict[str, Any]) -> dict[str, Any]:
        query = payload.get("query") or ""
        kws = keyword_topics(query, 8)
        constraints: dict[str, Any] = {}
        m = re.search(r"under\s+(\d+)\s*(min|minute|minutes)", query.lower())
        if m:
            constraints["max_duration_seconds"] = int(m.group(1)) * 60
        return {"keywords": kws, "constraints": constraints, "must_include": [], "must_exclude": []}
