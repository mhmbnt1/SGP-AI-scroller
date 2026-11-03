"""Honest platform capability/status matrix.

``live_verified`` is only true when a live smoke check has actually been run
and recorded in docs/VERIFICATION.md. It is false for every platform in this
repository snapshot because no social credentials were available.
"""

from __future__ import annotations

from focusfeed_api.config import get_settings

PLATFORM_MATRIX: dict[str, dict] = {
    "youtube": {
        "display_name": "YouTube / Shorts",
        "personalized_feed": True, "public_search": True, "extract_item": True, "captions": True,
        "status": "implemented", "live_verified": False,
        "notes": "Playwright adapter for the signed-in home feed and Shorts shelf; public search supported; captions via yt-dlp when enabled. Tested against recorded DOM fixtures only.",
    },
    "instagram": {
        "display_name": "Instagram Reels",
        "personalized_feed": True, "public_search": False, "extract_item": True, "captions": False,
        "status": "implemented", "live_verified": False,
        "notes": "Playwright adapter for the signed-in Reels feed. No public search (requires login). Captions come from the post caption only. Tested against recorded DOM fixtures only.",
    },
    "tiktok": {
        "display_name": "TikTok",
        "personalized_feed": False, "public_search": False, "extract_item": False, "captions": False,
        "status": "contract_only", "live_verified": False,
        "notes": "Adapter contract and typed DTOs exist; no extraction implemented yet.",
    },
    "x": {
        "display_name": "X",
        "personalized_feed": False, "public_search": False, "extract_item": False, "captions": False,
        "status": "contract_only", "live_verified": False,
        "notes": "Adapter contract only.",
    },
    "linkedin": {
        "display_name": "LinkedIn",
        "personalized_feed": False, "public_search": False, "extract_item": False, "captions": False,
        "status": "contract_only", "live_verified": False,
        "notes": "Adapter contract only.",
    },
    "demo": {
        "display_name": "Demo (synthetic)",
        "personalized_feed": True, "public_search": True, "extract_item": True, "captions": True,
        "status": "synthetic", "live_verified": False,
        "notes": "Labelled synthetic fixtures through the real job pipeline. Not real feed data.",
    },
}


def capability_rows() -> list[dict]:
    settings = get_settings()
    rows = []
    for key, v in PLATFORM_MATRIX.items():
        row = {"platform": key, **v}
        if key == "demo" and settings.ff_mode == "live":
            row["status"] = "disabled"
            row["notes"] = "Demo platform is disabled in live mode."
        if key == "youtube" and not settings.ff_enable_ytdlp:
            row["captions"] = False
            row["notes"] += " (captions disabled: FF_ENABLE_YTDLP=false)"
        rows.append(row)
    return rows


def next_step_for(status: str, mode: str) -> str:
    if mode != "live":
        return "Demo/test mode: no collector required."
    return {
        "available": "Connected. Collection will run on your schedule or when you refresh.",
        "needs_login": "Run `focusfeed-collector login <platform>` on your PC and sign in inside the dedicated browser window.",
        "collector_offline": "Start the collector on your PC: `focusfeed-collector run`.",
        "challenge_required": "Open the platform in the dedicated browser and complete the verification yourself, then retry.",
        "rate_limited": "The platform is limiting requests. Wait a while before the next run.",
        "upstream_changed": "The platform layout changed; an adapter update is required. Collection is paused for this platform.",
        "unsupported": "This platform is not implemented yet.",
        "timeout": "The last run timed out. Try again with a smaller budget.",
    }.get(status, "Check the collector status on your PC.")
