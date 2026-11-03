"""Opaque random tokens and their storage hashes.

We never store raw session/device/enrollment tokens. The database holds a
SHA-256 of the token; a database leak therefore does not yield usable
credentials. Comparison happens on the hash lookup (constant-length).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_enrollment_code() -> str:
    """Human-typable one-use pairing code: 4 groups of 4 (base32, no ambiguous chars)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(16))
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def normalize_enrollment_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().upper()


def csrf_token_for(session_id: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"csrf:{session_id}".encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
