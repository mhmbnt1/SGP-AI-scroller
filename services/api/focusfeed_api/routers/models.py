"""Administrator-approved model choices with live health/capability discovery."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter

from focusfeed_api.auth.deps import AppSettings, CurrentUser
from focusfeed_api.providers import get_provider
from focusfeed_api.providers.resources import measure
from focusfeed_api.schemas import ModelOptionOut, ModelsOut
from focusfeed_api.services.capabilities import list_capabilities

router = APIRouter(tags=["models"])


@router.get("/models", response_model=ModelsOut)
def models(_: CurrentUser, settings: AppSettings) -> ModelsOut:
    provider = get_provider(settings)
    health = provider.health()
    discovered = {m.name: m for m in health.models}
    options: list[ModelOptionOut] = []
    if provider.name == "fake":
        approved = {"text": ["fake-text"], "embedding": ["fake-embed"], "vision": []}
        defaults = {"text": "fake-text", "embedding": "fake-embed"}
    else:
        approved = {
            "text": settings.text_models,
            "embedding": settings.embedding_models,
            "vision": settings.vision_models,
        }
        defaults = {"text": settings.ff_default_text_model, "embedding": settings.ff_default_embedding_model}
    for purpose, names in approved.items():
        for name in names:
            info = discovered.get(name)
            caps = {}
            if info is not None:
                caps = {
                    "json_output": info.json_output,
                    "vision": info.vision,
                    "embeddings": info.embeddings,
                    "context_window": info.context_window,
                    "embedding_dimensions": info.embedding_dimensions,
                    "parameter_size": info.parameter_size,
                }
            options.append(
                ModelOptionOut(
                    name=name,
                    purpose=cast(Literal["text", "embedding", "vision"], purpose),
                    available=info is not None,
                    is_default=(defaults.get(purpose) == name),
                    capabilities=caps,
                )
            )  # type: ignore[arg-type]
    res = measure()
    return ModelsOut(
        provider=provider.name,
        provider_healthy=health.healthy,
        provider_detail=health.detail,
        options=options,
        resource_note=res.note,
    )


@router.get("/capabilities")
def capabilities(_: CurrentUser) -> list[dict]:
    return list_capabilities()
