"""Collector local state: profiles directory, device credential (OS keyring), API base URL.

The collector never stores social passwords. Platform cookies live only inside
the dedicated Chromium profile directory under ``state_dir/profiles/<platform>``.
On Windows that directory is protected by NTFS user ACLs (not encrypted by the
browser itself) — see docs/SECURITY_CONTROLS.md for the honest statement.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

KEYRING_SERVICE = "focusfeed-collector"
KEYRING_USER = "device-credential"


def default_state_dir() -> Path:
    env = os.environ.get("FF_COLLECTOR_STATE_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "FocusFeed" / "collector"
    return Path.home() / ".focusfeed" / "collector"


@dataclass
class CollectorConfig:
    api_base_url: str = "http://localhost:8000"
    state_dir: Path = field(default_factory=default_state_dir)
    device_id: str | None = None
    display_name: str = ""
    poll_seconds: int = 5
    headed: bool = False
    platforms: list[str] = field(default_factory=lambda: ["youtube", "instagram"])

    @property
    def config_path(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def profiles_dir(self) -> Path:
        return self.state_dir / "profiles"

    def profile_dir(self, platform: str) -> Path:
        return self.profiles_dir / platform

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _restrict(self.state_dir)
        data = {
            "api_base_url": self.api_base_url,
            "device_id": self.device_id,
            "display_name": self.display_name,
            "poll_seconds": self.poll_seconds,
            "headed": self.headed,
            "platforms": self.platforms,
        }
        self.config_path.write_text(json.dumps(data, indent=2))
        _restrict(self.config_path)

    @classmethod
    def load(cls, api_base_url: str | None = None) -> CollectorConfig:
        cfg = cls()
        if cfg.config_path.exists():
            data = json.loads(cfg.config_path.read_text())
            cfg.api_base_url = data.get("api_base_url", cfg.api_base_url)
            cfg.device_id = data.get("device_id")
            cfg.display_name = data.get("display_name", "")
            cfg.poll_seconds = int(data.get("poll_seconds", 5))
            cfg.headed = bool(data.get("headed", False))
            cfg.platforms = list(data.get("platforms", cfg.platforms))
        if api_base_url:
            cfg.api_base_url = api_base_url.rstrip("/")
        env_url = os.environ.get("FF_API_BASE_URL")
        if env_url and not api_base_url:
            cfg.api_base_url = env_url.rstrip("/")
        return cfg


def _restrict(path: Path) -> None:
    """Best-effort: owner-only permissions on POSIX; on Windows the per-user AppData ACL applies."""
    if os.name != "nt":
        try:
            path.chmod(stat.S_IRWXU if path.is_dir() else stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass


class CredentialStore:
    """Device credential in the OS keyring (Windows Credential Manager / macOS Keychain / Secret Service).

    Falls back to an owner-only file in the state directory when no keyring backend is available
    (e.g. headless Linux CI). The fallback is reported by ``backend_name``.
    """

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.fallback = state_dir / "device-credential"

    def backend_name(self) -> str:
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            backend = keyring.get_keyring()
            if isinstance(backend, FailKeyring):
                return "file-fallback"
            return type(backend).__name__
        except Exception:
            return "file-fallback"

    def get(self) -> str | None:
        try:
            import keyring

            value = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
            if value:
                return value
        except Exception:
            pass
        if self.fallback.exists():
            return self.fallback.read_text().strip() or None
        return None

    def set(self, value: str) -> str:
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, value)
            if keyring.get_password(KEYRING_SERVICE, KEYRING_USER) == value:
                return self.backend_name()
        except Exception:
            pass
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.fallback.write_text(value)
        _restrict(self.fallback)
        return "file-fallback"

    def clear(self) -> None:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass
        if self.fallback.exists():
            self.fallback.unlink()
