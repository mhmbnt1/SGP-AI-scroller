"""Credential vault: AES-256-GCM with versioned deployment keys, bound to owner/provider context.

* Keys come from ``FF_CREDENTIAL_KEYS`` ("v1:<base64 32 bytes>,v2:<base64>") — deployment
  configuration kept outside the database. ``FF_CREDENTIAL_ACTIVE_KEY`` selects the key for new
  writes; older versions stay decryptable until every row is re-encrypted (``rotate``).
* Associated data = "<scope>:<owner>:<provider>" so a ciphertext copied onto another user's row or
  another provider fails authentication.
* Development only: when no keys are configured outside production, a key is derived from
  ``FF_SECRET_KEY`` so the feature works locally; production refuses to start without explicit keys.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets as _secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class VaultError(Exception):
    pass


@dataclass(frozen=True)
class Encrypted:
    ciphertext_b64: str
    key_version: str


class CredentialVault:
    def __init__(self, keys: dict[str, bytes], active: str) -> None:
        if active not in keys:
            raise VaultError(f"active key version {active!r} is not configured")
        self._keys = keys
        self.active = active

    @classmethod
    def from_settings(
        cls, keys_spec: str, active: str, *, dev_secret: str | None, production: bool
    ) -> CredentialVault:
        keys: dict[str, bytes] = {}
        for part in [p.strip() for p in keys_spec.split(",") if p.strip()]:
            version, _, b64 = part.partition(":")
            raw = base64.b64decode(b64)
            if len(raw) != 32:
                raise VaultError(f"credential key {version} must be 32 bytes (base64)")
            keys[version] = raw
        if not keys:
            if production or not dev_secret:
                raise VaultError("FF_CREDENTIAL_KEYS is required (32-byte base64 key per version)")
            keys = {"dev": hashlib.sha256(f"dev-credential-key:{dev_secret}".encode()).digest()}
            active = "dev"
        return cls(keys, active)

    @staticmethod
    def aad(scope: str, owner: str, provider: str) -> bytes:
        return f"{scope}:{owner}:{provider}".encode()

    def encrypt(self, plaintext: str, *, scope: str, owner: str, provider: str) -> Encrypted:
        nonce = _secrets.token_bytes(12)
        ct = AESGCM(self._keys[self.active]).encrypt(
            nonce, plaintext.encode("utf-8"), self.aad(scope, owner, provider)
        )
        return Encrypted(base64.b64encode(nonce + ct).decode(), self.active)

    def decrypt(self, enc: Encrypted, *, scope: str, owner: str, provider: str) -> str:
        key = self._keys.get(enc.key_version)
        if key is None:
            raise VaultError(f"no key for version {enc.key_version}")
        raw = base64.b64decode(enc.ciphertext_b64)
        try:
            return AESGCM(key).decrypt(raw[:12], raw[12:], self.aad(scope, owner, provider)).decode("utf-8")
        except Exception as exc:  # InvalidTag or malformed
            raise VaultError("credential cannot be decrypted (wrong key version or context)") from exc

    def rotate(self, enc: Encrypted, *, scope: str, owner: str, provider: str) -> Encrypted:
        """Re-encrypt under the active key (used by the operator rotation command)."""
        return self.encrypt(
            self.decrypt(enc, scope=scope, owner=owner, provider=provider),
            scope=scope,
            owner=owner,
            provider=provider,
        )


def generate_key_spec(version: str = "v1") -> str:
    return f"{version}:{base64.b64encode(os.urandom(32)).decode()}"


def mask_key(value: str) -> str:
    """Only a hint survives: provider prefix shape + last 4 characters."""
    if len(value) < 8:
        return "****"
    return f"{value[:3]}…{value[-4:]}"
