"""Platform adapter contract.

One contract covers all platforms:

* ``capabilities()``                  — static, honest capability flags
* ``session_status(page)``            — available | needs_login | challenge_required | ...
* ``collect_personalized_feed(...)``  — bounded scrolling + extraction with checkpoints
* ``search_public_content(...)``      — only where actually supported
* ``extract_item(...)``               — single item metadata
* ``disconnect()``                    — clear the dedicated profile

Extraction logic is a JS snippet (``EXTRACT_JS``) evaluated in the page and
post-processed in Python, so the same code can be tested against recorded /
synthetic DOM fixtures with ``page.set_content``.
"""

from __future__ import annotations

import hashlib
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ff_protocol import (
    AdapterCapabilities,
    CandidateItem,
    CollectionMode,
    CollectorResultState,
    EvidenceBundle,
    JobBudget,
    Platform,
    PlatformResult,
    SessionStatus,
)
from pydantic import HttpUrl

_DURATION_RE = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{2})$")


def parse_duration(text: str | None) -> int | None:
    """'12:34' -> 754; '1:02:03' -> 3723; None/garbage -> None."""
    if not text:
        return None
    m = _DURATION_RE.match(text.strip())
    if not m:
        return None
    h, mm, ss = m.groups()
    return (int(h) if h else 0) * 3600 + int(mm) * 60 + int(ss)


def fingerprint(*parts: str | None) -> str:
    return hashlib.sha256("|".join(p or "" for p in parts).encode()).hexdigest()[:32]


