"""Pipeline orchestration: candidates -> ordered, explained selection.

Pure with respect to the database: persistence happens in services.batches.
"""

from __future__ import annotations

from focusfeed_api.pipeline.dedup import deduplicate
from focusfeed_api.pipeline.diversity import select_diverse
from focusfeed_api.pipeline.eligibility import apply_eligibility
from focusfeed_api.pipeline.enrich import enrich_candidates
from focusfeed_api.pipeline.explain import explain
from focusfeed_api.pipeline.scoring import score_candidates
from focusfeed_api.pipeline.text import contains_term
from focusfeed_api.pipeline.types import Candidate, Intent, PipelineConfig, PipelineOutcome, UserContext
from focusfeed_api.providers.base import CancelToken, Provider, ProviderError


def _prefilter_rank(c: Candidate, ctx: UserContext, intent: Intent | None) -> float:
    """Cheap plausibility score used to choose which candidates deserve a model call."""
    terms = intent.keywords if (intent and intent.keywords) else ctx.interests
    if not terms:
        return 0.5
    return sum(1 for t in terms if contains_term(c.text, t)) / len(terms)


def run_pipeline(
    cands: list[Candidate],
    *,
    ctx: UserContext,
    intent: Intent | None,
    cfg: PipelineConfig,
    provider: Provider | None,
    text_model: str,
    embedding_model: str | None,
    timeout_seconds: float,
    cancel: CancelToken | None,
    record_run,
) -> PipelineOutcome:
    notes: list[str] = []
    apply_eligibility(cands, ctx, intent)

    # embeddings (optional, bounded to eligible candidates)
    eligible = [c for c in cands if not c.exclusion_reason]
    if provider is not None and embedding_model and eligible:
        try:
            texts = [c.text[:2000] for c in eligible]
            if intent is not None and intent.query:
                texts.append(intent.query)
            vectors = provider.embed(model=embedding_model, texts=texts, timeout_seconds=timeout_seconds)
            if intent is not None and intent.query:
                intent.embedding = vectors.pop()
            for c, v in zip(eligible, vectors, strict=True):
                c.embedding = v
            record_run("embed", "ok", 0, None, None, "")
        except ProviderError as exc:
            notes.append(f"embeddings unavailable: {exc.code}")
            record_run("embed", exc.code, 0, None, None, str(exc)[:60])

    unique = deduplicate(cands)
    if cancel is not None:
        cancel.raise_if_cancelled()

    # bounded enrichment of the most plausible candidates
    ranked_for_enrich = sorted(unique, key=lambda c: (-_prefilter_rank(c, ctx, intent), c.dto.external_id))
    to_enrich = ranked_for_enrich[: cfg.max_enrich_candidates]
    stats = None
    if provider is not None:
        stats = enrich_candidates(
            to_enrich,
            provider=provider,
            model=text_model,
            cfg=cfg,
            timeout_seconds=timeout_seconds,
            cancel=cancel,
            record_run=record_run,
        )
    for c in unique:
        if c not in to_enrich or provider is None:
            from focusfeed_api.pipeline.enrich import _apply, deterministic_analysis

            c.analysis_kind = c.dto.evidence.analysis_kind.value
            _apply(c, deterministic_analysis(c), source="deterministic")

    score_candidates(unique, ctx, intent, cfg)
    selected, summary = select_diverse(
        unique, per_platform_limit=ctx.per_platform_limit, total_budget_seconds=ctx.total_budget_minutes * 60
    )
    for c in selected:
        c.components["final_score"] = c.score
    explanations = {id(c): explain(c, ctx, intent) for c in selected}
    for c in selected:
        c.summary = c.summary or ""
        c.components["explanation_len"] = float(len(explanations[id(c)]))
    excluded = [c for c in cands if c.exclusion_reason]
    model_outcomes = {}
    model_calls = 0
    if stats is not None:
        model_calls = stats.model_calls
        model_outcomes = {
            "ok": stats.ok,
            "invalid": stats.invalid,
            "unavailable": stats.unavailable,
            "timeout": stats.timeout,
            "fallback": stats.fallback,
        }
        if stats.unavailable:
            notes.append("model provider unavailable; deterministic fallback used")
        if stats.invalid:
            notes.append(f"{stats.invalid} invalid model output(s) rejected")
    summary["excluded_reasons"] = _count_reasons(excluded)
    summary["candidates_total"] = len(cands)
    summary["selected_total"] = len(selected)
    return PipelineOutcome(
        selected=selected,
        excluded=excluded,
        model_calls=model_calls,
        model_outcomes=model_outcomes,
        notes=notes,
        summary=summary,
    )


def _count_reasons(excluded: list[Candidate]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in excluded:
        key = (c.exclusion_reason or "unknown").split(":")[0]
        out[key] = out.get(key, 0) + 1
    return out


def explanation_for(c: Candidate, ctx: UserContext, intent: Intent | None) -> str:
    return explain(c, ctx, intent)
