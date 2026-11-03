"""In-process demo adapter: implements the platform adapter contract over synthetic fixtures.

It exists so the *entire* job flow (queue -> collection -> ingest -> enrich ->
rank -> batch) runs end-to-end without a browser or a social account. It never
runs in live mode for real platforms.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from ff_protocol import (
    AdapterCapabilities,
    CollectionMode,
    CollectorJobInstruction,
    CollectorResultState,
    JobBudget,
    Platform,
    PlatformResult,
    SessionStatus,
)

from focusfeed_api.fixtures.demo_content import demo_candidates


class DemoAdapter:
    platform: Platform

    def __init__(self, platform: Platform, *, simulate_delay_s: float = 0.0, fail_with: CollectorResultState | None = None) -> None:
        self.platform = platform
        self.simulate_delay_s = simulate_delay_s
        self.fail_with = fail_with

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            platform=self.platform, personalized_feed=True, public_search=True, extract_item=True, captions=True,
            status="implemented", notes="synthetic fixtures (demo/test only)",
        )

    def session_status(self) -> SessionStatus:
        return SessionStatus.available

    def collect_personalized_feed(self, request: CollectorJobInstruction, budget: JobBudget,
                                  checkpoint: list[str] | None = None, cancel_check=None) -> PlatformResult:
        return self._collect(request, budget, checkpoint or [], query=None, cancel_check=cancel_check)

    def search_public_content(self, request: CollectorJobInstruction, budget: JobBudget, cancel_check=None) -> PlatformResult:
        return self._collect(request, budget, [], query=request.query, cancel_check=cancel_check)

    def extract_item(self, reference: str, budget: JobBudget):
        for items in demo_candidates([self.platform.value]).values():
            for c in items:
                if c.external_id == reference:
                    return c
        return None

    def disconnect(self) -> None:
        return None

    def _collect(self, request, budget, checkpoint, *, query, cancel_check) -> PlatformResult:
        if self.fail_with is not None:
            return PlatformResult(
                platform=self.platform, state=self.fail_with,
                collection_mode=CollectionMode.synthetic_fixture, stop_reason=f"simulated {self.fail_with.value}",
            )
        mode = CollectionMode.synthetic_fixture
        items = demo_candidates([self.platform.value], query=query, limit_per_platform=budget.max_candidates_per_platform)[
            self.platform.value
        ]
        seen = set(checkpoint)
        out = []
        steps = 0
        for i, c in enumerate(items):
            if cancel_check is not None and cancel_check():
                return PlatformResult(
                    platform=self.platform, state=CollectorResultState.cancelled, collection_mode=mode, items=out,
                    scroll_steps=steps, stop_reason="cancelled", checkpoint_external_ids=[x.external_id for x in out],
                )
            if i % 5 == 0:
                steps += 1
                if steps > budget.max_scroll_steps_per_platform:
                    break
                if self.simulate_delay_s:
                    time.sleep(self.simulate_delay_s)
            if c.external_id in seen:
                continue
            out.append(c.model_copy(update={"observed_at": datetime.now(UTC)}))
        return PlatformResult(
            platform=self.platform, state=CollectorResultState.available, collection_mode=mode, items=out,
            scroll_steps=steps, stop_reason="budget_reached" if len(out) >= budget.max_candidates_per_platform else "feed_exhausted",
            checkpoint_external_ids=[x.external_id for x in out],
        )
