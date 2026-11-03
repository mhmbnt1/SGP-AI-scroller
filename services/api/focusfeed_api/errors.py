"""Consistent error envelope: {"error": {"code", "message", "request_id", "details"?}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str = "", *, code: str | None = None, status_code: int | None = None,
                 details: Any | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message or self.__class__.__doc__ or "Request failed"
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        self.retryable = retryable


class NotFound(AppError):
    """The requested resource does not exist or you do not have access to it."""

    status_code = 404
    code = "not_found"


class Forbidden(AppError):
    """You are not allowed to perform this action."""

    status_code = 403
    code = "forbidden"


class Unauthorized(AppError):
    """Authentication required."""

    status_code = 401
    code = "unauthorized"


class Conflict(AppError):
    """The request conflicts with the current state."""

    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    """Too many requests. Please wait and retry."""

    status_code = 429
    code = "rate_limited"


class ValidationFailed(AppError):
    """The request was well-formed but semantically invalid."""

    status_code = 422
    code = "validation_failed"


class ServiceUnavailable(AppError):
    """A required dependency is unavailable."""

    status_code = 503
    code = "service_unavailable"


def _envelope(request: Request, code: str, message: str, status: int, details: Any = None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body: dict[str, Any] = {"error": {"code": code, "message": message, "request_id": request_id}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        resp = _envelope(request, exc.code, exc.message, exc.status_code, exc.details)
        if exc.retryable:
            resp.headers["Retry-After"] = "5"
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
            for e in exc.errors()[:20]
        ]
        return _envelope(request, "validation_error", "Request validation failed.", 422, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 429: "rate_limited"}.get(
            exc.status_code, "http_error"
        )
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _envelope(request, code, message, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        # Never leak stack traces or exception text to clients.
        return _envelope(request, "internal_error", "An unexpected error occurred.", 500)
