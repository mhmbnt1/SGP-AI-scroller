"""Reproducible evaluation harness over labelled synthetic fixtures.

Compares the deterministic baseline (no model) against the enhanced pipeline
(fake provider: embeddings + structured analysis) on identical inputs.

Metrics: precision@K, NDCG@K (graded: 2 = all query labels match, 1 = partial),
creator/topic diversity, duplicate rate, constraint violations, consumption-
budget adherence, model calls, latency.

Labels are *synthetic* (fixture topic tags). They are software/regression
evidence, not evidence of real-world efficacy — see docs/EVALUATION.md.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from typing import Any

from focusfeed_api.fixtures.demo_content import DEMO_ITEMS, FIXTURE_EPOCH, labels_by_key
from focusfeed_api.pipeline.intent import parse_intent_deterministic
from focusfeed_api.pipeline.run import run_pipeline
from focusfeed_api.pipeline.types import Candidate, PipelineConfig, UserContext
from focusfeed_api.providers.fake import FakeProvider

WEIGHTS = {
    "intent_relevance": 0.35,
    "interest_match": 0.25,
    "feedback_signal": 0.10,
    "freshness": 0.10,
    "novelty": 0.10,
    "evidence_quality": 0.10,
}

# Each case: a user profile or query plus the fixture labels considered relevant.
CASES: list[dict[str, Any]] = [
    {
        "name": "interests:cooking+high-protein",
        "interests": ["cooking", "high-protein"],
        "query": None,
        "relevant": {"cooking", "high-protein"},
        "languages": ["en"],
    },
    {
        "name": "interests:programming",
        "interests": ["programming", "python"],
        "query": None,
        "relevant": {"programming", "python"},
        "languages": [],
    },
    {
        "name": "interests:fitness",
        "interests": ["fitness", "running"],
        "query": None,
        "relevant": {"fitness", "running"},
        "languages": [],
    },
    {
        "name": "query:protein recipes under 20 minutes",
        "interests": ["music"],
        "query": "high protein recipes under 20 minutes",
        "relevant": {"high-protein", "quick-meals"},
        "languages": [],
    },
    {
        "name": "query:python without clickbait",
        "interests": ["travel"],
        "query": "python tutorials without clickbait",
        "relevant": {"python"},
        "languages": [],
    },
    {
        "name": "interests:finance excl crypto",
        "interests": ["finance", "investing"],
        "query": None,
        "relevant": {"finance", "investing"},
        "languages": [],
        "exclusions": ["crypto"],
    },
]

HELD_OUT_SPLIT = 0.3  # last 30% of fixtures (by external_id order) are held out for the reported numbers


def _candidates(split: str) -> list[Candidate]:
    items = sorted(DEMO_ITEMS, key=lambda d: d.external_id)
    cut = int(len(items) * (1 - HELD_OUT_SPLIT))
    chosen = items[cut:] if split == "held_out" else items[:cut] if split == "train" else items
    return [Candidate(dto=d.to_candidate(feed_position=i)) for i, d in enumerate(chosen)]


def _grade(labels: list[str], relevant: set[str]) -> int:
    hits = len(set(labels) & relevant)
    if hits == 0:
        return 0
    return 2 if hits >= min(2, len(relevant)) else 1


def _ndcg(grades: list[int], k: int) -> float:
    def dcg(gs: list[int]) -> float:
        return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gs[:k]))

    ideal = sorted(grades, reverse=True)
    denom = dcg(ideal)
    return dcg(grades) / denom if denom else 0.0


def _run_case(case: dict[str, Any], *, enhanced: bool, split: str, k: int = 5) -> dict[str, Any]:
    labels = labels_by_key()
    cands = _candidates(split)
    ctx = UserContext(
        user_id=None,
        interests=case["interests"],
        exclusions=case.get("exclusions", []),
        excluded_creators=[],
        languages=case.get("languages", []),
        per_platform_limit=k,
        total_budget_minutes=60,
        consent_feedback_learning=True,
    )
    intent = parse_intent_deterministic(case["query"]) if case["query"] else None
    provider = FakeProvider() if enhanced else None
    cfg = PipelineConfig(weights=WEIGHTS, now=FIXTURE_EPOCH, max_model_calls=60)
    runs: list[tuple] = []
    start = time.perf_counter()
    out = run_pipeline(
        cands,
        ctx=ctx,
        intent=intent,
        cfg=cfg,
        provider=provider,
        text_model="fake-text",
        embedding_model="fake-embed",
        timeout_seconds=5,
        cancel=None,
        record_run=lambda *a: runs.append(a),
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    selected = out.selected
    grades = [
        _grade(labels.get((c.dto.platform.value, c.dto.external_id), []), case["relevant"]) for c in selected
    ]
    topk = grades[:k] if selected else []
    precision = (sum(1 for g in topk if g > 0) / len(topk)) if topk else 0.0
    keys = [c.key for c in selected]
    dup_rate = 1 - len(set(keys)) / len(keys) if keys else 0.0
    creators = [c.dto.creator_handle for c in selected]
    creator_div = len(set(creators)) / len(creators) if creators else 0.0
    topics = {t for c in selected for t in c.topics}
    violations = 0
    if intent and intent.max_duration_seconds:
        violations += sum(1 for c in selected if (c.dto.duration_seconds or 0) > intent.max_duration_seconds)
    for term in ctx.exclusions:
        violations += sum(1 for c in selected if term in c.text.lower().split())
    est = sum(c.estimated_seconds for c in selected)
    return {
        "case": case["name"],
        "variant": "enhanced" if enhanced else "baseline",
        "split": split,
        "selected": len(selected),
        "precision_at_k": round(precision, 3),
        "ndcg_at_k": round(_ndcg(grades, k), 3),
        "creator_diversity": round(creator_div, 3),
        "distinct_topics": len(topics),
        "duplicate_rate": round(dup_rate, 3),
        "constraint_violations": violations,
        "budget_adherence": est <= ctx.total_budget_minutes * 60,
        "estimated_seconds": est,
        "model_calls": out.model_calls,
        "latency_ms": latency_ms,
        "model_outcomes": out.model_outcomes,
    }


def run_evaluation() -> dict[str, Any]:
    per_query = []
    for split in ("held_out", "all"):
        for case in CASES:
            for enhanced in (False, True):
                per_query.append(_run_case(case, enhanced=enhanced, split=split))

    def _agg(split: str, variant: str, key: str) -> float:
        vals = [
            r[key]
            for r in per_query
            if r["split"] == split and r["variant"] == variant and isinstance(r[key], int | float)
        ]
        return round(sum(vals) / len(vals), 3) if vals else 0.0

    def _summary(split: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for variant in ("baseline", "enhanced"):
            out[variant] = {
                k: _agg(split, variant, k)
                for k in (
                    "precision_at_k",
                    "ndcg_at_k",
                    "creator_diversity",
                    "duplicate_rate",
                    "constraint_violations",
                    "model_calls",
                    "latency_ms",
                )
            }
            out[variant]["budget_adherence_rate"] = round(
                sum(1 for r in per_query if r["split"] == split and r["variant"] == variant and r["budget_adherence"])
                / len(CASES),
                3,
            )
        return out

    summary = _summary("held_out")  # primary (reported) numbers
    summary_all_fixtures = _summary("all")  # secondary: every fixture, no hold-out
    return {
        "summary_all_fixtures": summary_all_fixtures,
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": {
            "fixtures_total": len(DEMO_ITEMS),
            "held_out_fraction": HELD_OUT_SPLIT,
            "held_out_items": len(_candidates("held_out")),
            "label_source": "synthetic fixture topic tags (hand-written in fixtures/demo_content.py)",
            "cases": len(CASES),
            "k": 5,
        },
        "config": {"weights": WEIGHTS, "provider": "fake (deterministic)", "ranking_version": "ranking-v1"},
        "summary": summary,
        "per_query": per_query,
        "limitations": [
            "Synthetic labels and a deterministic fake provider: results are regression checks, not evidence of real-world usefulness.",
            "The held-out split is by fixture id, not by user; there are no real users or sessions.",
            "No LLM judge is used; relevance is defined by fixture tags only.",
        ],
    }
