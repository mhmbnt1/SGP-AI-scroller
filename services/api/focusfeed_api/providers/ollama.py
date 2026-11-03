"""Ollama provider (local inference, default for live mode).

* Discovers models via ``/api/tags`` and their capabilities via ``/api/show``
  (Ollama >= 0.6 reports ``capabilities`` such as ``completion``, ``vision``,
  ``embedding``). Older servers fall back to name heuristics and a one-shot
  structured-output probe.
* Structured output uses the ``format`` field with a JSON schema (Ollama >= 0.5).
* ``OLLAMA_BASE_URL`` is administrator configuration — never user input — and
  is the one privileged localhost path; it bypasses the SSRF guard on purpose.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from focusfeed_api.providers.base import (
    CancelToken,
    GenerationResult,
    InvalidOutput,
    ModelInfo,
    ProviderHealth,
    ProviderTimeout,
    ProviderUnavailable,
)

_VISION_HINTS = ("llava", "vision", "moondream", "minicpm-v", "bakllava", "gemma3", "qwen2.5vl", "qwen3-vl")
_EMBED_HINTS = ("embed", "bge", "minilm", "e5")


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, *, default_timeout: float = 180.0, num_ctx: int = 8192) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_timeout = default_timeout
        self.num_ctx = num_ctx
        self._model_cache: dict[str, ModelInfo] = {}

    # ------------------------------------------------------------------ discovery

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=httpx.Timeout(timeout, connect=5.0))

    def health(self) -> ProviderHealth:
        try:
            with self._client(10.0) as client:
                resp = client.get("/api/tags")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return ProviderHealth(healthy=False, detail=f"Ollama not reachable at {self.base_url}: {type(exc).__name__}")
        models: list[ModelInfo] = []
        for m in data.get("models", []):
            name = m.get("name") or m.get("model")
            if not name:
                continue
            models.append(self.describe_model(name, details=m.get("details") or {}))
        return ProviderHealth(healthy=True, detail=f"{len(models)} model(s) installed", models=models)

    def describe_model(self, name: str, details: dict[str, Any] | None = None) -> ModelInfo:
        if name in self._model_cache:
            return self._model_cache[name]
        info = ModelInfo(name=name, parameter_size=(details or {}).get("parameter_size"))
        caps: list[str] = []
        try:
            with self._client(10.0) as client:
                resp = client.post("/api/show", json={"model": name})
                if resp.status_code == 200:
                    body = resp.json()
                    caps = [str(c) for c in body.get("capabilities", [])]
                    mi = body.get("model_info") or {}
                    for k, v in mi.items():
                        if k.endswith(".context_length") and isinstance(v, int):
                            info.context_window = v
                        if k.endswith(".embedding_length") and isinstance(v, int):
                            info.embedding_dimensions = v
        except httpx.HTTPError:
            pass
        lowered = name.lower()
        info.vision = "vision" in caps or any(h in lowered for h in _VISION_HINTS)
        info.embeddings = "embedding" in caps or any(h in lowered for h in _EMBED_HINTS)
        info.json_output = ("completion" in caps) or (not caps and not info.embeddings)
        if info.embeddings:
            info.purposes.add("embedding")
        if info.json_output:
            info.purposes.add("text")
        if info.vision:
            info.purposes.add("vision")
        self._model_cache[name] = info
        return info

    def supports_vision(self, model: str) -> bool:
        return self.describe_model(model).vision

    # ------------------------------------------------------------------ generation

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
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": max_output_tokens},
            "keep_alive": "10m",
        }
        start = time.perf_counter()
        try:
            with self._client(timeout_seconds or self.default_timeout) as client:
                resp = client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"Ollama call exceeded {timeout_seconds}s") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Ollama not reachable: {type(exc).__name__}") from exc
        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code == 404:
            raise ProviderUnavailable(f"model '{model}' is not installed (ollama pull {model})")
        if resp.status_code >= 500:
            raise ProviderUnavailable(f"Ollama server error {resp.status_code}")
        if resp.status_code >= 400:
            raise InvalidOutput(f"Ollama rejected the request ({resp.status_code})")
        body = resp.json()
        text = (body.get("message") or {}).get("content", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidOutput("model output was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise InvalidOutput("model output was not a JSON object")
        return GenerationResult(
            parsed=parsed, raw_text=text, input_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"), latency_ms=latency, model=model,
        )

    def embed(self, *, model: str, texts: list[str], timeout_seconds: float) -> list[list[float]]:
        try:
            with self._client(timeout_seconds or self.default_timeout) as client:
                resp = client.post("/api/embed", json={"model": model, "input": texts})
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("embedding call timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Ollama not reachable: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise ProviderUnavailable(f"embedding model '{model}' is not installed")
        if resp.status_code >= 400:
            raise ProviderUnavailable(f"embedding request failed ({resp.status_code})")
        data = resp.json()
        vectors = data.get("embeddings") or []
        if len(vectors) != len(texts):
            raise InvalidOutput("embedding count mismatch")
        return [[float(x) for x in v] for v in vectors]

    def describe_image(self, *, model: str, image_bytes: bytes, prompt: str, timeout_seconds: float) -> str:
        import base64

        if not self.supports_vision(model):
            raise ProviderUnavailable(f"model '{model}' does not support images")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image_bytes).decode()]}],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 200},
        }
        try:
            with self._client(timeout_seconds or self.default_timeout) as client:
                resp = client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout("vision call timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Ollama not reachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise ProviderUnavailable(f"vision request failed ({resp.status_code})")
        return str((resp.json().get("message") or {}).get("content", ""))[:1000]
