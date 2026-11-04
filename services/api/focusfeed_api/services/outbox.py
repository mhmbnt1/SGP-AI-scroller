"""Transactional delivery outbox: consent + window + template checks at dispatch time, retries, statuses."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.models import ChannelLink, DeliveryOutbox, MessageTemplate
from focusfeed_api.services import usage as usagesvc
from focusfeed_api.services.channel_links import can_send_proactive

MAX_ATTEMPTS = 5
STATUS_RANK = {"accepted": 1, "sent": 2, "delivered": 3, "read": 4, "failed": 5}
PURPOSE_BY_KIND = {
    "digest": "digest",
    "alert": "alert",
    "reply": "reply_followup",
    "system": "reply_followup",
}


def enqueue(
    db: Session,
    *,
    user_id: uuid.UUID,
    link: ChannelLink | None,
    kind: str,
    body: str,
    logical_key: str,
    proactive: bool,
    not_before: datetime | None = None,
    related_batch_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> DeliveryOutbox:
    s = settings or get_settings()
    existing = db.scalar(
        select(DeliveryOutbox).where(
            DeliveryOutbox.channel == "whatsapp", DeliveryOutbox.logical_key == logical_key
        )
    )
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    start = not_before or now
    row = DeliveryOutbox(
        user_id=user_id,
        link_id=link.id if link else None,
        channel="whatsapp",
        logical_key=logical_key[:160],
        kind=kind,
        proactive=proactive,
        body=body[:4000],
        state="queued" if link is not None else "blocked_consent",
        not_before=start,
        next_attempt_at=start,
        expires_at=start + timedelta(hours=s.wa_max_delivery_age_hours),
        related_batch_id=related_batch_id,
    )
    if link is None:
        row.last_error = "no linked WhatsApp account"
    db.add(row)
    db.flush()
    return row


def within_service_window(link: ChannelLink, now: datetime, settings: Settings) -> bool:
    return link.last_inbound_at is not None and (now - link.last_inbound_at) < timedelta(
        hours=settings.wa_service_window_hours
    )


def approved_template(db: Session, purpose: str) -> MessageTemplate | None:
    return db.scalar(
        select(MessageTemplate)
        .where(
            MessageTemplate.channel == "whatsapp",
            MessageTemplate.purpose == purpose,
            MessageTemplate.status == "approved",
        )
        .order_by(MessageTemplate.created_at.desc())
    )


def dispatch_due(
    db: Session,
    transport: Any,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    limit: int = 50,
) -> dict[str, int]:
    """Send due outbox rows. Each row is re-checked for consent, window and template rules right before sending."""
    s = settings or get_settings()
    now = now or datetime.now(UTC)
    stats = {"sent": 0, "blocked": 0, "failed": 0, "expired": 0, "unknown": 0, "skipped": 0}
    rows = db.scalars(
        select(DeliveryOutbox)
        .where(
            DeliveryOutbox.channel == "whatsapp",
            DeliveryOutbox.state.in_(["queued", "blocked_window"]),
            DeliveryOutbox.next_attempt_at <= now,
        )
        .order_by(DeliveryOutbox.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        if row.expires_at and row.expires_at < now:
            row.state, row.last_error = "expired", "max delivery age exceeded"
            stats["expired"] += 1
            continue
        link = db.get(ChannelLink, row.link_id) if row.link_id else None
        if link is None and row.kind == "system" and row.recipient_id and not row.proactive:
            # minimal guidance to an unlinked sender who just wrote to us (inside their own service window)
            row.attempts += 1
            res = transport.send_text(row.recipient_id, row.body)
            if res.accepted:
                row.state, row.provider_message_id, row.sent_at = "accepted", res.provider_message_id, now
                stats["sent"] += 1
            else:
                row.state, row.last_error = ("unknown" if res.ambiguous else "failed"), res.error[:300]
                stats["failed"] += 0 if res.ambiguous else 1
            continue
        if link is None or link.status != "linked":
            row.state, row.last_error = "blocked_consent", "no linked WhatsApp account"
            stats["blocked"] += 1
            continue
        if row.proactive:
            ok, why = can_send_proactive(link, row.kind, now)
            if not ok:
                if why == "paused" and link.paused_until:
                    row.next_attempt_at = link.paused_until
                    stats["skipped"] += 1
                else:
                    row.state, row.last_error = "blocked_consent", why
                    stats["blocked"] += 1
                continue
        use_template = None
        if not within_service_window(link, now, s):
            tpl = approved_template(db, PURPOSE_BY_KIND.get(row.kind, "reply_followup"))
            if tpl is None:
                row.state, row.last_error = (
                    "blocked_window",
                    "outside the 24h service window and no approved template; content stays in the app",
                )
                row.next_attempt_at = now + timedelta(minutes=30)
                stats["blocked"] += 1
                continue
            use_template = tpl
        assert row.user_id is not None  # system guidance rows were dispatched above
        try:
            lid = usagesvc.reserve(
                user_id=row.user_id,
                kind="messaging",
                provider="whatsapp",
                model=use_template.name if use_template else "text",
                scope="operator",
                purpose="whatsapp_send",
                messages=1,
                calls=0,
            )
        except usagesvc.QuotaExceeded as exc:
            row.state, row.last_error = "blocked_consent", f"message allowance: {exc.message[:200]}"
            stats["blocked"] += 1
            continue
        row.attempts += 1
        row.state = "sending"
        db.flush()
        if use_template is not None:
            params = [row.body[:900]] if use_template.parameter_count >= 1 else []
            res = transport.send_template(link.sender_id, use_template.name, use_template.language, params)
            row.template_name, row.template_params = use_template.name, params
        else:
            res = transport.send_text(link.sender_id, row.body)
        if res.accepted:
            row.state, row.provider_message_id, row.sent_at, row.last_error = (
                "accepted",
                res.provider_message_id,
                now,
                "",
            )
            usagesvc.settle(lid, input_tokens=None, output_tokens=None, calls=0)
            stats["sent"] += 1
        elif res.ambiguous:
            row.state, row.last_error = (
                "unknown",
                "send timed out after transmission; awaiting reconciliation (no blind resend)",
            )
            usagesvc.settle(lid, input_tokens=None, output_tokens=None, calls=0)
            stats["unknown"] += 1
        else:
            usagesvc.release(lid, note=f"failed:{res.error[:60]}")
            if res.retryable and row.attempts < MAX_ATTEMPTS:
                row.state, row.last_error = "queued", res.error[:300]
                row.next_attempt_at = now + timedelta(seconds=min(3600, 30 * (2 ** (row.attempts - 1))))
            else:
                row.state, row.last_error = "failed", res.error[:300]
                stats["failed"] += 1
    db.flush()
    return stats


def apply_status(
    db: Session, provider_message_id: str, status: str, *, error: str = "", now: datetime | None = None
) -> bool:
    """Idempotent, order-safe status update by provider message id."""
    row = db.scalar(select(DeliveryOutbox).where(DeliveryOutbox.provider_message_id == provider_message_id))
    if row is None:
        return False
    now = now or datetime.now(UTC)
    new_rank = STATUS_RANK.get(status, 0)
    cur_rank = (
        STATUS_RANK.get(row.state, 0)
        if row.state in STATUS_RANK
        else (1 if row.state in ("accepted", "unknown") else 0)
    )
    if status == "failed":
        row.state, row.last_error, row.status_at = "failed", error[:300] or "provider reported failure", now
        return True
    if new_rank <= cur_rank and row.state != "unknown":
        return True  # duplicate or out-of-order event
    row.state = {"sent": "accepted", "delivered": "delivered", "read": "read", "accepted": "accepted"}.get(
        status, row.state
    )
    row.status_at = now
    return True


def history(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[DeliveryOutbox]:
    return list(
        db.scalars(
            select(DeliveryOutbox)
            .where(DeliveryOutbox.user_id == user_id)
            .order_by(DeliveryOutbox.created_at.desc())
            .limit(limit)
        ).all()
    )
