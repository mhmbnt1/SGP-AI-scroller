# API + worker image (same code, different command). Non-root, no browser, no media tools by default.
FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/protocol ./packages/protocol
COPY services/api ./services/api
COPY services/worker ./services/worker
COPY services/collector/pyproject.toml ./services/collector/pyproject.toml
RUN mkdir -p services/collector/focusfeed_collector && touch services/collector/focusfeed_collector/__init__.py \
 && uv sync --frozen --no-dev --package focusfeed-api --package focusfeed-worker
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --create-home --uid 10001 focusfeed && chown -R focusfeed:focusfeed /app
USER focusfeed
WORKDIR /app/services/api
EXPOSE 8000
CMD ["uvicorn", "focusfeed_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
