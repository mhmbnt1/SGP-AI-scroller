"""FastAPI application factory."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from focusfeed_api import __version__
from focusfeed_api.config import Settings, get_settings
from focusfeed_api.errors import install_error_handlers
from focusfeed_api.middleware import RequestContextMiddleware, configure_logging
from focusfeed_api.routers import auth, batches, collector_jobs, collectors, health, items, jobs, me, models, platforms, preferences, privacy, saved, schedules, search


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(json_output=settings.is_production)
    app = FastAPI(
        title="FocusFeed API",
        version=__version__,
        description="Bounded, evidence-grounded curation of personalized social feeds.",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
        max_age=600,
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    for r in (auth.router, me.router, preferences.router, platforms.router, collectors.router, collector_jobs.router, jobs.router,
              batches.router, search.router, items.router, saved.router, schedules.router, models.router, privacy.router, health.router):
        v1.include_router(r)
    app.include_router(v1)
    return app


app = create_app()
