"""WhatsApp linking/consent/preferences (consumer), notification history, and the restricted webhook."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from focusfeed_api.auth.deps import DB, AppSettings, CurrentUser
from focusfeed_api.channels import whatsapp as wa
from focusfeed_api.errors import AppError, NotFound, ServiceUnavailable, ValidationFailed
from focusfeed_api.models import MessageTemplate, WebhookInbox
from focusfeed_api.schemas import (
    NotificationOut,
    OkOut,
    WhatsAppLinkStartOut,
    WhatsAppPreferencesIn,
    WhatsAppStatusOut,
)
from focusfeed_api.services import audit
from focusfeed_api.services import channel_links as linksvc
from focusfeed_api.services import outbox as outboxsvc

router = APIRouter(tags=["channels"])


def _status(db, user, settings) -> WhatsAppStatusOut:
    link = linksvc.link_for_user(db, user.id)
    tpl_digest = outboxsvc.approved_template(db, "digest") is not None
    tpl_alert = outboxsvc.approved_template(db, "alert") is not None
    now = datetime.now(UTC)
    return WhatsAppStatusOut(
        transport_mode=settings.ff_whatsapp_mode,
        linked=link is not None,
        display_hint=link.display_hint if link else None,
        linked_at=link.linked_at if link else None,
        proactive_opt_in=bool(link and link.proactive_opt_in),
        digest_enabled=bool(link and link.digest_enabled),
        alerts_enabled=bool(link and link.alerts_enabled),
        paused_until=link.paused_until if link else None,
        opt_out_at=link.opt_out_at if link else None,
        in_service_window=bool(link and outboxsvc.within_service_window(link, now, settings)),
        templates_approved={"digest": tpl_digest, "alert": tpl_alert},
        eligibility_note=(
            "Live sending is disabled on this service."
            if settings.ff_whatsapp_mode == "disabled"
            else "Mock transport: messages are recorded, not sent."
            if settings.ff_whatsapp_mode == "mock"
            else "Live transport. Proactive digests/alerts outside the 24-hour service window require an approved template; otherwise content stays in the app."
        ),
        external_disclosure_acknowledged=bool(link and link.external_model_disclosure_at),
    )


@router.get("/channels/whatsapp", response_model=WhatsAppStatusOut)
def whatsapp_status(user: CurrentUser, db: DB, settings: AppSettings) -> WhatsAppStatusOut:
    return _status(db, user, settings)


@router.post(
    "/channels/whatsapp/link", response_model=WhatsAppLinkStartOut, status_code=status.HTTP_201_CREATED
)
def whatsapp_link(user: CurrentUser, db: DB, settings: AppSettings, request: Request) -> WhatsAppLinkStartOut:
    if settings.ff_whatsapp_mode == "disabled":
        raise ServiceUnavailable(
            "WhatsApp is not enabled on this service. The operator must configure the business sender first."
        )
    row, code, deep_link = linksvc.start_link(db, user, settings=settings)
    audit.record(db, "whatsapp.link_started", user_id=user.id, request=request)
    db.commit()
    return WhatsAppLinkStartOut(
        code=code,
        expires_at=row.expires_at,
        deep_link=deep_link,
        message_text=f"LINK {code}",
        instructions="Send this code from your own WhatsApp to the FocusFeed number. The code works once and expires in 10 minutes. We never ask for your phone number in the app; the link is confirmed from the message you send.",
    )


@router.put("/channels/whatsapp/preferences", response_model=WhatsAppStatusOut)
def whatsapp_preferences(
    body: WhatsAppPreferencesIn, user: CurrentUser, db: DB, settings: AppSettings, request: Request
) -> WhatsAppStatusOut:
    link = linksvc.link_for_user(db, user.id)
    if link is None:
        raise NotFound("Link WhatsApp first.")
    if body.proactive_opt_in:
        if not body.acknowledge_external_processing and link.external_model_disclosure_at is None:
            raise ValidationFailed(
                "Please acknowledge how your messages are processed before enabling notifications.",
                code="disclosure_required",
            )
        linksvc.opt_in(
            db,
            link,
            digests=body.digest_enabled,
            alerts=body.alerts_enabled,
            disclosure_ack=body.acknowledge_external_processing,
        )
        if body.paused_until is not None:
            linksvc.pause(db, link, body.paused_until)
        else:
            link.paused_until = None
    else:
        linksvc.opt_out(db, link, source="app")
    audit.record(
        db,
        "whatsapp.preferences_updated",
        user_id=user.id,
        request=request,
        data={"opt_in": body.proactive_opt_in},
    )
    db.commit()
    return _status(db, user, settings)


@router.delete("/channels/whatsapp", response_model=OkOut)
def whatsapp_unlink(user: CurrentUser, db: DB, request: Request) -> OkOut:
    link = linksvc.link_for_user(db, user.id)
    if link is None:
        raise NotFound("No linked WhatsApp account.")
    linksvc.unlink(db, link, source="app")
    audit.record(db, "whatsapp.unlinked", user_id=user.id, request=request)
    db.commit()
    return OkOut(message="WhatsApp unlinked. Pending notifications were cancelled.")


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(
    user: CurrentUser, db: DB, limit: int = Query(default=50, ge=1, le=200)
) -> list[NotificationOut]:
    return [
        NotificationOut(
            id=r.id,
            kind=r.kind,
            proactive=r.proactive,
            state=r.state,
            body_preview=r.body[:140],
            created_at=r.created_at,
            not_before=r.not_before,
            sent_at=r.sent_at,
            status_at=r.status_at,
            attempts=r.attempts,
            last_error=r.last_error,
            related_batch_id=r.related_batch_id,
        )
        for r in outboxsvc.history(db, user.id, limit)
    ]


# ----------------------------------------------------------------------------- webhook (no user auth; signature-verified)


@router.get("/webhooks/whatsapp")
def webhook_verify(
    settings: AppSettings,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
) -> Response:
    if settings.ff_whatsapp_mode == "disabled" or not settings.wa_verify_token:
        return Response(status_code=404)
    import hmac as _hmac

    if (
        hub_mode == "subscribe"
        and _hmac.compare_digest(hub_verify_token, settings.wa_verify_token)
        and hub_challenge
    ):
        return Response(content=hub_challenge[:64], media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhooks/whatsapp")
async def webhook_receive(request: Request, db: DB, settings: AppSettings) -> dict:
    if settings.ff_whatsapp_mode == "disabled":
        raise AppError("WhatsApp is disabled.", code="whatsapp_disabled", status_code=404)
    body = await request.body()
    if len(body) > wa.MAX_WEBHOOK_BYTES:
        raise AppError("Payload too large.", code="payload_too_large", status_code=413)
    if not wa.verify_signature(body, request.headers.get("x-hub-signature-256"), settings.wa_app_secret):
        raise AppError("Invalid signature.", code="invalid_signature", status_code=401)
    try:
        payload = json.loads(body)
        events, ignored = wa.parse_events(payload, settings.wa_phone_number_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AppError("Malformed payload.", code="malformed_payload", status_code=400) from exc
    accepted = 0
    try:
        for ev in events:
            res = db.execute(
                pg_insert(WebhookInbox)
                .values(
                    channel="whatsapp",
                    event_key=ev.event_key[:160],
                    kind=ev.kind,
                    business_sender_id=ev.business_sender_id,
                    sender_id=ev.sender_id,
                    payload=ev.payload,
                )
                .on_conflict_do_nothing(constraint="uq_webhook_inbox_event")
                .returning(WebhookInbox.id)
            )
            accepted += len(res.fetchall())
        db.commit()
    except Exception as exc:  # durable acceptance failed -> let the platform retry
        db.rollback()
        raise ServiceUnavailable("Could not store the event; retry.") from exc
    return {"ok": True, "accepted": accepted, "duplicates": len(events) - accepted, "ignored": ignored}


# ----------------------------------------------------------------------------- operator template registry (admin)


@router.get("/admin/whatsapp/templates")
def list_templates(user: CurrentUser, db: DB) -> list[dict]:
    from focusfeed_api.errors import Forbidden

    if not user.is_admin:
        raise Forbidden("Administrator access required.")
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "language": t.language,
            "category": t.category,
            "purpose": t.purpose,
            "status": t.status,
            "parameter_count": t.parameter_count,
        }
        for t in db.scalars(select(MessageTemplate)).all()
    ]


@router.put("/admin/whatsapp/templates/{name}")
def upsert_template(name: str, body: dict, user: CurrentUser, db: DB, request: Request) -> dict:
    from focusfeed_api.errors import Forbidden

    if not user.is_admin:
        raise Forbidden("Administrator access required.")
    allowed_status = {"draft", "submitted", "approved", "rejected", "paused"}
    st = str(body.get("status", "draft"))
    if (
        st not in allowed_status
        or str(body.get("purpose", "digest")) not in {"digest", "alert", "reply_followup"}
        or str(body.get("category", "marketing")) not in {"utility", "marketing", "authentication"}
    ):
        raise ValidationFailed("Invalid template metadata.", code="template_invalid")
    lang = str(body.get("language", "en"))[:16]
    tpl = db.scalar(
        select(MessageTemplate).where(
            MessageTemplate.channel == "whatsapp",
            MessageTemplate.name == name[:120],
            MessageTemplate.language == lang,
        )
    )
    if tpl is None:
        tpl = MessageTemplate(channel="whatsapp", name=name[:120], language=lang)
        db.add(tpl)
    tpl.category, tpl.purpose, tpl.status = (
        str(body.get("category", "marketing")),
        str(body.get("purpose", "digest")),
        st,
    )
    tpl.body_preview, tpl.parameter_count = (
        str(body.get("body_preview", ""))[:1024],
        int(body.get("parameter_count", 0)),
    )
    audit.record(
        db, "admin.template_updated", user_id=user.id, request=request, data={"name": name, "status": st}
    )
    db.commit()
    return {
        "id": str(tpl.id),
        "name": tpl.name,
        "status": tpl.status,
        "purpose": tpl.purpose,
        "category": tpl.category,
    }
