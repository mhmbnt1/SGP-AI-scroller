from focusfeed_api.evaluation import run_evaluation


def test_evaluation_harness_runs_and_reports_both_variants():
    report = run_evaluation()
    assert report["dataset"]["held_out_items"] > 0
    assert set(report["summary"]) == {"baseline", "enhanced"}
    for variant in ("baseline", "enhanced"):
        s = report["summary"][variant]
        assert 0.0 <= s["precision_at_k"] <= 1.0 and 0.0 <= s["ndcg_at_k"] <= 1.0
        assert s["duplicate_rate"] == 0.0
        assert s["constraint_violations"] == 0
        assert s["budget_adherence_rate"] == 1.0
    assert report["summary"]["baseline"]["model_calls"] == 0
    assert report["summary"]["enhanced"]["model_calls"] > 0
    assert len(report["per_query"]) == 2 * report["dataset"]["cases"]
    assert report["limitations"]
