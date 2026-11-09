"""Inbound WhatsApp handling: deterministic commands first, bounded intent, shared domain services.

STOP/HELP/STATUS/linking/pause/save/explain never call a model. Content requests create a normal
search job (source="whatsapp"); the worker's completion hook composes the reply from the batch.
Inbound text is untrusted: it is matched against fixed patterns and, for content requests, passed
to the existing bounded intent stage as data.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.models import (
    ChannelConversation,
    ChannelLink,
    CollectionJob,
    ContentItem,
    Feedback,
    Recommendation,
    RecommendationBatch,
    SavedItem,
    Schedule,
    TopicWatch,
    User,
    WebhookInbox,
)
from focusfeed_api.services import channel_links as linksvc
from focusfeed_api.services import jobs as jobsvc
from focusfeed_api.services import outbox as outboxsvc
from focusfeed_api.services.model_routing import resolve_for_user
from focusfeed_api.services.preferences import get_or_create_profile
from focusfeed_api.services.schedules import compute_next_run

ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
    "5th": 5,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
}
SHOWN_TTL = timedelta(hours=24)
MAX_SHOWN = 5
MAX_TURNS = 10
TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)
CAP_RE = re.compile(r"at most\s+(\d{1,2}|one|two|three|four|five)\s+alerts?", re.I)
WATCH_RE = re.compile(
    r"(?:notify|alert)\s+me\s+when\s+(?:there\s+is\s+)?(?:new\s+)?(.+?)(?:\s+news)?(?:[,.]|\s+but\b|$)", re.I
)
URL_RE = re.compile(r"https?://\S+", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _ref(text: str) -> int | None:
    t = _norm(text)
    m = re.search(r"(?:number|no\.?|#|item|article)\s*(\d{1,2})\b", t) or re.search(r"\b(\d{1,2})\b", t)
    if m:
        return int(m.group(1))
    for w, n in ORDINALS.items():
        if re.search(rf"\b{w}\b", t):
            return n
    return None


def _parse_time(text: str) -> str | None:
    m = TIME_RE.search(text)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and hh < 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def user_timezone(db: Session, user_id: uuid.UUID) -> str:
    sched = db.scalar(select(Schedule).where(Schedule.user_id == user_id).order_by(Schedule.created_at))
    return sched.timezone if sched else "UTC"


# ----------------------------------------------------------------------------- replies


def _reply(db: Session, link: ChannelLink, body: str, key: str) -> None:
    outboxsvc.enqueue(
        db, user_id=link.user_id, link=link, kind="reply", body=body, logical_key=key, proactive=False
    )


def _conv(db: Session, link: ChannelLink) -> ChannelConversation:
    conv = db.scalar(select(ChannelConversation).where(ChannelConversation.link_id == link.id))
    if conv is None:
        conv = ChannelConversation(link_id=link.id, user_id=link.user_id)
        db.add(conv)
        db.flush()
    return conv


def remember_turn(conv: ChannelConversation, role: str, text: str) -> None:
    turns = list(conv.recent_turns or [])[-(MAX_TURNS - 1) :]
    turns.append({"role": role, "text": text[:300], "at": datetime.now(UTC).isoformat()})
    conv.recent_turns = turns


def show_items(conv: ChannelConversation, items: list[dict[str, Any]]) -> None:
    conv.shown_items = [
        {"n": i + 1, "item_id": str(it["item_id"]), "title": it["title"][:120], "url": it["url"]}
        for i, it in enumerate(items[:MAX_SHOWN])
    ]
    conv.shown_at = datetime.now(UTC)


def resolve_shown(conv: ChannelConversation, n: int | None) -> tuple[dict[str, Any] | None, str]:
    if not conv.shown_items or not conv.shown_at or datetime.now(UTC) - conv.shown_at > SHOWN_TTL:
        return None, "I haven't shown you a list recently. Send 'digest' or ask for something first."
    if n is None:
        return None, f"Which one? Reply with a number 1-{len(conv.shown_items)}."
    for it in conv.shown_items:
        if it["n"] == n:
            return it, ""
    return (
        None,
        f"I only showed {len(conv.shown_items)} items. Reply with a number 1-{len(conv.shown_items)}.",
    )


def format_items(
    items: list[dict[str, Any]], *, header: str, settings: Settings, batch_id: uuid.UUID | None = None
) -> str:
    lines = [header]
    for i, it in enumerate(items[:MAX_SHOWN], start=1):
        meta = " · ".join(
            x for x in [it.get("creator") or "", it.get("duration") or "", it.get("label") or ""] if x
        )
        lines.append(f"{i}. {it['title'][:90]}" + (f" ({meta})" if meta else "") + f"\n{it['url']}")
    if batch_id:
        lines.append(f"Open in app: {settings.ff_public_app_url}/history/{batch_id} (sign-in required)")
    lines.append(
        "Reply: 'explain 2', 'save 2', 'not interested 2', 'digest', 'help'. STOP to end notifications."
    )
    return "\n".join(lines)[:3900]


def batch_items(db: Session, batch: RecommendationBatch) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Recommendation, ContentItem)
        .join(ContentItem, ContentItem.id == Recommendation.item_id)
        .where(Recommendation.batch_id == batch.id, Recommendation.hidden_at.is_(None))
        .order_by(Recommendation.rank)
        .limit(MAX_SHOWN)
    ).all()
    out = []
    for r, i in rows:
        mins = round(r.estimated_seconds / 60)
        out.append(
            {
                "item_id": i.id,
                "title": i.title or (i.caption or "")[:80] or i.canonical_url,
                "url": i.canonical_url,
                "creator": i.creator_name or i.creator_handle or "",
                "duration": f"{mins} min" if r.duration_known else f"~{mins} min",
                "label": "synthetic demo" if i.is_synthetic else i.platform,
                "summary": r.summary,
                "explanation": r.explanation,
            }
        )
    return out


# ----------------------------------------------------------------------------- command handlers


def handle_text(
    db: Session,
    link: ChannelLink | None,
    *,
    sender_id: str,
    business_sender_id: str,
    text: str,
    message_id: str,
    settings: Settings | None = None,
) -> str:
    """Return a short outcome label (for tests/logs). Replies are enqueued in the outbox."""
    s = settings or get_settings()
    now = datetime.now(UTC)
    t = _norm(text)
    key = f"reply:{message_id}"
    # 1. unknown sender: linking or minimal guidance (never reveals anything)
    if link is None:
        new_link, outcome = linksvc.consume_link_code(
            db, sender_id=sender_id, business_sender_id=business_sender_id, text=text
        )
        if new_link is not None:
            conv = _conv(db, new_link)
            remember_turn(conv, "user", text)
            _reply(
                db,
                new_link,
                "✅ WhatsApp linked to your FocusFeed account. Notifications stay OFF until you enable them in the app (Settings → WhatsApp). Reply 'help' for commands.",
                key,
            )
            return "linked"
        if outcome in ("expired", "too_many_attempts", "invalid"):
            hint = {
                "expired": "That code expired or was already used.",
                "too_many_attempts": "Too many attempts; generate a new code.",
                "invalid": "That code is not valid.",
            }[outcome]
            body = f"{hint} Open FocusFeed → Settings → WhatsApp and tap 'Connect WhatsApp' for a fresh code."
        else:
            body = "Hi! This is FocusFeed. To link this number, open the FocusFeed app → Settings → WhatsApp → 'Connect WhatsApp' and send the code shown there."
        bucket = now.strftime("%Y%m%d%H")
        from focusfeed_api.models import DeliveryOutbox

        lk = f"onboard:{sender_id}:{bucket}"  # at most one guidance reply per sender per hour
        if db.scalar(select(DeliveryOutbox.id).where(DeliveryOutbox.logical_key == lk)) is None:
            db.add(
                DeliveryOutbox(
                    user_id=None,
                    link_id=None,
                    recipient_id=sender_id,
                    channel="whatsapp",
                    logical_key=lk,
                    kind="system",
                    proactive=False,
                    body=body,
                    state="queued",
                    not_before=now,
                    next_attempt_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
        return f"unknown_sender:{outcome}"
    # 2. linked sender: service-window anchor + context
    link.last_inbound_at = now
    conv = _conv(db, link)
    remember_turn(conv, "user", text)
    user = db.get(User, link.user_id)
    assert user is not None
    # a linked sender re-sending a code: never start a search with it; report the outcome
    if linksvc.extract_code(text) is not None:
        _new, outcome = linksvc.consume_link_code(
            db, sender_id=sender_id, business_sender_id=business_sender_id, text=text
        )
        msg = {
            "linked": "This number is now linked to that account.",
            "expired": "That code expired or was already used. Your WhatsApp is still linked.",
            "too_many_attempts": "Too many attempts; generate a new code in the app.",
            "invalid": "That code is not valid. Your WhatsApp is still linked.",
        }.get(outcome, "Your WhatsApp is linked.")
        _reply(db, _new or link, msg, key)
        return f"relink:{outcome}"
    # deterministic commands (no model)
    if t in ("stop", "unsubscribe", "cancel", "end", "quit"):
        linksvc.opt_out(db, link, source="whatsapp")
        _reply(
            db,
            link,
            "You won't receive WhatsApp notifications from FocusFeed anymore. Your batches stay in the app. You can re-enable notifications there.",
            key,
        )
        return "stop"
    if t in ("start", "resume", "unpause"):
        if linksvc.resume(db, link):
            _reply(db, link, "Notifications resumed.", key)
            return "resume"
        _reply(
            db,
            link,
            "Notifications are off. For your protection they can only be turned on inside the FocusFeed app (Settings → WhatsApp).",
            key,
        )
        return "resume_refused"
    if t.startswith("pause"):
        tz = ZoneInfo(user_timezone(db, user.id))
        until = (
            (now.astimezone(tz) + timedelta(days=1))
            .replace(hour=8, minute=0, second=0, microsecond=0)
            .astimezone(UTC)
        )
        linksvc.pause(db, link, until)
        _reply(
            db,
            link,
            f"Paused until {until.astimezone(tz).strftime('%a %H:%M')} ({tz.key}). Reply 'resume' to resume earlier.",
            key,
        )
        return "pause"
    if t in ("help", "?", "commands"):
        _reply(
            db,
            link,
            "FocusFeed commands: 'digest' (latest batch) · ask anything e.g. 'find three quick vegetarian dinner recipes' · 'explain 2' · 'save 2' · 'not interested 2' · 'relevant 2' · 'status' · 'model' · 'digest at 7pm' · 'notify me when there is new AI news, at most 3 alerts a day' · 'pause' · 'resume' · STOP.",
            key,
        )
        return "help"
    if t in ("status", "connection", "connections"):
        job = db.scalar(
            select(CollectionJob)
            .where(CollectionJob.user_id == user.id)
            .order_by(CollectionJob.created_at.desc())
        )
        from focusfeed_api.models import HostedProfile

        profiles = db.scalars(select(HostedProfile).where(HostedProfile.user_id == user.id)).all()
        src = (
            ", ".join(f"{p.platform}: {p.status.replace('_', ' ')}" for p in profiles)
            or "no sources connected"
        )
        last = (
            f"Last run: {job.state.replace('_', ' ')} ({job.created_at.strftime('%d %b %H:%M')} UTC)"
            if job
            else "No runs yet."
        )
        notif = (
            "on"
            if link.proactive_opt_in and not (link.paused_until and link.paused_until > now)
            else ("paused" if link.paused_until and link.paused_until > now else "off")
        )
        _reply(db, link, f"Sources — {src}.\n{last}\nWhatsApp notifications: {notif}.", key)
        return "status"
    if t in ("model", "ai", "which ai", "which model"):
        prof = get_or_create_profile(db, user)
        try:
            routed = resolve_for_user(db, user, prof, settings=s)
            label = routed.label if routed else "no provider configured"
        except Exception as exc:  # noqa: BLE001
            label = f"unavailable ({getattr(exc, 'code', 'error')})"
        _reply(db, link, f"Your AI setting: {label}. Change it in the app → Settings → AI.", key)
        return "model"
    if t in ("digest", "latest", "today", "my digest", "batch"):
        batch = db.scalar(
            select(RecommendationBatch)
            .where(RecommendationBatch.user_id == user.id, RecommendationBatch.mode == "daily")
            .order_by(RecommendationBatch.generated_at.desc())
        )
        if batch is None:
            _reply(
                db,
                link,
                "No batch is prepared yet. Set a schedule in the app or ask me for something specific.",
                key,
            )
            return "digest_none"
        items = batch_items(db, batch)
        show_items(conv, items)
        stale = (now - batch.generated_at) > timedelta(hours=36)
        header = f"Your {'latest' if not stale else 'last (older)'} batch from {batch.generated_at.strftime('%d %b %H:%M')} UTC ({batch.completion_status}):"
        _reply(db, link, format_items(items, header=header, settings=s, batch_id=batch.id), key)
        return "digest"
    m_save = re.match(
        r"^(save|unsave|like|relevant|not interested|not relevant|dislike|explain|summarize|summarise|what is|tell me about)\b(.*)$",
        t,
    )
    if m_save:
        verb, rest = m_save.group(1), m_save.group(2)
        it, problem = resolve_shown(conv, _ref(rest))
        if it is None:
            _reply(db, link, problem, key)
            return "clarify"
        item_id = uuid.UUID(it["item_id"])
        if verb == "save":
            saved = db.scalar(
                select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.item_id == item_id)
            )
            if saved is None:
                db.add(SavedItem(user_id=user.id, item_id=item_id))
            else:
                saved.removed_at = None
            _reply(db, link, f"Saved: {it['title']}", key)
            return "save"
        if verb == "unsave":
            saved = db.scalar(
                select(SavedItem).where(SavedItem.user_id == user.id, SavedItem.item_id == item_id)
            )
            if saved is not None:
                saved.removed_at = now
            _reply(db, link, f"Removed from saved: {it['title']}", key)
            return "unsave"
        if verb in ("like", "relevant", "not interested", "not relevant", "dislike"):
            action = {
                "like": "relevant",
                "relevant": "relevant",
                "not interested": "not_interested",
                "not relevant": "not_relevant",
                "dislike": "not_relevant",
            }[verb]
            if (
                db.scalar(
                    select(Feedback.id).where(
                        Feedback.user_id == user.id,
                        Feedback.item_id == item_id,
                        Feedback.action == action,
                        Feedback.revoked_at.is_(None),
                    )
                )
                is None
            ):
                db.add(Feedback(user_id=user.id, item_id=item_id, action=action, scope="item"))
            _reply(db, link, f"Noted ({action.replace('_', ' ')}): {it['title']}", key)
            return "feedback"
        rec = db.scalar(
            select(Recommendation)
            .where(Recommendation.user_id == user.id, Recommendation.item_id == item_id)
            .order_by(Recommendation.created_at.desc())
        )
        if rec is None:
            _reply(db, link, f"{it['title']}\n{it['url']}", key)
        else:
            _reply(db, link, f"{it['title']}\n{rec.summary}\nWhy: {rec.explanation}\n{it['url']}"[:3900], key)
        return "explain"
    # settings: digest time / delivery / watches (deterministic parse)
    if re.search(r"\b(digest|recommendations?|batch)\b.*\b(at|by)\b", t) and _parse_time(t):
        hhmm = _parse_time(t) or "19:00"
        tzname = user_timezone(db, user.id)
        sched = db.scalar(select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.created_at))
        prof = get_or_create_profile(db, user)
        if sched is None:
            sched = Schedule(user_id=user.id, timezone=tzname, platforms=list(prof.platforms or []))
            db.add(sched)
        hh, mm = (int(x) for x in hhmm.split(":"))
        total = (hh * 60 + mm - (sched.lead_minutes or 60)) % (24 * 60)
        sched.ready_by_time, sched.local_time = hhmm, f"{total // 60:02d}:{total % 60:02d}"
        sched.enabled = True
        sched.next_run_at = compute_next_run(
            sched.local_time, list(sched.days_of_week or [0, 1, 2, 3, 4, 5, 6]), sched.timezone, now
        )
        if "whatsapp" in t:
            chans = list(sched.deliver_channels or ["app"])
            if "whatsapp" not in chans:
                chans.append("whatsapp")
            sched.deliver_channels = chans
            extra = (
                " It will be sent here only while WhatsApp notifications are enabled in the app."
                if not link.proactive_opt_in
                else " It will also be sent here."
            )
        else:
            extra = ""
        _reply(db, link, f"OK — your batch will be ready by {hhmm} ({tzname}) every day.{extra}", key)
        return "schedule"
    if "whatsapp" in t and re.search(r"\b(send|deliver)\b", t) and "digest" in t:
        sched = db.scalar(select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.created_at))
        if sched is not None:
            chans = list(sched.deliver_channels or ["app"])
            if "whatsapp" not in chans:
                chans.append("whatsapp")
            sched.deliver_channels = chans
        if link.proactive_opt_in:
            _reply(
                db,
                link,
                "Done — your digest will be delivered here when it is ready."
                if sched
                else "Set a digest time first, e.g. 'digest at 7pm'.",
                key,
            )
        else:
            _reply(
                db,
                link,
                "To receive digests here, enable WhatsApp notifications in the app (Settings → WhatsApp). We only switch proactive messages on from the app.",
                key,
            )
        return "deliver"
    m_watch = WATCH_RE.search(text or "")
    if m_watch:
        topic = _norm(m_watch.group(1))[:60]
        cap_m = CAP_RE.search(t)
        cap = ORDINALS.get(cap_m.group(1), None) if cap_m else None
        if cap_m and cap is None:
            cap = int(cap_m.group(1))
        urls = [u for u in URL_RE.findall(text or "")][:3]
        from focusfeed_api.services.watches import validate_sources

        try:
            sources = validate_sources([{"type": "rss", "url": u} for u in urls])
        except Exception:  # noqa: BLE001
            sources = []
        w = TopicWatch(
            user_id=user.id,
            name=topic.title(),
            topics=[topic],
            mode="alert",
            max_alerts_per_day=max(1, min(cap or 3, 10)),
            timezone=user_timezone(db, user.id),
            sources=sources,
            next_poll_at=now,
            poll_minutes=s.ff_watch_poll_minutes_default,
        )
        db.add(w)
        src_note = (
            f"Watching {len(sources)} feed(s)."
            if sources
            else "Add RSS feeds to this watch in the app (Settings → Watches) — I only use sources you choose."
        )
        _reply(
            db,
            link,
            f"Watch created: '{topic}', at most {w.max_alerts_per_day} alert(s) a day. {src_note} Alerts come here only while notifications are enabled.",
            key,
        )
        return "watch"
    # content request -> bounded search job; the completion hook replies
    active = db.scalar(
        select(CollectionJob).where(CollectionJob.user_id == user.id, CollectionJob.state.in_(jobsvc.ACTIVE))
    )
    if active is not None and active.channel_link_id == link.id:
        _reply(
            db, link, "I'm still working on your previous request — I'll reply as soon as it's ready.", key
        )
        return "busy"
    try:
        job, created = jobsvc.create_job(
            db,
            user,
            mode="search",
            query=text[:500],
            platforms=None,
            budget=None,
            idempotency_key=f"wa:{message_id}"[:128],
            source="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001 - validation errors -> friendly reply
        _reply(db, link, f"I couldn't start that: {getattr(exc, 'message', 'try again later')}", key)
        return "job_error"
    job.channel_link_id = link.id
    job.reply_context = {"message_id": message_id}
    conv.pending_job_id = job.id
    _reply(db, link, f"Looking for: “{text[:120]}”. I'll reply with up to {MAX_SHOWN} results shortly.", key)
    return "search_started"


def process_inbox(db: Session, *, settings: Settings | None = None, limit: int = 50) -> dict[str, int]:
    """Process pending verified inbox rows: messages -> handlers, statuses -> outbox."""
    s = settings or get_settings()
    stats = {"messages": 0, "statuses": 0, "ignored": 0}
    rows = db.scalars(
        select(WebhookInbox)
        .where(WebhookInbox.state == "pending")
        .order_by(WebhookInbox.received_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        try:
            if row.kind == "status":
                outboxsvc.apply_status(
                    db,
                    row.payload.get("message_id", ""),
                    row.payload.get("status", ""),
                    error=row.payload.get("error", ""),
                )
                stats["statuses"] += 1
            elif row.kind == "message" and row.payload.get("type") == "text":
                link = linksvc.link_for_sender(db, row.sender_id, row.business_sender_id)
                note = handle_text(
                    db,
                    link,
                    sender_id=row.sender_id,
                    business_sender_id=row.business_sender_id,
                    text=row.payload.get("text", ""),
                    message_id=row.payload.get("message_id", row.event_key),
                    settings=s,
                )
                row.note = note[:300]
                stats["messages"] += 1
            else:
                link = linksvc.link_for_sender(db, row.sender_id, row.business_sender_id)
                if link is not None:
                    link.last_inbound_at = datetime.now(UTC)
                    _reply(
                        db,
                        link,
                        "I can only read text messages for now. Reply 'help' for commands.",
                        f"reply:{row.event_key}",
                    )
                stats["ignored"] += 1
            row.state, row.processed_at = "processed", datetime.now(UTC)
        except Exception as exc:  # noqa: BLE001
            row.state, row.note = "failed", f"{type(exc).__name__}: {str(exc)[:200]}"
            row.processed_at = datetime.now(UTC)
        db.flush()
    return stats


def reply_for_job(
    db: Session, job: CollectionJob, batch: RecommendationBatch | None, *, settings: Settings | None = None
) -> None:
    """Completion hook for WhatsApp-originated jobs."""
    s = settings or get_settings()
    if job.channel_link_id is None:
        return
    link = db.get(ChannelLink, job.channel_link_id)
    if link is None or link.status != "linked":
        return
    conv = _conv(db, link)
    key = f"result:{job.id}"
    if batch is None:
        reason = job.stop_reason or job.state.replace("_", " ")
        _reply(
            db,
            link,
            f"I couldn't complete that request ({reason}). "
            + (
                "Reconnect your source in the app."
                if job.state == "needs_user_action"
                else "Try again later."
            ),
            key,
        )
        return
    items = batch_items(db, batch)
    if not items:
        _reply(
            db,
            link,
            "I didn't find anything suitable within your settings. Try different words or widen your sources in the app.",
            key,
        )
        return
    show_items(conv, items)
    _reply(
        db,
        link,
        format_items(items, header=f"Results for “{(job.query or '')[:80]}”:", settings=s, batch_id=batch.id),
        key,
    )
    conv.pending_job_id = None


def digest_for_schedule(
    db: Session, job: CollectionJob, batch: RecommendationBatch, *, settings: Settings | None = None
) -> None:
    """Completion hook for scheduled jobs: optional proactive WhatsApp digest honouring 'send at'."""
    s = settings or get_settings()
    if job.schedule_id is None:
        return
    sched = db.get(Schedule, job.schedule_id)
    if sched is None:
        return
    sched.last_batch_id = batch.id
    if "whatsapp" not in list(sched.deliver_channels or []):
        return
    link = linksvc.link_for_user(db, job.user_id)
    now = datetime.now(UTC)
    not_before = now
    if sched.deliver_time:
        tz = ZoneInfo(sched.timezone)
        local = now.astimezone(tz)
        hh, mm = (int(x) for x in sched.deliver_time.split(":"))
        cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand > local:
            not_before = cand.astimezone(UTC)
    items = batch_items(db, batch)
    from focusfeed_api.services.watches import pending_digest_discoveries

    extra = pending_digest_discoveries(db, job.user_id, limit=3)
    body = format_items(
        items,
        header=f"Your FocusFeed batch ({batch.completion_status}, {len(items)} items):",
        settings=s,
        batch_id=batch.id,
    )
    if extra:
        body += "\n\nFrom your watches:\n" + "\n".join(
            f"• {(i.title or '')[:80]} — {i.canonical_url}" for d, i, w in extra
        )
        for d, _i, _w in extra:
            d.disposition = "digested_sent"
    if link is not None:
        conv = _conv(db, link)
        show_items(conv, items)
    outboxsvc.enqueue(
        db,
        user_id=job.user_id,
        link=link,
        kind="digest",
        body=body,
        logical_key=f"digest:{job.id}",
        proactive=True,
        not_before=not_before,
        related_batch_id=batch.id,
        settings=s,
    )


def enqueue_watch_alerts(db: Session, *, settings: Settings | None = None) -> int:
    from focusfeed_api.services.watches import alerted_pending_outbox

    s = settings or get_settings()
    n = 0
    for d, item, w in alerted_pending_outbox(db):
        link = linksvc.link_for_user(db, w.user_id)
        body = (
            f"New on your '{w.name}' watch: {item.title or item.canonical_url}\n{item.canonical_url}\n(discovered {d.discovered_at.strftime('%H:%M')} UTC"
            + (
                f", published {d.source_published_at.strftime('%d %b %H:%M')} UTC"
                if d.source_published_at
                else ""
            )
            + f"; checked every {w.poll_minutes} min)"
        )
        outboxsvc.enqueue(
            db,
            user_id=w.user_id,
            link=link,
            kind="alert",
            body=body,
            logical_key=f"alert:{d.id}",
            proactive=True,
            settings=s,
        )
        n += 1
    return n
