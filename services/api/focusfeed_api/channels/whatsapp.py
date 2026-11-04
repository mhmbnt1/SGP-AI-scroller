"""WhatsApp Business Platform (Cloud API) transport + webhook handling.

* ``MockTransport`` for tests/demo: records sends, can simulate failures/timeouts; never touches the network.
* ``GraphTransport``: official Graph API ``/{version}/{phone_number_id}/messages`` with a bearer token;
  host fixed to graph.facebook.com. Only used when ``FF_WHATSAPP_MODE=live``.
* Webhook: GET verification (``hub.verify_token``), POST signature ``X-Hub-Signature-256`` = HMAC-SHA256
  over the *raw* body with the app secret, constant-time compare; strict payload parsing; account check.

API version and policy details could not be re-verified from the build environment (Meta docs not
reachable through the proxy); ``WA_API_VERSION`` is configuration and must be confirmed at deployment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from focusfeed_api.config import Settings

GRAPH_HOST = "graph.facebook.com"
MAX_WEBHOOK_BYTES = 256 * 1024
MAX_TEXT = 1500


@dataclass
class SendResult:
    accepted: bool
    provider_message_id: str | None = None
    error: str = ""
    ambiguous: bool = False  # timeout after the request was sent: do not blindly resend
    retryable: bool = False


@dataclass
class InboxEvent:
    kind: str  # message | status
    event_key: str
    business_sender_id: str
    sender_id: str
    payload: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- webhook helpers


def verify_signature(raw_body: bytes, header_value: str | None, app_secret: str) -> bool:
    if not header_value or not app_secret:
        return False
    scheme, _, sig = header_value.partition("=")
    if scheme != "sha256" or not sig:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.lower())


def parse_events(payload: dict[str, Any], expected_phone_number_id: str) -> tuple[list[InboxEvent], int]:
    """Return (events for our sender, ignored_count). Malformed structures raise ValueError."""
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        raise ValueError("unexpected object")
    entries = payload.get("entry")
    if not isinstance(entries, list) or len(entries) > 50:
        raise ValueError("entry must be a bounded list")
    events: list[InboxEvent] = []
    ignored = 0
    for entry in entries:
        for change in (entry or {}).get("changes", []) if isinstance(entry, dict) else []:
            value = (change or {}).get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict) or value.get("messaging_product") != "whatsapp":
                ignored += 1
                continue
            meta = value.get("metadata") or {}
            business_id = str(meta.get("phone_number_id") or "")
            if not business_id or business_id != expected_phone_number_id:
                ignored += 1
                continue
            for msg in value.get("messages", [])[:50]:
                if not isinstance(msg, dict) or not msg.get("id") or not msg.get("from"):
                    ignored += 1
                    continue
                mtype = str(msg.get("type") or "unknown")
                text = ""
                if mtype == "text":
                    text = str((msg.get("text") or {}).get("body") or "")[:MAX_TEXT]
                elif mtype == "button":
                    text = str((msg.get("button") or {}).get("text") or "")[:MAX_TEXT]
                elif mtype == "interactive":
                    inter = msg.get("interactive") or {}
                    text = str(
                        ((inter.get("button_reply") or inter.get("list_reply") or {}).get("title")) or ""
                    )[:MAX_TEXT]
                events.append(
                    InboxEvent(
                        kind="message",
                        event_key=f"msg:{msg['id']}",
                        business_sender_id=business_id,
                        sender_id=str(msg["from"])[:64],
                        payload={
                            "message_id": str(msg["id"])[:160],
                            "type": mtype,
                            "text": text,
                            "timestamp": str(msg.get("timestamp") or "")[:20],
                        },
                    )
                )
            for st in value.get("statuses", [])[:100]:
                if not isinstance(st, dict) or not st.get("id") or not st.get("status"):
                    ignored += 1
                    continue
                events.append(
                    InboxEvent(
                        kind="status",
                        event_key=f"status:{st['id']}:{st['status']}",
                        business_sender_id=business_id,
                        sender_id=str(st.get("recipient_id") or "")[:64],
                        payload={
                            "message_id": str(st["id"])[:160],
                            "status": str(st["status"])[:24],
                            "timestamp": str(st.get("timestamp") or "")[:20],
                            "error": str(((st.get("errors") or [{}])[0] or {}).get("title") or "")[:200],
                        },
                    )
                )
    return events, ignored


# ----------------------------------------------------------------------------- transports


class MockTransport:
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail_next: str | None = None  # "error" | "timeout" | "rate_limit"
        self._seq = 0

    def _next(self, kind: str, to: str, body: str, extra: dict[str, Any]) -> SendResult:
        mode, self.fail_next = self.fail_next, None
        if mode == "error":
            return SendResult(False, error="mock: provider error", retryable=False)
        if mode == "rate_limit":
            return SendResult(False, error="mock: rate limited", retryable=True)
        if mode == "timeout":
            return SendResult(False, error="mock: timeout after send", ambiguous=True)
        self._seq += 1
        mid = f"wamid.mock.{self._seq}"
        self.sent.append({"kind": kind, "to": to, "body": body, "message_id": mid, **extra})
        return SendResult(True, mid)

    def send_text(self, to: str, body: str) -> SendResult:
        return self._next("text", to, body, {})

    def send_template(self, to: str, name: str, language: str, params: list[str]) -> SendResult:
        return self._next("template", to, " | ".join(params), {"template": name, "language": language})


class GraphTransport:
    name = "graph"

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.version = settings.wa_api_version
        self.phone_number_id = settings.wa_phone_number_id
        self.token = settings.wa_access_token
        self.client = client or httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0))

    def _post(self, payload: dict[str, Any]) -> SendResult:
        url = f"https://{GRAPH_HOST}/{self.version}/{self.phone_number_id}/messages"
        started = time.monotonic()
        try:
            resp = self.client.post(url, json=payload, headers={"Authorization": f"Bearer {self.token}"})
        except httpx.TimeoutException:
            return SendResult(False, error="timeout", ambiguous=(time.monotonic() - started) > 1.0)
        except httpx.HTTPError as exc:
            return SendResult(False, error=type(exc).__name__, retryable=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            return SendResult(False, error=f"http {resp.status_code}", retryable=True)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
                msg = f"{err.get('code', '')} {str(err.get('message', ''))[:120]}"
            except ValueError:
                msg = f"http {resp.status_code}"
            return SendResult(False, error=msg, retryable=False)
        try:
            mid = str((resp.json().get("messages") or [{}])[0].get("id") or "")
        except ValueError:
            mid = ""
        return SendResult(True, mid or None)

    def send_text(self, to: str, body: str) -> SendResult:
        return self._post(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": body[:4096]},
            }
        )

    def send_template(self, to: str, name: str, language: str, params: list[str]) -> SendResult:
        components = (
            [{"type": "body", "parameters": [{"type": "text", "text": p[:1024]} for p in params]}]
            if params
            else []
        )
        return self._post(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {"name": name, "language": {"code": language}, "components": components},
            }
        )


_mock_singleton: MockTransport | None = None


def get_transport(settings: Settings):
    global _mock_singleton
    if settings.ff_whatsapp_mode == "mock":
        if _mock_singleton is None:
            _mock_singleton = MockTransport()
        return _mock_singleton
    if settings.ff_whatsapp_mode == "live":
        return GraphTransport(settings)
    raise RuntimeError("WhatsApp transport is disabled (FF_WHATSAPP_MODE=disabled)")


def reset_mock_transport() -> MockTransport:
    global _mock_singleton
    _mock_singleton = MockTransport()
    return _mock_singleton


def sign(raw_body: bytes, app_secret: str) -> str:
    return "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()


def minimal_payload_for_tests(phone_number_id: str, sender: str, text: str, msg_id: str) -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA",
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15550000000",
                                    "phone_number_id": phone_number_id,
                                },
                                "contacts": [{"wa_id": sender, "profile": {"name": "Test"}}],
                                "messages": [
                                    {
                                        "from": sender,
                                        "id": msg_id,
                                        "timestamp": str(int(time.time())),
                                        "type": "text",
                                        "text": {"body": text},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    ).encode()
