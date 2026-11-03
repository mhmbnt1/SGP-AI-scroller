# Evaluation

## What was measured

A reproducible harness (`services/api/focusfeed_api/evaluation.py`, run with
`uv run focusfeed-api evaluate`, output `reports/evaluation.json`) compares two variants of the
ranking pipeline on **identical inputs**:

* **baseline** — deterministic pipeline only (eligibility, dedup, keyword topics, scoring, MMR, budget);
  no model calls.
* **enhanced** — same pipeline plus the provider stage: embeddings (hashed bag-of-words, 64-d) for
  intent/near-duplicate similarity and per-candidate structured analysis (topics/summary/evidence refs)
  from the **deterministic fake provider**.

### Dataset and labels

* 30 hand-written synthetic fixtures (`fixtures/demo_content.py`), each tagged with topic labels
  (e.g. `cooking`, `high-protein`, `python`, `clickbait`). These labels are the *only* ground truth.
* 6 cases: 3 interest profiles (queryless), 2 explicit queries (one with a duration constraint, one
  with an exclusion phrase), 1 interest profile with an exclusion.
* Held-out split: the last 30 % of fixtures by id (9 items) are the **primary** evaluation set; all
  30 fixtures are reported as a secondary number. The split is by item, not by user — there are no
  real users.
* Relevance grade per selected item: 2 if it carries ≥ 2 of the case's relevant labels (or all when
  only one), 1 if it carries one, 0 otherwise.

### Metrics (K = 5 per platform)

precision@K, NDCG@K (graded), creator diversity (distinct creators / selected), duplicate rate,
constraint violations (explicit duration/exclusion), consumption-budget adherence, model calls, latency.

## Observed results (run of 2026-11-03, fake provider, `ranking-v1`, default weights)

Primary — held-out fixtures (9 items):

| Variant | precision@5 | NDCG@5 | creator diversity | duplicate rate | constraint violations | budget adherence | model calls / case | latency |
|---|---|---|---|---|---|---|---|---|
| baseline | 0.142 | 0.389 | 1.00 | 0.00 | 0 | 100 % | 0 | ~1 ms |
| enhanced | 0.142 | 0.389 | 1.00 | 0.00 | 0 | 100 % | 8.8 | ~3 ms |

Secondary — all 30 fixtures:

| Variant | precision@5 | NDCG@5 | creator diversity | duplicate rate | constraint violations | budget adherence | model calls / case | latency |
|---|---|---|---|---|---|---|---|---|
| baseline | 0.300 | 0.652 | 0.98 | 0.00 | 0 | 100 % | 0 | ~9 ms |
| enhanced | 0.300 | 0.652 | 0.98 | 0.00 | 0 | 100 % | 20 | ~17 ms |

## Interpretation (what these numbers do and do not say)

* **Hard constraints hold**: zero duplicates, zero explicit-constraint violations and full budget
  adherence in every case and both variants — this is the regression property the harness exists for.
* **Precision is bounded by the tiny label set**, not only by ranking quality: with 9 held-out items,
  most cases have 0–2 relevant items, so precision@5 cannot exceed 0.2–0.4 even for a perfect ranker.
  Treat the absolute values as a smoke level, not as an accuracy claim.
* **Enhanced equals baseline** here because the fake provider derives topics deterministically from
  the same text the baseline already matches on; it adds cost (8.8–20 calls per case) without new
  information. This is the expected and honest result for a *fake* provider: it validates plumbing,
  validation and fallbacks, not model value. A real local model (Ollama) may change topics,
  summaries and near-duplicate detection; that comparison has **not** been run (no Ollama in the build
  environment) and must be repeated with the same command once models are installed.
* No LLM-as-judge is used anywhere; the fixture tags are the only labels.

## Limitations

1. Synthetic items and labels written by the developer; no real feeds, no real users, no user study.
2. No efficacy or "time saved" measurement exists. Any such claim requires a consented user study
   with before/after usage data; the export endpoint and `model_runs`/`job_events` tables provide the
   telemetry hooks for it.
3. The held-out split protects only against over-fitting the hand-written cases to specific fixtures.
4. Weights are engineering heuristics (`FF_RANKING_WEIGHTS_JSON`); no tuning was performed.

## Future dataset / export interface (for consented experiments)

`GET /api/v1/privacy/export` returns, per user, every batch with its ranked items, score components,
explanations and the user's feedback actions. Combined with `preferences_snapshot` and
`config_version` on each batch this is sufficient to build an offline dataset of
(context, candidate, components, user feedback) tuples for later learning-to-rank experiments.
No model training was performed in this sprint.
