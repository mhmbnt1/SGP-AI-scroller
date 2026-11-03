"""Interchangeable model provider interface.

Every provider must:
* report health and discovered models with *measured* capabilities,
* produce validated structured output (JSON schema) or raise ``InvalidOutput``,
* optionally embed text and interpret images,
* respect timeouts and a cooperative ``CancelToken``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    code = "provider_error"
    retryable = False


class ProviderUnavailable(ProviderError):
    """Server/model is not reachable or not installed (distinct from a deadline)."""

    code = "provider_unavailable"
    retryable = True


class ProviderTimeout(ProviderError):
    """The bounded per-call deadline elapsed."""

    code = "provider_timeout"
    retryable = True


class InvalidOutput(ProviderError):
    """The model returned something that does not validate against the schema."""

    code = "invalid_output"
    retryable = True


class Cancelled(ProviderError):
    code = "cancelled"


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise Cancelled("cancelled")


@dataclass
class ModelInfo:
    name: str
    purposes: set[str] = field(default_factory=set)  # text | embedding | vision
    json_output: bool = False
    vision: bool = False
    embeddings: bool = False
    context_window: int | None = None
    parameter_size: str | None = None
    embedding_dimensions: int | None = None


@dataclass
class ProviderHealth:
    healthy: bool
    detail: str
    models: list[ModelInfo] = field(default_factory=list)


@dataclass
class GenerationResult:
    parsed: dict[str, Any]
    raw_text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    model: str


class Provider(Protocol):
    name: str

    def health(self) -> ProviderHealth: ...

    def generate_structured(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        timeout_seconds: float,
        max_output_tokens: int = 800,
        cancel: CancelToken | None = None,
    ) -> GenerationResult: ...

    def embed(self, *, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]: ...

    def supports_vision(self, model: str) -> bool: ...

    def describe_image(
        self, *, model: str, image_bytes: bytes, prompt: str, timeout_seconds: float
    ) -> str: ...
