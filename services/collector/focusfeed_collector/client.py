"""Outbound-only HTTP client for the collector protocol. No inbound ports, no debugging endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from ff_protocol import CollectorJobInstruction, CollectorJobResult

from focusfeed_collector import __version__


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code


@dataclass
class ApiClient:
    base_url: str
    credential: str | None = None
    timeout: float = 30.0

    def _headers(self) -> dict[str, str]:
        h = {"User-Agent": f"focusfeed-collector/{__version__}"}
        if self.credential:
            h["Authorization"] = f"Device {self.credential}"
        return h

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout, headers=self._headers()) as client:
            resp = client.request(method, path, **kw)
        if resp.status_code >= 400:
            try:
                err = resp.json().get("error", {})
            except ValueError:
                err = {}
            raise ApiError(
                resp.status_code, err.get("code", "http_error"), err.get("message", resp.text[:200])
            )
        return resp

    def exchange_enrollment(self, code: str, os_name: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/collectors/enrollments/exchange",
            json={"code": code, "os_name": os_name, "collector_version": __version__},
        ).json()

    def heartbeat(
        self, platform_status: dict[str, str], capabilities: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/collectors/heartbeat",
            json={
                "collector_version": __version__,
                "platform_status": platform_status,
                "capabilities": capabilities,
            },
        ).json()

    def claim(self, platforms: list[str]) -> CollectorJobInstruction | None:
        resp = self._request("POST", "/api/v1/collector/jobs/claim", json={"platforms": platforms})
        if resp.status_code == 204 or not resp.content:
            return None
        return CollectorJobInstruction.model_validate(resp.json())

    def renew_lease(self, job_id: str, lease_token: str) -> dict[str, Any]:
        return self._request(
            "POST", f"/api/v1/collector/jobs/{job_id}/lease", json={"lease_token": lease_token}
        ).json()

    def event(
        self,
        job_id: str,
        lease_token: str,
        kind: str,
        message: str = "",
        platform: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._request(
            "POST",
            f"/api/v1/collector/jobs/{job_id}/events",
            json={
                "lease_token": lease_token,
                "kind": kind,
                "message": message[:500],
                "platform": platform,
                "data": data or {},
            },
        )

    def submit_results(self, result: CollectorJobResult) -> dict[str, Any]:
        return self._request(
            "POST", f"/api/v1/collector/jobs/{result.job_id}/results", json=result.model_dump(mode="json")
        ).json()

    def health(self) -> bool:
        try:
            return self._request("GET", "/api/v1/health/live").status_code == 200
        except (httpx.HTTPError, ApiError):
            return False
