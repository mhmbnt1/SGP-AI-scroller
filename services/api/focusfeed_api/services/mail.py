"""Outbound email for account recovery.

Modes (``FF_MAIL_MODE``):
* ``disabled`` (default): recovery is unavailable; clients show the operator-managed fallback.
* ``capture``: development/test only; mails are kept in memory so tests can read the code.
* ``smtp``: real delivery through the operator's SMTP relay (STARTTLS by default).

The message body carries a one-time code, so it is never logged.
"""

from __future__ import annotations

import logging
import smtplib
import threading
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

log = logging.getLogger("focusfeed.mail")


class MailUnavailable(RuntimeError):
    """Raised when no delivery path is configured."""


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


_captured: list[Mail] = []
_lock = threading.Lock()


def captured() -> list[Mail]:
    with _lock:
        return list(_captured)


def clear_captured() -> None:
    with _lock:
        _captured.clear()


def _mask(addr: str) -> str:
    local, _, domain = addr.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def available(settings: Any) -> bool:
    return settings.ff_mail_mode in {"capture", "smtp"}


def send(settings: Any, mail: Mail) -> None:
    mode = settings.ff_mail_mode
    if mode == "capture":
        with _lock:
            _captured.append(mail)
        log.info("mail captured to=%s subject=%s", _mask(mail.to), mail.subject)
        return
    if mode != "smtp":
        raise MailUnavailable("Email delivery is not configured on this service.")
    msg = EmailMessage()
    msg["From"] = settings.ff_smtp_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg.set_content(mail.body)
    with smtplib.SMTP(settings.ff_smtp_host, settings.ff_smtp_port, timeout=20) as smtp:
        if settings.ff_smtp_starttls:
            smtp.starttls()
        if settings.ff_smtp_username:
            smtp.login(settings.ff_smtp_username, settings.ff_smtp_password)
        smtp.send_message(msg)
    log.info("mail sent to=%s subject=%s", _mask(mail.to), mail.subject)
