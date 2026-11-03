"""Redaction helpers for logs, job events and error details."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS = [
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[A-Za-z0-9\-_\.=]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(cookie\s*[:=]\s*)[^;\s]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)(session|token|secret|password|api[_-]?key|credential)(\"?\s*[:=]\s*\"?)[^\s\"',}]+"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"[A-Za-z0-9_\-]{40,}"), "[REDACTED_LONG_TOKEN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[REDACTED_EMAIL]"),
]

SENSITIVE_KEYS = {
    "password",
    "token",
    "secret",
    "cookie",
    "authorization",
    "credential",
    "api_key",
    "lease_token",
    "code",
    "session",
}


def redact_text(text: str, max_len: int = 1000) -> str:
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out[:max_len]


def redact_mapping(data: dict[str, Any], max_depth: int = 4) -> dict[str, Any]:
    def _walk(v: Any, depth: int) -> Any:
        if depth > max_depth:
            return "[TRUNCATED]"
        if isinstance(v, dict):
            return {
                k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else _walk(vv, depth + 1))
                for k, vv in v.items()
            }
        if isinstance(v, list):
            return [_walk(x, depth + 1) for x in v[:50]]
        if isinstance(v, str):
            return redact_text(v, 500)
        return v

    return _walk(data, 0)