class PlatformAdapter(ABC):
    platform: Platform
    home_url: str
    login_url: str
    allowed_domains: tuple[str, ...]
    EXTRACT_JS: str = "() => []"

    # ------------------------------------------------------------- contract

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    def session_status(self, page: Any) -> SessionStatus: ...

    def raw_to_candidate(
        self, raw: dict[str, Any], mode: CollectionMode, position: int
    ) -> CandidateItem | None:
        """Convert one raw extracted record to a validated CandidateItem; None when unusable."""
        eid = str(raw.get("external_id") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not eid or not url.startswith("https://"):
            return None
        try:
            return CandidateItem(
                platform=self.platform,
                external_id=eid[:200],
                canonical_url=HttpUrl(url[:2000]),
                creator_handle=(str(raw.get("creator_handle") or "")[:200] or None),
                creator_name=(str(raw.get("creator_name") or "")[:200] or None),
                title=(str(raw.get("title") or "")[:1000] or None),
                caption=(str(raw.get("caption") or "")[:5000] or None),
                language=None,
                duration_seconds=parse_duration(raw.get("duration_text"))
                if raw.get("duration_text")
                else raw.get("duration_seconds"),
                published_at=None,
                observed_at=datetime.now(UTC),
                collection_mode=mode,
                feed_position=position,
                thumbnail_url=(
                    HttpUrl(str(raw.get("thumbnail_url"))[:2000])
                    if str(raw.get("thumbnail_url") or "").startswith("https://")
                    else None
                ),
                evidence=EvidenceBundle(
                    missing_fields=[k for k in ("title", "duration_text", "creator_handle") if not raw.get(k)]
                ),
                raw_fingerprint=fingerprint(eid, raw.get("title"), raw.get("creator_handle")),
            )
        except Exception:
            return None

    def collect_personalized_feed(
        self,
        page: Any,
        budget: JobBudget,
        checkpoint: list[str],
        *,
        cancel_check: Callable[[], bool] | None = None,
        deadline: float | None = None,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> PlatformResult:
        status = self.session_status(page)
        if status != SessionStatus.available:
            return PlatformResult(
                platform=self.platform,
                state=CollectorResultState(status.value),
                collection_mode=CollectionMode.personalized_feed,
                stop_reason=f"session status {status.value}",
            )
        return self._scroll_and_extract(
            page,
            budget,
            set(checkpoint),
            CollectionMode.personalized_feed,
            cancel_check,
            deadline,
            on_progress,
        )

    def search_public_content(
        self, page: Any, query: str, budget: JobBudget, *, cancel_check=None, deadline=None, on_progress=None
    ) -> PlatformResult:
        return PlatformResult(
            platform=self.platform,
            state=CollectorResultState.unsupported,
            collection_mode=CollectionMode.public_search,
            stop_reason="public search not supported by this adapter",
        )

    def extract_item(self, page: Any, reference: str, budget: JobBudget) -> CandidateItem | None:
        return None

    def disconnect(self, profile_dir) -> None:
        import shutil

        shutil.rmtree(profile_dir, ignore_errors=True)

    # ------------------------------------------------------------- shared scrolling loop

    def _scroll_and_extract(
        self,
        page: Any,
        budget: JobBudget,
        seen: set[str],
        mode: CollectionMode,
        cancel_check,
        deadline,
        on_progress,
    ) -> PlatformResult:
        items: list[CandidateItem] = []
        collected_ids: list[str] = []
        steps = 0
        stale_steps = 0
        stop_reason = "feed_exhausted"
        state = CollectorResultState.available
        upstream_zero = True
        while True:
            if cancel_check is not None and cancel_check():
                state, stop_reason = CollectorResultState.cancelled, "cancelled"
                break
            if deadline is not None and time.monotonic() > deadline:
                state, stop_reason = (
                    CollectorResultState.partial if items else CollectorResultState.timeout,
                    "deadline",
                )
                break
            raw_items = self._extract(page)
            if raw_items:
                upstream_zero = False
            new = 0
            for raw in raw_items:
                eid = str(raw.get("external_id") or "")
                if not eid or eid in seen:
                    continue
                cand = self.raw_to_candidate(raw, mode, len(items))
                if cand is None:
                    continue
                seen.add(eid)
                items.append(cand)
                collected_ids.append(eid)
                new += 1
                if len(items) >= budget.max_candidates_per_platform:
                    break
            if on_progress is not None:
                on_progress("scroll", {"step": steps, "new": new, "total": len(items)})
            if len(items) >= budget.max_candidates_per_platform:
                stop_reason = "budget_reached"
                break
            steps += 1
            if steps >= budget.max_scroll_steps_per_platform:
                stop_reason = "max_scroll_steps"
                break
            stale_steps = stale_steps + 1 if new == 0 else 0
            if stale_steps >= 3:
                stop_reason = "no_new_items"
                break
            self._scroll_once(page)
        if upstream_zero and not items and state == CollectorResultState.available:
            state, stop_reason = (
                CollectorResultState.upstream_changed,
                "no items matched the expected page structure",
            )
        if state == CollectorResultState.available and self._rate_limited(page):
            state, stop_reason = CollectorResultState.rate_limited, "platform returned rate-limit responses"
        return PlatformResult(
            platform=self.platform,
            state=state,
            collection_mode=mode,
            items=items,
            scroll_steps=steps,
            stop_reason=stop_reason,
            checkpoint_external_ids=collected_ids[:1000],
        )

    def _extract(self, page: Any) -> list[dict[str, Any]]:
        try:
            out = page.evaluate(self.EXTRACT_JS)
        except Exception:
            return []
        return [x for x in out if isinstance(x, dict)] if isinstance(out, list) else []

    def _scroll_once(self, page: Any) -> None:
        try:
            page.mouse.wheel(0, 1600)
        except Exception:
            try:
                page.evaluate("() => window.scrollBy(0, 1600)")
            except Exception:
                pass
        try:
            page.wait_for_timeout(1200)
        except Exception:
            time.sleep(1.2)

    def _rate_limited(self, page: Any) -> bool:
        return bool(getattr(page, "_ff_rate_limited", False))


def get_adapter(platform: str) -> PlatformAdapter:
    from focusfeed_collector.adapters.contract_only import ContractOnlyAdapter
    from focusfeed_collector.adapters.instagram import InstagramAdapter
    from focusfeed_collector.adapters.youtube import YouTubeAdapter

    if platform == "youtube":
        return YouTubeAdapter()
    if platform == "instagram":
        return InstagramAdapter()
    if platform in ("tiktok", "x", "linkedin"):
        return ContractOnlyAdapter(Platform(platform))
    raise KeyError(platform)
