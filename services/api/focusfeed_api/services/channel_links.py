"""WhatsApp linking (one-use hashed codes bound to verified inbound identity), consent, STOP, pause."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.models import ChannelConversation, ChannelLink, ChannelLinkCode, DeliveryOutbox, User
from focusfeed_api.security.tokens import generate_enrollment_code, hash_token, normalize_enrollment_code

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
CODE_RE = re.compile(r"\b([A-Z2-9]{4})[- ]?([A-Z2-9]{4})[- ]?([A-Z2-9]{4})[- ]?([A-Z2-9]{4})\b", re.I)


def mask_sender(sender_id: str) -> str:
    return f"…{sender_id[-4:]}" if len(sender_id) >= 4 else "…"


def start_link(
    db: Session, user: User, *, settings: Settings | None = None
) -> tuple[ChannelLinkCode, str, str | None]:
    s = settings or get_settings()
    now = datetime.now(UTC)
    for old in db.scalars(
        select(ChannelLinkCode).where(ChannelLinkCode.user_id == user.id, ChannelLinkCode.used_at.is_(None))
    ).all():
        old.expires_at = min(old.expires_at, now)  # invalidate previous pending codes
    code = generate_enrollment_code()
    row = ChannelLinkCode(
        user_id=user.id,
        channel="whatsapp",
        code_hash=hash_token(normalize_enrollment_code(code)),
        expires_at=now + timedelta(minutes=CODE_TTL_MINUTES),
    )
    db.add(row)
    db.flush()
    deep_link = (
        f"https://wa.me/{s.wa_business_phone_e164}?text=LINK%20{code}" if s.wa_business_phone_e164 else None
    )
    return row, code, deep_link


def extract_code(text: str) -> str | None:
    cleaned = re.sub(
        r"(?i)\blink\b", " ", text or ""
    )  # the keyword itself is 4 letters; never treat it as a code group
    m = CODE_RE.search(cleaned)
    if not m:
        return None
    return "-".join(g.upper() for g in m.groups())


def consume_link_code(
    db: Session, *, sender_id: str, business_sender_id: str, text: str
) -> tuple[ChannelLink | None, str]:
    """Bind the verified inbound sender to the pending code. Returns (link, outcome)."""
    code = extract_code(text)
    if code is None:
        return None, "no_code"
    row = db.scalar(
        select(ChannelLinkCode)
        .where(ChannelLinkCode.code_hash == hash_token(normalize_enrollment_code(code)))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if row is None:
        return None, "invalid"
    if row.used_at is not None or row.expires_at <= now:
        return None, "expired"
    row.attempts += 1
    if row.attempts > MAX_ATTEMPTS:
        row.expires_at = now
        return None, "too_many_attempts"
    user = db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        return None, "invalid"
    # one WhatsApp identity may belong to one app user per business sender; relinking replaces the old binding
    existing_identity = db.scalar(
        select(ChannelLink).where(
            ChannelLink.channel == "whatsapp",
            ChannelLink.sender_id == sender_id,
            ChannelLink.business_sender_id == business_sender_id,
        )
    )
    if existing_identity is not None and existing_identity.user_id != user.id:
        existing_identity.status, existing_identity.unlinked_at, existing_identity.proactive_opt_in = (
            "unlinked",
            now,
            False,
        )
        existing_identity.sender_id = f"unlinked:{uuid.uuid4().hex[:12]}:{existing_identity.sender_id}"[:64]
    link = db.scalar(
        select(ChannelLink).where(ChannelLink.user_id == user.id, ChannelLink.channel == "whatsapp")
    )
    if link is None:
        link = ChannelLink(user_id=user.id, channel="whatsapp")
        db.add(link)
    link.sender_id, link.business_sender_id, link.display_hint = (
        sender_id,
        business_sender_id,
        mask_sender(sender_id),
    )
    link.status, link.linked_at, link.unlinked_at = "linked", now, None
    link.last_inbound_at = now
    row.used_at = now
    db.flush()
    conv = db.scalar(select(ChannelConversation).where(ChannelConversation.link_id == link.id))
    if conv is None:
        db.add(ChannelConversation(link_id=link.id, user_id=user.id))
    db.flush()
    return link, "linked"


def link_for_user(db: Session, user_id: uuid.UUID) -> ChannelLink | None:
    return db.scalar(
        select(ChannelLink).where(
            ChannelLink.user_id == user_id, ChannelLink.channel == "whatsapp", ChannelLink.status == "linked"
        )
    )


def link_for_sender(db: Session, sender_id: str, business_sender_id: str) -> ChannelLink | None:
    return db.scalar(
        select(ChannelLink).where(
            ChannelLink.channel == "whatsapp",
            ChannelLink.sender_id == sender_id,
            ChannelLink.business_sender_id == business_sender_id,
            ChannelLink.status == "linked",
        )
    )


def cancel_pending_proactive(db: Session, link: ChannelLink, reason: str) -> int:
    n = 0
    for row in db.scalars(
        select(DeliveryOutbox)
        .where(
            DeliveryOutbox.link_id == link.id,
            DeliveryOutbox.proactive.is_(True),
            DeliveryOutbox.state.in_(["prepared", "queued", "blocked_window"]),
        )
        .with_for_update()
    ).all():
        row.state, row.last_error = "cancelled", reason[:300]
        n += 1
    return n


def opt_out(db: Session, link: ChannelLink, *, source: str) -> int:
    """STOP semantics: identical from app and WhatsApp; suppresses pending proactive deliveries atomically."""
    now = datetime.now(UTC)
    link.proactive_opt_in, link.opt_out_at, link.opt_out_source = False, now, source
    link.paused_until = None
    return cancel_pending_proactive(db, link, f"opted out via {source}")


def opt_in(db: Session, link: ChannelLink, *, digests: bool, alerts: bool, disclosure_ack: bool) -> None:
    """App-only. A WhatsApp message never re-enables proactive messages."""
    now = datetime.now(UTC)
    link.proactive_opt_in, link.opt_in_at, link.opt_out_at, link.opt_out_source = True, now, None, ""
    link.digest_enabled, link.alerts_enabled = digests, alerts
    if disclosure_ack and link.external_model_disclosure_at is None:
        link.external_model_disclosure_at = now


def pause(db: Session, link: ChannelLink, until: datetime) -> int:
    link.paused_until = until
    n = 0
    for row in db.scalars(
        select(DeliveryOutbox).where(
            DeliveryOutbox.link_id == link.id,
            DeliveryOutbox.proactive.is_(True),
            DeliveryOutbox.state.in_(["prepared", "queued"]),
        )
    ).all():
        row.not_before = max(row.not_before or until, until)
        n += 1
    return n


def resume(db: Session, link: ChannelLink) -> bool:
    if not link.proactive_opt_in:
        return False
    link.paused_until = None
    return True


def unlink(db: Session, link: ChannelLink, *, source: str) -> None:
    now = datetime.now(UTC)
    cancel_pending_proactive(db, link, f"unlinked via {source}")
    link.status, link.unlinked_at, link.proactive_opt_in = "unlinked", now, False
    link.sender_id = f"unlinked:{uuid.uuid4().hex[:12]}:{link.sender_id}"[:64]
    conv = db.scalar(select(ChannelConversation).where(ChannelConversation.link_id == link.id))
    if conv is not None:
        db.delete(conv)


def can_send_proactive(link: ChannelLink, kind: str, now: datetime) -> tuple[bool, str]:
    if link.status != "linked":
        return False, "unlinked"
    if not link.proactive_opt_in:
        return False, "no_opt_in"
    if link.paused_until and link.paused_until > now:
        return False, "paused"
    if kind == "digest" and not link.digest_enabled:
        return False, "digests_disabled"
    if kind == "alert" and not link.alerts_enabled:
        return False, "alerts_disabled"
    return True, "ok"
