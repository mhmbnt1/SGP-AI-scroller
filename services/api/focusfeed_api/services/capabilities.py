"""Runtime capability registry.

Each entry resolves to a *reviewed* implementation inside this repository
(``entry_point`` is a dotted path checked against an allowlist of project
modules). Nothing here can be pointed at a user- or model-supplied path.
Disabled/unavailable capabilities are listed explicitly with a reason.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass, field
from typing import Any

from focusfeed_api.config import get_settings

ALLOWED_MODULE_PREFIXES = ("focusfeed_api.", "focusfeed_worker.", "focusfeed_collector.", "ff_protocol")


@dataclass(frozen=True)
class CapabilityEntry:
    id: str
    version: str
    purpose: str
    when_to_use: str
    input_schema: str  # pydantic model / dataclass name
    output_schema: str
    permissions: list[str]
    domains: list[str]
    dependencies: list[str]
    timeout_seconds: int
    resource_limits: dict[str, Any]
    platforms: list[str]
    model_requirements: str
    error_codes: list[str]
    retryable_errors: list[str]
    entry_point: str
    tests: list[str]
    provenance: str
    status: str = "available"  # available | disabled | unavailable
    status_reason: str = ""


_REGISTRY: list[CapabilityEntry] = [
    CapabilityEntry(
        id="session.connect",
        version="1.0",
        purpose="Pair a local collector, check platform session health, isolate the dedicated browser profile, revoke.",
        when_to_use="Before any live collection; on connection status screens.",
        input_schema="EnrollmentExchange | HeartbeatIn",
        output_schema="EnrollmentExchangeOut | HeartbeatOut",
        permissions=["user:authenticated", "device:credential"],
        domains=[],
        dependencies=["postgresql"],
        timeout_seconds=10,
        resource_limits={"enrollments_per_minute": 5, "enrollment_ttl_minutes": 10},
        platforms=["youtube", "instagram", "tiktok", "x", "linkedin"],
        model_requirements="none",
        error_codes=["enrollment_invalid", "device_revoked", "rate_limited"],
        retryable_errors=["rate_limited"],
        entry_point="focusfeed_api.services.collectors",
        tests=["services/api/tests/test_collectors.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="feed.collect",
        version="1.0",
        purpose="Bounded scrolling of an authenticated personalized feed and candidate extraction.",
        when_to_use="Daily queryless batch jobs.",
        input_schema="CollectorJobInstruction",
        output_schema="PlatformResult",
        permissions=["device:credential", "job:lease"],
        domains=["youtube.com", "instagram.com"],
        dependencies=["playwright", "chromium"],
        timeout_seconds=600,
        resource_limits={"max_scroll_steps": 12, "max_candidates": 40, "max_wall_clock_s": 600},
        platforms=["youtube", "instagram"],
        model_requirements="none",
        error_codes=[
            "needs_login",
            "challenge_required",
            "upstream_changed",
            "rate_limited",
            "timeout",
            "cancelled",
        ],
        retryable_errors=["timeout", "rate_limited"],
        entry_point="focusfeed_collector.adapters",
        tests=["services/collector/tests/test_adapters.py"],
        provenance="project-authored (selectors inspired by public DOM structure; no upstream code vendored)",
    ),
    CapabilityEntry(
        id="search.public",
        version="1.0",
        purpose="Public search on a platform for explicit natural-language intents.",
        when_to_use="Search mode when the platform adapter reports public_search=true.",
        input_schema="CollectorJobInstruction(query)",
        output_schema="PlatformResult",
        permissions=["device:credential", "job:lease"],
        domains=["youtube.com"],
        dependencies=["playwright"],
        timeout_seconds=300,
        resource_limits={"max_candidates": 40},
        platforms=["youtube"],
        model_requirements="none",
        error_codes=["unsupported", "upstream_changed", "timeout"],
        retryable_errors=["timeout"],
        entry_point="focusfeed_collector.adapters.youtube",
        tests=["services/collector/tests/test_adapters.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="evidence.transcript",
        version="1.0",
        purpose="Fetch platform captions for a candidate (yt-dlp subprocess with fixed argv) and parse VTT into segments.",
        when_to_use="Enrichment of plausible YouTube candidates when FF_ENABLE_YTDLP=true.",
        input_schema="CandidateItem",
        output_schema="EvidenceBundle",
        permissions=["worker"],
        domains=["youtube.com"],
        dependencies=["yt-dlp (optional)"],
        timeout_seconds=60,
        resource_limits={"max_download_bytes": 2_000_000, "max_items_per_job": 10},
        platforms=["youtube"],
        model_requirements="none",
        error_codes=["tool_missing", "timeout", "unavailable"],
        retryable_errors=["timeout"],
        entry_point="focusfeed_api.services.evidence",
        tests=["services/api/tests/test_evidence.py"],
        provenance="approach adapted from Agent-Reach youtube channel (MIT) — reimplemented, not vendored",
        status="disabled" if not get_settings().ff_enable_ytdlp else "available",
        status_reason="" if get_settings().ff_enable_ytdlp else "FF_ENABLE_YTDLP=false",
    ),
    CapabilityEntry(
        id="evidence.frames",
        version="1.0",
        purpose="Sample a bounded number of frames with ffmpeg for optional vision-model observations.",
        when_to_use="Only for candidates without captions when a vision model is configured.",
        input_schema="CandidateItem",
        output_schema="EvidenceBundle.frame_samples",
        permissions=["worker"],
        domains=[],
        dependencies=["ffmpeg (optional)", "vision model (optional)"],
        timeout_seconds=120,
        resource_limits={"max_frames_per_item": 4, "max_analyzed_seconds": 600},
        platforms=["youtube", "instagram"],
        model_requirements="vision-capable model",
        error_codes=["tool_missing", "model_capability_mismatch", "timeout"],
        retryable_errors=["timeout"],
        entry_point="focusfeed_api.services.evidence",
        tests=["services/api/tests/test_evidence.py"],
        provenance="approach adapted from claude-watch frames.py (MIT) — reimplemented without Obsidian/paid transcription",
        status="disabled" if not get_settings().ff_enable_ffmpeg else "available",
        status_reason="" if get_settings().ff_enable_ffmpeg else "FF_ENABLE_FFMPEG=false",
    ),
    CapabilityEntry(
        id="analysis.candidate",
        version="1.0",
        purpose="Grounded topics/summary/evidence refs for one candidate via structured model output.",
        when_to_use="Enrichment stage, bounded by max_model_calls.",
        input_schema="analyze_candidate payload (pipeline.enrich.build_user_payload)",
        output_schema="ANALYSIS_SCHEMA",
        permissions=["worker"],
        domains=[],
        dependencies=["provider: fake|ollama"],
        timeout_seconds=180,
        resource_limits={"max_transcript_chars": 6000, "retries": 1},
        platforms=["all"],
        model_requirements="JSON-capable text model",
        error_codes=["invalid_output", "provider_timeout", "provider_unavailable"],
        retryable_errors=["invalid_output", "provider_timeout"],
        entry_point="focusfeed_api.pipeline.enrich",
        tests=["services/api/tests/test_pipeline.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="intent.interpret",
        version="1.0",
        purpose="Turn an explicit query into keywords/constraints (deterministic parse + optional model refinement).",
        when_to_use="Search mode.",
        input_schema="query string",
        output_schema="Intent",
        permissions=["worker"],
        domains=[],
        dependencies=["provider (optional)"],
        timeout_seconds=60,
        resource_limits={"max_query_chars": 500},
        platforms=["all"],
        model_requirements="optional",
        error_codes=[],
        retryable_errors=[],
        entry_point="focusfeed_api.pipeline.intent",
        tests=["services/api/tests/test_pipeline.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="ranking.select",
        version="1.0",
        purpose="Eligibility, dedup, scoring, MMR diversity, top-K and consumption budget.",
        when_to_use="Every job.",
        input_schema="list[Candidate] + UserContext",
        output_schema="PipelineOutcome",
        permissions=["worker"],
        domains=[],
        dependencies=[],
        timeout_seconds=60,
        resource_limits={"max_candidates": 1200},
        platforms=["all"],
        model_requirements="none",
        error_codes=[],
        retryable_errors=[],
        entry_point="focusfeed_api.pipeline.run",
        tests=["services/api/tests/test_pipeline.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="jobs.orchestrate",
        version="1.0",
        purpose="Persisted state machine with leases, heartbeats, checkpoints, cancellation, retries and schedules.",
        when_to_use="Worker loop.",
        input_schema="CollectionJob",
        output_schema="CollectionJob",
        permissions=["worker"],
        domains=[],
        dependencies=["postgresql"],
        timeout_seconds=600,
        resource_limits={"lease_s": 120, "max_attempts": 3},
        platforms=["all"],
        model_requirements="none",
        error_codes=["lease_conflict", "deadline_exceeded"],
        retryable_errors=["deadline_exceeded"],
        entry_point="focusfeed_worker.orchestrator",
        tests=["services/worker/tests/test_orchestrator.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="security.url_guard",
        version="1.0",
        purpose="SSRF-safe URL validation and bounded fetching for any server-side request.",
        when_to_use="Any fetch of a user- or page-supplied URL.",
        input_schema="url",
        output_schema="FetchResult",
        permissions=["worker"],
        domains=["public only"],
        dependencies=[],
        timeout_seconds=15,
        resource_limits={"max_bytes": 5_000_000, "max_redirects": 3},
        platforms=["all"],
        model_requirements="none",
        error_codes=["unsafe_url"],
        retryable_errors=[],
        entry_point="focusfeed_api.security.ssrf",
        tests=["services/api/tests/test_security.py"],
        provenance="project-authored",
    ),
    CapabilityEntry(
        id="telemetry.evaluate",
        version="1.0",
        purpose="Reproducible evaluation harness over labelled fixtures (precision@K, NDCG, diversity, duplicates, budget adherence).",
        when_to_use="Offline, via scripts/evaluate.py.",
        input_schema="fixtures",
        output_schema="reports/evaluation.json",
        permissions=["developer"],
        domains=[],
        dependencies=[],
        timeout_seconds=120,
        resource_limits={},
        platforms=["demo"],
        model_requirements="fake provider",
        error_codes=[],
        retryable_errors=[],
        entry_point="focusfeed_api.evaluation",
        tests=["services/api/tests/test_evaluation.py"],
        provenance="project-authored",
    ),
]


def list_capabilities() -> list[dict[str, Any]]:
    return [asdict(e) for e in _REGISTRY]


def resolve(entry_id: str):
    """Import the implementation module for a registry entry (allowlisted modules only)."""
    entry = next((e for e in _REGISTRY if e.id == entry_id), None)
    if entry is None:
        raise KeyError(entry_id)
    if not entry.entry_point.startswith(ALLOWED_MODULE_PREFIXES):
        raise PermissionError("entry point outside allowed modules")
    return importlib.import_module(entry.entry_point)


def entry_ids() -> list[str]:
    return [e.id for e in _REGISTRY]


__all__ = ["CapabilityEntry", "entry_ids", "list_capabilities", "resolve", "field"]
