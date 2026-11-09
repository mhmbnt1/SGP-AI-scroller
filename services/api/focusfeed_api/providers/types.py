"""Normalized provider request/result types and safe error classification (Phase 2).

Every hosted adapter speaks this vocabulary so routing, usage accounting, fallback
rules and tests do not depend on SDK-specific objects.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from focusfeed_api.providers.base import (
    InvalidOutput,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
)

TaskType = Literal["summary", "chat", "intent", "vision", "embedding", "connection_test"]
CredentialScope = Literal["operator", "user"]


class AuthError(ProviderError):
    """Invalid/revoked credential. Never retried, never a reason to fall back to operator keys."""

    code = "provider_auth"
    retryable = False


class BillingError(ProviderError):
    """Insufficient balance / quota on the provider account. Not retried."""

    code = "provider_billing"
    retryable = False


class RateLimitedError(ProviderError):
    """HTTP 429 or provider throttling. Retried with backoff within the per-call budget."""

    code = "provider_rate_limited"
    retryable = True


class PolicyRefusal(ProviderError):
    """The provider refused the content for policy reasons. Not retried."""

    code = "provider_refusal"
    retryable = False


class CapabilityUnsupported(ProviderError):
    """The (provider, model) pair does not support the requested task (e.g. embeddings on Anthropic)."""

    code = "capability_unsupported"
    retryable = False


class CircuitOpen(ProviderUnavailable):
    code = "provider_circuit_open"


@dataclass
class ProviderRequest:
    provider: str
    model: str
    task: TaskType
    credential_ref: str  # connection id or "operator:<provider>" — never a raw key
    system: str = ""
    user: str = ""
    schema: dict[str, Any] | None = None
    images: list[bytes] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)  # embeddings
    max_output_tokens: int = 800
    timeout_seconds: float = 60.0


@dataclass
class ProviderResult:
    provider: str
    model: str
    parsed: dict[str, Any] | None
    raw_text: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    request_id: str | None
    fallback_from: str | None = None  # "provider/model" when a permitted fallback was used
    vectors: list[list[float]] | None = None


def classify_exception(exc: BaseException) -> ProviderError:
    """Map SDK exceptions to the normalized hierarchy using status codes and class names only.

    Messages are truncated and never include request bodies or credentials.
    """
    if isinstance(exc, ProviderError):
        return exc
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    name = type(exc).__name__
    msg = f"{name}: {str(exc)[:120]}"
    if isinstance(status, int):
        if status in (401, 403):
            return AuthError(msg)
        if status == 402:
            return BillingError(msg)
        if status == 429:
            low = str(exc).lower()
            if "quota" in low or "billing" in low or "insufficient" in low:
                return BillingError(msg)
            return RateLimitedError(msg)
        if status in (408, 504):
            return ProviderTimeout(msg)
        if status >= 500:
            return ProviderUnavailable(msg)
        if status == 400 and "refus" in str(exc).lower():
            return PolicyRefusal(msg)
        if status in (400, 404, 422):
            return InvalidOutput(msg)
    lname = name.lower()
    if "timeout" in lname:
        return ProviderTimeout(msg)
    if "authentication" in lname or "permission" in lname:
        return AuthError(msg)
    if "ratelimit" in lname:
        return RateLimitedError(msg)
    if "connection" in lname or "unavailable" in lname:
        return ProviderUnavailable(msg)
    return ProviderUnavailable(msg)


class CircuitBreaker:
    """Per-provider in-process breaker: opens after N consecutive transient failures for a cooldown."""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 60.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def check(self, key: str) -> None:
        until = self._open_until.get(key, 0.0)
        if until and time.monotonic() < until:
            raise CircuitOpen(f"{key} temporarily disabled after repeated failures")

    def record_success(self, key: str) -> None:
        self._failures[key] = 0
        self._open_until.pop(key, None)

    def record_failure(self, key: str) -> None:
        n = self._failures.get(key, 0) + 1
        self._failures[key] = n
        if n >= self.threshold:
            self._open_until[key] = time.monotonic() + self.cooldown

    def reset(self) -> None:
        self._failures.clear()
        self._open_until.clear()


breaker = CircuitBreaker()


def with_retries(
    fn: Callable[[], Any],
    *,
    key: str,
    attempts: int = 2,
    base_delay: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry only retryable errors (rate limit, timeout, unavailable); bounded; records breaker state."""
    breaker.check(key)
    last: ProviderError | None = None
    for i in range(attempts + 1):
        try:
            out = fn()
            breaker.record_success(key)
            return out
        except BaseException as exc:  # noqa: BLE001 - classified immediately
            err = classify_exception(exc)
            if not err.retryable or i == attempts:
                if err.retryable:
                    breaker.record_failure(key)
                raise err from exc
            last = err
            sleep(base_delay * (2**i))
    assert last is not None
    raise last
