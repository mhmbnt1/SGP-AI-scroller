"""Provider factory driven by settings. External providers stay disabled unless explicitly enabled."""

from __future__ import annotations

from focusfeed_api.config import Settings, get_settings
from focusfeed_api.providers.base import Provider
from focusfeed_api.providers.fake import FakeProvider
from focusfeed_api.providers.ollama import OllamaProvider

_override: Provider | None = None


def set_provider_override(provider: Provider | None) -> None:
    """Tests inject a provider (e.g. a FakeProvider with a fail mode)."""
    global _override
    _override = provider


def get_provider(settings: Settings | None = None) -> Provider:
    if _override is not None:
        return _override
    settings = settings or get_settings()
    if settings.ff_mode == "test":
        return FakeProvider()
    if settings.ff_llm_provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, default_timeout=settings.ff_model_timeout_seconds)
    return FakeProvider()
