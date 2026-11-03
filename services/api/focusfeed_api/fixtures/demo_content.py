"""Synthetic, clearly-labelled demo content.

Every item is marked ``collection_mode=synthetic_fixture`` and ``is_synthetic``
so it can never be confused with real personalized-feed data. The ``labels``
field carries topic labels used by the evaluation harness (synthetic labels
are for regression checks, not evidence of real-world efficacy).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ff_protocol import CandidateItem, CollectionMode, EvidenceBundle, Platform, TranscriptSegment, TranscriptSource

FIXTURE_EPOCH = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@dataclass
class DemoItem:
    platform: str
    external_id: str
    creator: str
    title: str
    caption: str
    duration: int | None
    age_days: float
    language: str
    labels: list[str]
    transcript: list[str] = field(default_factory=list)
    feed_rank: int = 0

    @property
    def url(self) -> str:
        if self.platform == "youtube":
            return f"https://www.youtube.com/watch?v={self.external_id}"
        if self.platform == "instagram":
            return f"https://www.instagram.com/reel/{self.external_id}/"
        return f"https://demo.focusfeed.invalid/items/{self.external_id}"

    def to_candidate(self, mode: CollectionMode = CollectionMode.synthetic_fixture, feed_position: int | None = None) -> CandidateItem:
        segments = []
        if self.transcript and self.duration:
            per = self.duration / max(1, len(self.transcript))
            segments = [
                TranscriptSegment(start_s=round(i * per, 1), end_s=round((i + 1) * per, 1), text=t)
                for i, t in enumerate(self.transcript)
            ]
        evidence = EvidenceBundle(
            transcript_source=TranscriptSource.fixture if segments else TranscriptSource.none,
            transcript_language=self.language if segments else None,
            transcript_segments=segments,
            coverage_ratio=0.9 if segments else 0.0,
            extraction_method="fixture_transcript" if segments else "fixture_metadata",
            missing_fields=[] if self.duration else ["duration"],
        )
        return CandidateItem(
            platform=Platform(self.platform),
            external_id=self.external_id,
            canonical_url=self.url,
            creator_handle=self.creator,
            creator_name=self.creator.replace("_", " ").title(),
            title=self.title,
            caption=self.caption,
            language=self.language,
            duration_seconds=self.duration,
            published_at=FIXTURE_EPOCH - timedelta(days=self.age_days),
            observed_at=FIXTURE_EPOCH,
            collection_mode=mode,
            feed_position=feed_position if feed_position is not None else self.feed_rank,
            thumbnail_url=None,
            evidence=evidence,
        )


def _yt(eid, creator, title, caption, duration, age, labels, transcript=None, lang="en"):
    return DemoItem("youtube", eid, creator, title, caption, duration, age, lang, labels, transcript or [])


def _ig(eid, creator, title, caption, duration, age, labels, transcript=None, lang="en"):
    return DemoItem("instagram", eid, creator, title, caption, duration, age, lang, labels, transcript or [])


DEMO_ITEMS: list[DemoItem] = [
    # ---- cooking
    _yt("yt_cook_001", "weeknight_kitchen", "High-protein chicken stir fry in 15 minutes", "Quick weeknight dinner: 42g protein per serving. Full recipe below.", 540, 1.2, ["cooking", "high-protein", "quick-meals"],
        ["Tonight we're making a high protein chicken stir fry that takes about fifteen minutes.", "You need chicken breast, broccoli, soy sauce, garlic and ginger.", "Slice the chicken thin so it cooks fast, then sear it in a hot pan.", "Add the vegetables, the sauce, and serve over rice. Forty-two grams of protein."]),
    _yt("yt_cook_002", "weeknight_kitchen", "Meal prep: 5 lunches for under $20", "Budget meal prep with lentils, rice and roasted vegetables.", 780, 4.0, ["cooking", "meal-prep", "budget"],
        ["Five lunches for under twenty dollars, let's go.", "Lentils are the cheapest protein you can buy.", "Roast a tray of vegetables while the rice cooks.", "Portion everything into containers and you're done for the week."]),
    _ig("ig_cook_001", "proteinplates", "20-minute salmon bowl", "Salmon, quinoa, edamame. 38g protein. #highprotein #quickmeals", 58, 0.5, ["cooking", "high-protein", "quick-meals"],
        ["Salmon bowl in twenty minutes.", "Season the salmon, air fry for twelve minutes.", "Quinoa, edamame, cucumber, and a soy lime dressing.", "Thirty-eight grams of protein."]),
    _ig("ig_cook_002", "sweettoothdaily", "Triple chocolate lava cake", "The most decadent dessert you'll make this week.", 45, 2.0, ["cooking", "dessert"],
        ["Triple chocolate lava cake.", "Dark chocolate, butter, sugar, eggs, a little flour.", "Bake for exactly eleven minutes."]),
    _yt("yt_cook_003", "slowfoodlab", "Sourdough starter from scratch: a 7-day guide", "Everything you need to know to build a reliable starter.", 1500, 20.0, ["cooking", "baking"],
        ["Welcome to the seven day sourdough starter guide.", "Day one: equal parts flour and water, leave it covered.", "By day four you should see bubbles and a sour smell."]),
    # ---- fitness
    _yt("yt_fit_001", "coach_amira", "Beginner strength program: 3 days a week", "Squat, hinge, push, pull. Progressive overload explained simply.", 900, 3.0, ["fitness", "strength"],
        ["This is the only beginner strength program you need.", "Three days a week: squat, hinge, push, pull.", "Add two and a half kilos whenever you complete all sets.", "Rest at least a day between sessions."]),
    _ig("ig_fit_001", "coach_amira", "Fix your squat depth in 60 seconds", "Ankle mobility drill that actually works.", 60, 0.8, ["fitness", "mobility"],
        ["If your squat is shallow, try this ankle mobility drill.", "Knee over toe, hold for thirty seconds each side."]),
    _ig("ig_fit_002", "runwithtomas", "Zone 2 running explained", "Why slow running makes you faster. #running #zone2", 75, 6.0, ["fitness", "running"],
        ["Zone two running means you can hold a conversation.", "Eighty percent of your weekly volume should be this easy.", "It builds the aerobic base that makes race pace feel easier."]),
    _yt("yt_fit_002", "runwithtomas", "My marathon training week (vlog)", "A full week of training, nutrition and recovery.", 1320, 9.0, ["fitness", "running", "vlog"]),
    _yt("yt_fit_003", "gymtok_hype", "INSANE 30 DAY TRANSFORMATION (you won't believe)", "Click to see the results!!!", 420, 1.0, ["fitness", "clickbait"]),
    # ---- programming
    _yt("yt_prog_001", "typed_thoughts", "Python 3.13 free-threading: what actually changes", "A practical look at the no-GIL build with benchmarks.", 1140, 2.5, ["programming", "python"],
        ["Python three point thirteen ships an experimental free threaded build.", "The GIL is gone in that build, so CPU bound threads can run in parallel.", "Single threaded code is a bit slower, around five to ten percent in my benchmarks.", "Most libraries still need updates before this is practical."]),
    _yt("yt_prog_002", "typed_thoughts", "FastAPI dependency injection patterns", "Clean request-scoped dependencies without globals.", 960, 12.0, ["programming", "python", "web"],
        ["Dependency injection in FastAPI is just functions that yield.", "Use Annotated to keep your signatures readable.", "Scope database sessions to the request and close them in a finally block."]),
    _ig("ig_prog_001", "devshorts", "Stop using bare except in Python", "Catch specific exceptions. Your future self will thank you.", 30, 0.3, ["programming", "python"],
        ["Stop writing bare except.", "Catch the specific exception, log it, and re-raise if you can't handle it."]),
    _yt("yt_prog_003", "rustacean_lab", "Rust ownership explained with pictures", "Borrowing, lifetimes, and why the compiler is your friend.", 1500, 30.0, ["programming", "rust"],
        ["Ownership is the core idea in Rust.", "Each value has exactly one owner at a time.", "Borrowing lets you reference a value without taking ownership."]),
    _yt("yt_prog_004", "ai_hype_daily", "This AI tool will REPLACE all programmers", "The end of coding is here. Subscribe!", 600, 0.4, ["programming", "ai", "clickbait"]),
    # ---- finance
    _yt("yt_fin_001", "plainmoney", "Index funds vs. ETFs: the boring truth", "Fees, taxes and when it genuinely matters.", 720, 5.0, ["finance", "investing"],
        ["Index funds and ETFs mostly track the same thing.", "The difference is fees, tax treatment and how you buy them.", "For most people the expense ratio matters more than the wrapper."]),
    _ig("ig_fin_001", "plainmoney", "Emergency fund: how many months?", "Three to six months of expenses, here's how to pick.", 50, 1.5, ["finance", "budgeting"],
        ["How big should your emergency fund be?", "Three months if your income is stable, six if it isn't."]),
    _ig("ig_fin_002", "cryptomoon_daily", "THIS COIN WILL 100X (not financial advice)", "Last chance before the pump!", 40, 0.2, ["finance", "crypto", "clickbait"]),
    # ---- travel
    _yt("yt_travel_001", "slowtravel_jo", "Three days in Lisbon on a budget", "Where to stay, what to eat, and the tram you should skip.", 1080, 15.0, ["travel", "europe", "budget"],
        ["Lisbon in three days without spending a fortune.", "Stay in Graça, eat at the tascas, skip the tram twenty-eight queue."]),
    _ig("ig_travel_001", "slowtravel_jo", "Hidden viewpoint in Porto", "Nobody goes here at sunrise. #porto #travel", 35, 7.0, ["travel", "europe"]),
    # ---- music / gaming / science
    _yt("yt_music_001", "studio_notes", "How to mix vocals: a 10-minute workflow", "EQ, compression, de-essing, reverb — in that order.", 630, 8.0, ["music", "production"],
        ["Mixing vocals in ten minutes.", "High pass first, then subtractive EQ.", "Compress gently, de-ess, then add reverb on a send."]),
    _yt("yt_game_001", "pixelpatch", "Indie game devlog #12: enemy AI", "Finite state machines for enemies.", 840, 2.2, ["gaming", "gamedev", "programming"],
        ["Devlog twelve: enemy AI.", "I'm using a simple finite state machine: idle, patrol, chase, attack."]),
    _yt("yt_sci_001", "labcoat_explains", "Why your sourdough rises: the science of fermentation", "Yeast, bacteria, and gluten networks.", 660, 11.0, ["science", "baking", "cooking"],
        ["Fermentation is yeast and bacteria eating sugars.", "Carbon dioxide gets trapped in the gluten network, that's the rise."]),
    _ig("ig_sci_001", "labcoat_explains", "Caffeine half-life explained", "Why a 4pm coffee ruins your sleep.", 55, 3.3, ["science", "sleep", "health"],
        ["Caffeine has a half life of about five hours.", "A four pm coffee means a quarter of it is still in you at midnight."]),
    # ---- non-English and duplicates (for dedup and language tests)
    _yt("yt_es_001", "cocina_rapida", "Pollo al ajillo en 20 minutos", "Receta rápida y alta en proteína.", 600, 2.0, ["cooking", "high-protein", "quick-meals"],
        ["Hoy preparamos pollo al ajillo en veinte minutos.", "Necesitas pechuga de pollo, ajo, aceite y perejil."], lang="es"),
    _yt("yt_cook_001_dup", "reposter_tv", "High-protein chicken stir fry in 15 minutes", "Re-upload of weeknight_kitchen's recipe.", 540, 0.9, ["cooking", "high-protein", "quick-meals"]),
    _ig("ig_fit_003", "coach_amira", "Deadlift setup checklist", "Bar over midfoot, shins touch, chest up.", 48, 1.1, ["fitness", "strength"],
        ["Deadlift setup: bar over midfoot.", "Shins to the bar, chest up, pull the slack out."]),
    _ig("ig_fit_004", "coach_amira", "Rest days matter", "Recovery is where you grow.", 30, 2.6, ["fitness", "recovery"]),
    _yt("yt_prod_001", "calm_desk", "A realistic morning routine for focus", "No 5am club. Just three habits that stick.", 480, 1.8, ["productivity", "habits"],
        ["A realistic morning routine.", "Phone stays in the other room until after breakfast.", "Write the one task that matters today."]),
    _yt("yt_prod_002", "calm_desk", "Why infinite scroll is designed to keep you scrolling", "Variable rewards and how to opt out.", 720, 6.5, ["productivity", "attention", "technology"],
        ["Infinite scroll works like a slot machine.", "Variable rewards keep you pulling the lever.", "Set a finite batch and a stopping cue."]),
]


def demo_candidates(platforms: list[str], *, query: str | None = None, limit_per_platform: int = 40) -> dict[str, list[CandidateItem]]:
    """Return fixture candidates per platform. ``demo`` platform maps to all fixtures."""
    out: dict[str, list[CandidateItem]] = {}
    for p in platforms:
        pool = DEMO_ITEMS if p == "demo" else [d for d in DEMO_ITEMS if d.platform == p]
        if query:
            q = {t for t in query.lower().replace(",", " ").split() if len(t) > 2}
            pool = [d for d in pool if any(t in (d.title + " " + d.caption + " " + " ".join(d.labels)).lower() for t in q)] or pool[:8]
        cands = []
        for i, d in enumerate(pool[:limit_per_platform]):
            c = d.to_candidate(feed_position=i)
            if p == "demo":
                c = c.model_copy(update={"platform": Platform.demo, "canonical_url": d.url})
            cands.append(c)
        out[p] = cands
    return out


def labels_by_key() -> dict[tuple[str, str], list[str]]:
    return {(d.platform, d.external_id): d.labels for d in DEMO_ITEMS}
