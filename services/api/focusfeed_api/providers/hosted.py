"""Hosted provider adapters: OpenAI (and xAI via the OpenAI-compatible endpoint), Anthropic, Gemini.

Each adapter implements the existing ``Provider`` protocol so the pipeline is unchanged, and keeps
the SDK call behind one ``_raw_*`` boundary that tests replace with fixtures. Keys are passed in at
construction from the credential vault and never stored on the instance beyond the SDK client.
Origins are fixed (allowlisted); users cannot supply base URLs.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

from focusfeed_api.providers.base import (
    CancelToken,
    GenerationResult,
    InvalidOutput,
    ModelInfo,
    ProviderHealth,
)
from focusfeed_api.providers.catalog import PROVIDER_META, find_model, models_for
from focusfeed_api.providers.types import CapabilityUnsupported, with_retries


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidOutput("model output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidOutput("model output was not a JSON object")
    return parsed


class _HostedBase:
    name = "hosted"

    def __init__(
        self, api_key: str, *, default_timeout: float = 60.0, http_client: Any | None = None
    ) -> None:
        self._api_key = api_key
        self.default_timeout = default_timeout
        self._http_client = http_client
        self.last_request_id: str | None = None

    # -- capability discovery from the catalog (no network) --------------------------------------
    def health(self) -> ProviderHealth:
        models = [
            ModelInfo(
                name=m.id,
                purposes=set(("text",) if "chat" in m.tasks else ())
                | set(("embedding",) if "embedding" in m.tasks else ())
                | set(("vision",) if "vision" in m.tasks else ()),
                json_output="json" in m.tasks,
                vision="vision" in m.tasks,
                embeddings="embedding" in m.tasks,
                context_window=m.context_window,
                embedding_dimensions=m.embedding_dimensions,
            )
            for m in models_for(self.name)
        ]
        return ProviderHealth(
            healthy=bool(self._api_key),
            detail="configured (catalog); reachability requires a connection test",
            models=models,
        )

    def supports_vision(self, model: str) -> bool:
        spec = find_model(self.name, model)
        return bool(spec and "vision" in spec.tasks)

    def _require(self, model: str, task: str) -> None:
        spec = find_model(self.name, model)
        if spec is None:
            raise CapabilityUnsupported(f"{self.name}/{model} is not in the catalog")
        if not spec.supports(task):
            raise CapabilityUnsupported(f"{self.name}/{model} does not support {task}")

    # -- Provider protocol -----------------------------------------------------------------------
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
    ) -> GenerationResult:
        if cancel is not None:
            cancel.raise_if_cancelled()
        self._require(model, "chat")
        start = time.perf_counter()
        raw = with_retries(
            lambda: self._raw_chat(
                model, system, user, schema, timeout_seconds or self.default_timeout, max_output_tokens
            ),
            key=self.name,
        )
        parsed = _parse_json_object(raw["text"])
        self.last_request_id = raw.get("request_id")
        return GenerationResult(
            parsed=parsed,
            raw_text=raw["text"],
            input_tokens=raw.get("input_tokens"),
            output_tokens=raw.get("output_tokens"),
            latency_ms=int((time.perf_counter() - start) * 1000),
            model=model,
        )

    def embed(self, *, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        self._require(model, "embedding")
        raw = with_retries(
            lambda: self._raw_embed(model, texts, timeout_seconds or self.default_timeout),
            key=f"{self.name}:embed",
        )
        vectors = raw["vectors"]
        if len(vectors) != len(texts):
            raise InvalidOutput("embedding count mismatch")
        self.last_request_id = raw.get("request_id")
        return vectors

    def describe_image(self, *, model: str, image_bytes: bytes, prompt: str, timeout_seconds: float) -> str:
        self._require(model, "vision")
        raw = with_retries(
            lambda: self._raw_vision(model, image_bytes, prompt, timeout_seconds or self.default_timeout),
            key=f"{self.name}:vision",
        )
        self.last_request_id = raw.get("request_id")
        return str(raw["text"])[:1000]

    def test_connection(self, model: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
        """Deliberate, user-requested connection test (counted in usage by the caller)."""
        res = self.generate_structured(
            model=model,
            system="Reply with JSON only.",
            user='{"task":"ping"}',
            schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
            timeout_seconds=timeout_seconds,
            max_output_tokens=20,
        )
        return {
            "ok": True,
            "model": model,
            "latency_ms": res.latency_ms,
            "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens,
            "request_id": self.last_request_id,
        }

    # -- SDK boundaries (overridden per provider; patched in tests) -------------------------------
    def _raw_chat(
        self,
        model: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        timeout: float,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _raw_embed(self, model: str, texts: list[str], timeout: float) -> dict[str, Any]:
        raise CapabilityUnsupported(f"{self.name} has no embedding models")

    def _raw_vision(self, model: str, image_bytes: bytes, prompt: str, timeout: float) -> dict[str, Any]:
        raise CapabilityUnsupported(f"{self.name} vision not implemented")


class OpenAICompatibleProvider(_HostedBase):
    """OpenAI, and xAI through its documented OpenAI-compatible API (fixed base URL from the catalog)."""

    def __init__(self, api_key: str, *, name: str = "openai", **kw: Any) -> None:
        super().__init__(api_key, **kw)
        self.name = name
        self.base_url = PROVIDER_META[name]["base_url"]

    def _client(self, timeout: float):
        import openai

        return openai.OpenAI(
            api_key=self._api_key,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=0,
            http_client=self._http_client,
        )

    def _raw_chat(self, model, system, user, schema, timeout, max_output_tokens):
        client = self._client(timeout)
        raw = client.chat.completions.with_raw_response.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema, "strict": False},
            },
            max_completion_tokens=max_output_tokens,
            temperature=0,
        )
        comp = raw.parse()
        choice = comp.choices[0]
        if getattr(choice, "finish_reason", "") == "content_filter":
            from focusfeed_api.providers.types import PolicyRefusal

            raise PolicyRefusal("content filtered by provider")
        usage = comp.usage
        return {
            "text": choice.message.content or "",
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "request_id": raw.headers.get("x-request-id"),
        }

    def _raw_embed(self, model, texts, timeout):
        client = self._client(timeout)
        raw = client.embeddings.with_raw_response.create(model=model, input=texts)
        emb = raw.parse()
        return {
            "vectors": [[float(x) for x in d.embedding] for d in emb.data],
            "request_id": raw.headers.get("x-request-id"),
            "input_tokens": getattr(emb.usage, "prompt_tokens", None),
        }

    def _raw_vision(self, model, image_bytes, prompt, timeout):
        client = self._client(timeout)
        b64 = base64.b64encode(image_bytes).decode()
        raw = client.chat.completions.with_raw_response.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ],
            max_completion_tokens=200,
            temperature=0,
        )
        comp = raw.parse()
        return {
            "text": comp.choices[0].message.content or "",
            "request_id": raw.headers.get("x-request-id"),
            "input_tokens": getattr(comp.usage, "prompt_tokens", None),
            "output_tokens": getattr(comp.usage, "completion_tokens", None),
        }


class AnthropicProvider(_HostedBase):
    name = "anthropic"

    def _client(self, timeout: float):
        import anthropic

        return anthropic.Anthropic(
            api_key=self._api_key, timeout=timeout, max_retries=0, http_client=self._http_client
        )

    def _raw_chat(self, model, system, user, schema, timeout, max_output_tokens):
        client = self._client(timeout)
        raw = client.messages.with_raw_response.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        msg = raw.parse()
        if getattr(msg, "stop_reason", "") == "refusal":
            from focusfeed_api.providers.types import PolicyRefusal

            raise PolicyRefusal("model refused the request")
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return {
            "text": text,
            "input_tokens": getattr(msg.usage, "input_tokens", None),
            "output_tokens": getattr(msg.usage, "output_tokens", None),
            "request_id": raw.headers.get("request-id"),
        }

    def _raw_vision(self, model, image_bytes, prompt, timeout):
        client = self._client(timeout)
        b64 = base64.b64encode(image_bytes).decode()
        raw = client.messages.with_raw_response.create(
            model=model,
            max_tokens=200,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        msg = raw.parse()
        text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")
        return {
            "text": text,
            "request_id": raw.headers.get("request-id"),
            "input_tokens": getattr(msg.usage, "input_tokens", None),
            "output_tokens": getattr(msg.usage, "output_tokens", None),
        }


class GeminiProvider(_HostedBase):
    name = "gemini"

    def _client(self, timeout: float):
        from google import genai
        from google.genai import types as gt

        return genai.Client(api_key=self._api_key, http_options=gt.HttpOptions(timeout=int(timeout * 1000)))

    def _raw_chat(self, model, system, user, schema, timeout, max_output_tokens):
        from google.genai import types as gt

        client = self._client(timeout)
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=gt.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema,
                max_output_tokens=max_output_tokens,
                temperature=0,
            ),
        )
        um = getattr(resp, "usage_metadata", None)
        if getattr(resp, "prompt_feedback", None) and getattr(resp.prompt_feedback, "block_reason", None):
            from focusfeed_api.providers.types import PolicyRefusal

            raise PolicyRefusal(f"blocked: {resp.prompt_feedback.block_reason}")
        return {
            "text": resp.text or "",
            "input_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
            "request_id": getattr(resp, "response_id", None),
        }

    def _raw_embed(self, model, texts, timeout):
        client = self._client(timeout)
        resp = client.models.embed_content(model=model, contents=texts)
        return {"vectors": [[float(x) for x in e.values] for e in resp.embeddings], "request_id": None}

    def _raw_vision(self, model, image_bytes, prompt, timeout):
        from google.genai import types as gt

        client = self._client(timeout)
        resp = client.models.generate_content(
            model=model,
            contents=[gt.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
            config=gt.GenerateContentConfig(max_output_tokens=200, temperature=0),
        )
        um = getattr(resp, "usage_metadata", None)
        return {
            "text": resp.text or "",
            "request_id": getattr(resp, "response_id", None),
            "input_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
        }


def build_hosted_provider(
    provider: str, api_key: str, *, timeout: float = 60.0, http_client: Any | None = None
):
    if provider == "openai":
        return OpenAICompatibleProvider(
            api_key, name="openai", default_timeout=timeout, http_client=http_client
        )
    if provider == "xai":
        return OpenAICompatibleProvider(api_key, name="xai", default_timeout=timeout, http_client=http_client)
    if provider == "anthropic":
        return AnthropicProvider(api_key, default_timeout=timeout, http_client=http_client)
    if provider == "gemini":
        return GeminiProvider(api_key, default_timeout=timeout, http_client=http_client)
    raise CapabilityUnsupported(f"unknown hosted provider {provider}")
