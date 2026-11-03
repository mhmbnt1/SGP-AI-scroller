"""Argon2id password hashing via argon2-cffi (OWASP ASVS V2.4 / password storage cheat sheet)."""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Parameters follow the OWASP Password Storage Cheat Sheet minimums for Argon2id
# (m=19 MiB, t=2, p=1). They are deliberately modest so a Windows dev box stays responsive.
_hasher = PasswordHasher(
    time_cost=2, memory_cost=19 * 1024, parallelism=1, hash_len=32, salt_len=16, type=Type.ID
)

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_policy(password: str) -> str | None:
    """Return a user-readable problem, or None when acceptable.

    Length-based policy per ASVS 2.1 (no composition rules). A tiny denylist of
    the most common passwords is enforced; a full breached-password check is a
    documented residual gap.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use at most {MAX_PASSWORD_LENGTH} characters."
    lowered = password.lower()
    if lowered in {"password12", "passwordpassword", "1234567890", "qwertyuiop", "focusfeed123"}:
        return "That password is too common."
    return None
