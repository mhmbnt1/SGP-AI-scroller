"""Contract-only adapters (TikTok, X, LinkedIn): typed interface exists, extraction not implemented.

They always report ``unsupported`` so the backend can show honest status and never dispatch work to them.
"""

from __future__ import annotations

from typing import Any

from ff_protocol import (
    AdapterCapabilities,
    CollectionMode,
    CollectorResultState,
    JobBudget,
    Platform,
    PlatformResult,
    SessionStatus,
)

from focusfeed_collector.adapters.base import PlatformAdapter

_HOME = {
    Platform.tiktok: "https://www.tiktok.com/foryou",
    Platform.x: "https://x.com/home",
    Platform.linkedin: "https://www.linkedin.com/feed/",
}
_LOGIN = {
    Platform.tiktok: "https://www.tiktok.com/login",
    Platform.x: "https://x.com/i/flow/login",
    Platform.linkedin: "https://www.linkedin.com/login",
}
_DOMAINS = {
    Platform.tiktok: ("tiktok.com", "tiktokcdn.com"),
    Platform.x: ("x.com", "twimg.com"),
    Platform.linkedin: ("linkedin.com", "licdn.com"),
}


class ContractOnlyAdapter(PlatformAdapter):
    def __init__(self, platform: Platform) -> None:
        self.platform = platform
        self.home_url = _HOME[platform]
        self.login_url = _LOGIN[platform]
        self.allowed_domains = _DOMAINS[platform]

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            platform=self.platform,
            status="contract_only",
            notes="adapter contract defined; extraction not implemented",
        )

    def session_status(self, page: Any) -> SessionStatus:
        return SessionStatus.unsupported

    def collect_personalized_feed(
        self, page: Any, budget: JobBudget, checkpoint: list[str], **kw: Any
    ) -> PlatformResult:
        return PlatformResult(
            platform=self.platform,
            state=CollectorResultState.unsupported,
            collection_mode=CollectionMode.personalized_feed,
            stop_reason="not implemented",
        )
