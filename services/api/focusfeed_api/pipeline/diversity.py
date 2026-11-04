"""Bounded diversity selection (MMR-style) with per-platform top-K and a total consumption budget."""

from __future__ import annotations

from focusfeed_api.pipeline.text import jaccard
from focusfeed_api.pipeline.types import Candidate

LAMBDA = 0.7  # relevance vs. diversity trade-off
CREATOR_PENALTY = 0.35  # similarity contribution when the creator repeats


def _similarity(a: Candidate, b: Candidate) -> float:
    sim = jaccard(set(a.topics), set(b.topics))
    if a.dto.creator_handle and a.dto.creator_handle == b.dto.creator_handle:
        sim = max(sim, CREATOR_PENALTY + 0.65 * sim)
    return min(1.0, sim)


def select_diverse(
    cands: list[Candidate], *, per_platform_limit: int, total_budget_seconds: int
) -> tuple[list[Candidate], dict]:
    """Greedy MMR per platform, then a global consumption-budget cut in rank order.

    Returns the ordered selection and a summary dict with counts per platform.
    """
    eligible = [c for c in cands if not c.exclusion_reason]
    by_platform: dict[str, list[Candidate]] = {}
    for c in eligible:
        by_platform.setdefault(c.dto.platform.value, []).append(c)

    per_platform_selected: dict[str, list[Candidate]] = {}
    for platform, pool in by_platform.items():
        remaining = sorted(pool, key=lambda c: (-c.score, c.dto.external_id))
        chosen: list[Candidate] = []
        while remaining and len(chosen) < per_platform_limit:
            best = None
            best_val = -1.0
            for c in remaining:
                max_sim = max((_similarity(c, s) for s in chosen), default=0.0)
                val = LAMBDA * c.score - (1 - LAMBDA) * max_sim
                if val > best_val:
                    best_val, best = val, c
            assert best is not None
            best.components["diversity_adjusted"] = round(best_val, 4)
            chosen.append(best)
            remaining.remove(best)
        per_platform_selected[platform] = chosen

    # interleave platforms by rank so no single platform dominates the top of the batch
    ordered: list[Candidate] = []
    max_len = max((len(v) for v in per_platform_selected.values()), default=0)
    for i in range(max_len):
        for platform in sorted(per_platform_selected):
            lst = per_platform_selected[platform]
            if i < len(lst):
                ordered.append(lst[i])

    # consumption budget: keep items in order while the running estimate fits
    final: list[Candidate] = []
    used = 0
    dropped_budget = 0
    for c in ordered:
        if used + c.estimated_seconds <= total_budget_seconds or not final:
            final.append(c)
            used += c.estimated_seconds
        else:
            c.exclusion_reason = "consumption_budget"
            dropped_budget += 1
    summary = {
        "per_platform": {p: len([c for c in final if c.dto.platform.value == p]) for p in by_platform},
        "candidates_per_platform": {p: len(v) for p, v in by_platform.items()},
        "dropped_for_budget": dropped_budget,
        "estimated_seconds": used,
        "budget_seconds": total_budget_seconds,
    }
    return final, summary
