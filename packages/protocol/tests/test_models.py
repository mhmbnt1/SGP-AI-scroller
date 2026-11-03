from datetime import UTC, datetime

import pytest
from ff_protocol import (
    AnalysisKind,
    CandidateItem,
    CollectionMode,
    EvidenceBundle,
    JobBudget,
    Platform,
    TranscriptSegment,
)
from pydantic import ValidationError


def _item(**overrides):
    base = dict(
        platform=Platform.youtube,
        external_id="abc123",
        canonical_url="https://www.youtube.com/watch?v=abc123",
        observed_at=datetime.now(UTC),
        collection_mode=CollectionMode.synthetic_fixture,
    )
    base.update(overrides)
    return CandidateItem(**base)


def test_candidate_rejects_non_http_url():
    with pytest.raises(ValidationError):
        _item(canonical_url="file:///etc/passwd")
    with pytest.raises(ValidationError):
        _item(canonical_url="javascript:alert(1)")


def test_candidate_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        _item(extra_field="x")


def test_evidence_analysis_kind_labels():
    assert EvidenceBundle().analysis_kind == AnalysisKind.metadata_only
    t = EvidenceBundle(transcript_segments=[TranscriptSegment(start_s=0, end_s=5, text="hi")])
    assert t.analysis_kind == AnalysisKind.transcript_supported
    f = EvidenceBundle(frame_samples=[{"timestamp_s": 1.0, "observation": "a kitchen"}])
    assert f.analysis_kind == AnalysisKind.sampled_visual
    c = EvidenceBundle(
        transcript_segments=[TranscriptSegment(start_s=0, end_s=5, text="hi")],
        frame_samples=[{"timestamp_s": 1.0}],
    )
    assert c.analysis_kind == AnalysisKind.combined


def test_transcript_segment_ordering():
    with pytest.raises(ValidationError):
        TranscriptSegment(start_s=10, end_s=5, text="x")


def test_budget_bounds():
    with pytest.raises(ValidationError):
        JobBudget(max_candidates_per_platform=0)
    with pytest.raises(ValidationError):
        JobBudget(max_wall_clock_seconds=100_000)
