"""Model catalog: configuration data, not scattered constants.

* ``verified`` is false for every entry shipped here: model IDs and prices were taken from SDK/vendor
  knowledge and could NOT be re-checked against vendor documentation from the build environment
  (vendor doc hosts are not reachable through the proxy). Operators must confirm them at deployment
  and may override the whole catalog with ``FF_MODEL_CATALOG_PATH`` (JSON with the same shape).
* Prices carry currency, source and effective date; ``None`` means "unknown" and usage is then
  accounted as tokens only (cost = unknown/unavailable).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

PROVIDER_META: dict[str, dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI models",
        "help": "The models behind ChatGPT, accessed through the OpenAI API (not the ChatGPT app).",
        "base_url": "https://api.openai.com/v1",
        "operator_env": "OPENAI_API_KEY",
        "sdk": "openai (official Python SDK)",
    },
    "anthropic": {
        "display_name": "Anthropic Claude",
        "help": "Claude models through the Anthropic API.",
        "base_url": "https://api.anthropic.com",
        "operator_env": "ANTHROPIC_API_KEY",
        "sdk": "anthropic (official Python SDK)",
    },
    "gemini": {
        "display_name": "Google Gemini",
        "help": "Gemini models through the Google Gemini API (Google GenAI SDK).",
        "base_url": "https://generativelanguage.googleapis.com",
        "operator_env": "GEMINI_API_KEY",
        "sdk": "google-genai (official Python SDK)",
    },
    "xai": {
        "display_name": "xAI Grok",
        "help": "Grok models through the xAI API (OpenAI-compatible endpoint).",
        "base_url": "https://api.x.ai/v1",
        "operator_env": "XAI_API_KEY",
        "sdk": "openai SDK pointed at api.x.ai (documented OpenAI-compatible API)",
    },
    "ollama": {
        "display_name": "Service-hosted Ollama",
        "help": "Open models run on the operator's own inference host. No external API.",
        "base_url": None,  # deployment configuration (OLLAMA_BASE_URL), never user-supplied
        "operator_env": "OLLAMA_BASE_URL",
        "sdk": "HTTP (httpx)",
    },
    "fake": {
        "display_name": "Deterministic test provider",
        "help": "Tests/demo only.",
        "base_url": None,
        "operator_env": "",
        "sdk": "in-process",
    },
}

ALLOWLISTED_HOSTS = {"api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "api.x.ai"}


@dataclass(frozen=True)
class Price:
    input_usd_per_1m: float
    output_usd_per_1m: float
    currency: str = "USD"
    source: str = "vendor price list as remembered at build time — NOT verified; confirm before relying on it"
    effective_date: str = "2026-11-04"


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    id: str
    label: str
    tasks: tuple[str, ...]  # subset of: chat, summary, intent, json, vision, embedding
    context_window: int | None = None
    embedding_dimensions: int | None = None
    price: Price | None = None
    verified: bool = False
    default_for: tuple[str, ...] = field(default_factory=tuple)

    def supports(self, task: str) -> bool:
        if task in ("summary", "chat", "intent", "connection_test"):
            return "chat" in self.tasks
        return task in self.tasks


DEFAULT_CATALOG: list[ModelSpec] = [
    # OpenAI
    ModelSpec(
        "openai",
        "gpt-4.1-mini",
        "GPT-4.1 mini",
        ("chat", "json", "vision"),
        1_000_000,
        price=Price(0.40, 1.60),
        default_for=("chat", "summary", "intent", "vision"),
    ),
    ModelSpec("openai", "gpt-4.1", "GPT-4.1", ("chat", "json", "vision"), 1_000_000, price=Price(2.00, 8.00)),
    ModelSpec(
        "openai", "gpt-4o-mini", "GPT-4o mini", ("chat", "json", "vision"), 128_000, price=Price(0.15, 0.60)
    ),
    ModelSpec(
        "openai",
        "text-embedding-3-small",
        "text-embedding-3-small",
        ("embedding",),
        embedding_dimensions=1536,
        price=Price(0.02, 0.0),
        default_for=("embedding",),
    ),
    # Anthropic
    ModelSpec(
        "anthropic",
        "claude-haiku-4-5",
        "Claude Haiku 4.5",
        ("chat", "json", "vision"),
        200_000,
        price=Price(1.00, 5.00),
        default_for=("chat", "summary", "intent", "vision"),
    ),
    ModelSpec(
        "anthropic",
        "claude-sonnet-4-5",
        "Claude Sonnet 4.5",
        ("chat", "json", "vision"),
        200_000,
        price=Price(3.00, 15.00),
    ),
    # Gemini
    ModelSpec(
        "gemini",
        "gemini-2.5-flash",
        "Gemini 2.5 Flash",
        ("chat", "json", "vision"),
        1_000_000,
        price=Price(0.30, 2.50),
        default_for=("chat", "summary", "intent", "vision"),
    ),
    ModelSpec(
        "gemini",
        "gemini-2.5-flash-lite",
        "Gemini 2.5 Flash-Lite",
        ("chat", "json", "vision"),
        1_000_000,
        price=Price(0.10, 0.40),
    ),
    ModelSpec(
        "gemini",
        "gemini-embedding-001",
        "Gemini Embedding 001",
        ("embedding",),
        embedding_dimensions=3072,
        price=None,
        default_for=("embedding",),
    ),
    # xAI
    ModelSpec(
        "xai",
        "grok-4-fast-non-reasoning",
        "Grok 4 Fast",
        ("chat", "json", "vision"),
        2_000_000,
        price=Price(0.20, 0.50),
        default_for=("chat", "summary", "intent", "vision"),
    ),
    ModelSpec("xai", "grok-3-mini", "Grok 3 mini", ("chat", "json"), 131_072, price=Price(0.30, 0.50)),
    # Ollama (operator host; ids are whatever the operator pulled)
    ModelSpec(
        "ollama",
        "qwen2.5:7b-instruct",
        "Qwen2.5 7B (hosted)",
        ("chat", "json"),
        32_768,
        price=Price(
            0.0,
            0.0,
            source="self-hosted: no per-token price; operator pays hosting",
            effective_date="2026-11-04",
        ),
        default_for=("chat", "summary", "intent"),
    ),
    ModelSpec(
        "ollama",
        "llama3.2:3b",
        "Llama 3.2 3B (hosted)",
        ("chat", "json"),
        131_072,
        price=Price(0.0, 0.0, source="self-hosted", effective_date="2026-11-04"),
    ),
    ModelSpec(
        "ollama",
        "nomic-embed-text",
        "nomic-embed-text (hosted)",
        ("embedding",),
        embedding_dimensions=768,
        price=Price(0.0, 0.0, source="self-hosted", effective_date="2026-11-04"),
        default_for=("embedding",),
    ),
    # Fake
    ModelSpec(
        "fake",
        "fake-text",
        "Fake text (tests)",
        ("chat", "json"),
        8192,
        price=Price(0.0, 0.0, source="n/a", effective_date="2026-11-04"),
        verified=True,
        default_for=("chat", "summary", "intent"),
    ),
    ModelSpec(
        "fake",
        "fake-embed",
        "Fake embeddings (tests)",
        ("embedding",),
        embedding_dimensions=64,
        price=Price(0.0, 0.0, source="n/a", effective_date="2026-11-04"),
        verified=True,
        default_for=("embedding",),
    ),
]


def _from_json(path: str) -> list[ModelSpec]:
    data = json.loads(open(path, encoding="utf-8").read())  # noqa: SIM115 - small config file
    out: list[ModelSpec] = []
    for m in data["models"]:
        price = Price(**m["price"]) if m.get("price") else None
        out.append(
            ModelSpec(
                m["provider"],
                m["id"],
                m.get("label", m["id"]),
                tuple(m["tasks"]),
                m.get("context_window"),
                m.get("embedding_dimensions"),
                price,
                bool(m.get("verified", False)),
                tuple(m.get("default_for", [])),
            )
        )
    return out


@lru_cache
def catalog() -> list[ModelSpec]:
    path = os.environ.get("FF_MODEL_CATALOG_PATH")
    if path and os.path.exists(path):
        return _from_json(path)
    return list(DEFAULT_CATALOG)


def models_for(provider: str) -> list[ModelSpec]:
    return [m for m in catalog() if m.provider == provider]


def find_model(provider: str, model_id: str) -> ModelSpec | None:
    return next((m for m in catalog() if m.provider == provider and m.id == model_id), None)


def default_model(provider: str, task: str) -> ModelSpec | None:
    t = "embedding" if task == "embedding" else ("vision" if task == "vision" else "chat")
    for m in models_for(provider):
        if t in m.default_for or (t == "chat" and "chat" in m.default_for):
            return m
    return next((m for m in models_for(provider) if m.supports(task)), None)


def estimate_cost_usd(
    spec: ModelSpec | None, input_tokens: int | None, output_tokens: int | None
) -> tuple[float | None, str]:
    """Return (estimate, pricing_source). None when pricing or usage is unknown."""
    if spec is None or spec.price is None or input_tokens is None or output_tokens is None:
        return None, "unknown"
    cost = (input_tokens / 1_000_000) * spec.price.input_usd_per_1m + (
        output_tokens / 1_000_000
    ) * spec.price.output_usd_per_1m
    return round(cost, 6), spec.price.source


def as_dict(spec: ModelSpec) -> dict[str, Any]:
    d = asdict(spec)
    d["tasks"] = list(spec.tasks)
    d["default_for"] = list(spec.default_for)
    return d
