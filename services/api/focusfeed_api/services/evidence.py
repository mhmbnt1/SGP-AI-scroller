"""Evidence enrichment for live candidates: captions (yt-dlp) and sampled frames (ffmpeg).

Safety/cost rules
-----------------
* Tools are invoked with fixed argv arrays (never a shell), fixed executable
  lookup via ``shutil.which`` and hard timeouts. URLs are validated by the
  SSRF guard *and* restricted to the platform allowlist before any call.
* Work is bounded by the job budget: ``max_media_items``, ``max_download_bytes``,
  ``max_frames_per_item``, ``max_analyzed_seconds``, per-stage timeout.
* Temp files live in a per-job directory created with ``tempfile.mkdtemp`` and are
  removed afterwards; filenames are derived from UUIDs, never from page content.
* Nothing here is enabled unless FF_ENABLE_YTDLP / FF_ENABLE_FFMPEG are true.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # noqa: S404 - fixed argv, no shell
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ff_protocol import TranscriptSegment
from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.models import CollectionJob, ContentItem, EvidenceArtifact, UserObservation
from focusfeed_api.providers.base import CancelToken
from focusfeed_api.security.ssrf import UnsafeURL, validate_url

CAPTION_DOMAINS = {"youtube.com", "youtu.be"}
_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")


class ToolMissing(Exception):
    pass


@dataclass
class CaptionResult:
    segments: list[TranscriptSegment]
    language: str | None
    source: str  # platform_captions | auto_captions
    method: str


def _ts(s: str) -> float:
    m = _TS.search(s)
    if not m:
        return 0.0
    h, mi, se, ms = (int(x) for x in m.groups())
    return h * 3600 + mi * 60 + se + ms / 1000.0


def parse_vtt(text: str, max_segments: int = 2000) -> list[TranscriptSegment]:
    """Parse WebVTT into segments; merges rolling duplicate lines produced by auto-captions."""
    segments: list[TranscriptSegment] = []
    last_text = ""
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        if not lines:
            continue
        timing = next((ln for ln in lines if "-->" in ln), None)
        if timing is None:
            continue
        start_s, end_s = timing.split("-->")[:2]
        start, end = _ts(start_s), _ts(end_s.strip().split(" ")[0])
        content = " ".join(_TAG.sub("", ln).strip() for ln in lines[lines.index(timing) + 1 :])
        content = re.sub(r"\s+", " ", content).strip()
        if not content or content == last_text:
            continue
        last_text = content
        if end < start:
            end = start
        segments.append(TranscriptSegment(start_s=round(start, 3), end_s=round(end, 3), text=content[:2000]))
        if len(segments) >= max_segments:
            break
    return segments


def coverage(segments: list[TranscriptSegment], duration_seconds: int | None) -> float:
    if not duration_seconds or duration_seconds <= 0 or not segments:
        return 0.0
    covered = sum(max(0.0, s.end_s - s.start_s) for s in segments)
    return max(0.0, min(1.0, covered / duration_seconds))


def fetch_captions(
    url: str, *, languages: list[str], timeout_seconds: int, max_bytes: int, workdir: Path
) -> CaptionResult | None:
    """Download subtitles only (no media) with yt-dlp. Returns None when no captions exist."""
    exe = shutil.which("yt-dlp")
    if not exe:
        raise ToolMissing("yt-dlp is not installed")
    safe = validate_url(url, allowed_domains=CAPTION_DOMAINS)
    langs = ",".join(languages) if languages else "en"
    out_tpl = str(workdir / f"{uuid.uuid4().hex}.%(ext)s")
    argv = [
        exe,
        "--no-warnings",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        langs,
        "--sub-format",
        "vtt",
        "--no-playlist",
        "--no-cache-dir",
        "--max-filesize",
        str(max_bytes),
        "-o",
        out_tpl,
        "--",
        safe,
    ]
    try:
        subprocess.run(  # noqa: S603
            argv, capture_output=True, text=True, timeout=timeout_seconds, check=False, cwd=str(workdir)
        )
    except subprocess.TimeoutExpired:
        return None
    vtts = sorted(workdir.glob("*.vtt"))
    if not vtts:
        return None
    chosen = vtts[0]
    if chosen.stat().st_size > max_bytes:
        return None
    text = chosen.read_text(encoding="utf-8", errors="replace")
    segments = parse_vtt(text)
    if not segments:
        return None
    lang_match = re.search(r"\.([a-zA-Z-]{2,10})\.vtt$", chosen.name)
    lang = lang_match.group(1) if lang_match else None
    # yt-dlp names auto captions identically; treat 'auto' as auto_captions if the file came from --write-auto-subs only.
    source = "auto_captions" if "auto" in chosen.name.lower() else "platform_captions"
    return CaptionResult(segments=segments, language=lang, source=source, method="yt-dlp subtitles")


def sample_frames(
    media_path: Path, *, duration_seconds: int, max_frames: int, timeout_seconds: int, workdir: Path
) -> list[float]:
    """Extract up to ``max_frames`` evenly spaced JPEG frames from a *local* media file with ffmpeg. Returns timestamps."""
    exe = shutil.which("ffmpeg")
    if not exe:
        raise ToolMissing("ffmpeg is not installed")
    if max_frames <= 0 or duration_seconds <= 0:
        return []
    stamps = [round(duration_seconds * (i + 1) / (max_frames + 1), 2) for i in range(max_frames)]
    out: list[float] = []
    for ts in stamps:
        target = workdir / f"frame_{uuid.uuid4().hex}.jpg"
        argv = [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            str(ts),
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-q:v",
            "4",
            "-y",
            str(target),
        ]
        try:
            subprocess.run(argv, capture_output=True, timeout=timeout_seconds, check=False)  # noqa: S603
        except subprocess.TimeoutExpired:
            break
        if target.exists():
            out.append(ts)
    return out


def enrich_job_evidence(db: Session, job: CollectionJob, *, cancel: CancelToken | None = None) -> int:
    """Add transcript evidence for the most plausible live YouTube candidates within budget. Returns artifacts added."""
    settings = get_settings()
    if not settings.ff_enable_ytdlp:
        return 0
    budget = job.budget or {}
    max_items = int(budget.get("max_media_items", 10))
    max_bytes = int(budget.get("max_download_bytes", 50_000_000))
    stage_timeout = int(budget.get("per_stage_timeout_seconds", 120))
    rows = db.execute(
        select(ContentItem, UserObservation)
        .join(UserObservation, UserObservation.item_id == ContentItem.id)
        .where(
            UserObservation.job_id == job.id,
            UserObservation.user_id == job.user_id,
            ContentItem.platform == "youtube",
        )
        .order_by(UserObservation.feed_position.nulls_last())
    ).all()
    from focusfeed_api.models import PreferenceProfile

    prof = db.scalar(select(PreferenceProfile).where(PreferenceProfile.user_id == job.user_id))
    languages = list(prof.languages) if prof and prof.languages else ["en"]
    added = 0
    workdir = Path(tempfile.mkdtemp(prefix="ff-evidence-"))
    try:
        for item, _obs in rows[:max_items]:
            if cancel is not None and cancel.cancelled:
                break
            exists = db.scalar(
                select(EvidenceArtifact.id).where(
                    EvidenceArtifact.user_id == job.user_id,
                    EvidenceArtifact.item_id == item.id,
                    EvidenceArtifact.job_id == job.id,
                    EvidenceArtifact.kind == "transcript",
                )
            )
            if exists is not None:
                continue
            try:
                res = fetch_captions(
                    item.canonical_url,
                    languages=languages,
                    timeout_seconds=min(stage_timeout, 60),
                    max_bytes=min(max_bytes, 2_000_000),
                    workdir=workdir,
                )
            except (ToolMissing, UnsafeURL):
                break
            if res is None:
                continue
            db.add(
                EvidenceArtifact(
                    user_id=job.user_id,
                    item_id=item.id,
                    job_id=job.id,
                    kind="transcript",
                    transcript_source=res.source,
                    coverage_ratio=coverage(res.segments, item.duration_seconds),
                    segments=[s.model_dump() for s in res.segments],
                    frames=[],
                    extraction_method=res.method,
                    language=res.language,
                    retention_until=datetime.now(UTC) + timedelta(days=settings.ff_retention_days),
                )
            )
            added += 1
        db.flush()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return added
