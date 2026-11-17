"""Thin HTTP client for the BMIP Query API (W1-D).

The dashboard never opens PostgreSQL or Iceberg directly: authorisation,
caching, fallback, and refresh policy live in one place behind the API.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"


class ApiError(RuntimeError):
    def __init__(self, status: int, problem: dict[str, Any] | None, detail: str = ""):
        self.status = status
        self.problem = problem or {}
        message = (
            self.problem.get("detail")
            or self.problem.get("title")
            or detail
            or f"HTTP {status}"
        )
        super().__init__(message)


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("BMIP_API_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.api_key = api_key if api_key is not None else os.getenv("BMIP_API_KEY", "")
        self.timeout = timeout

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        cleaned = {key: value for key, value in (params or {}).items() if value is not None}
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                params=cleaned,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ApiError(0, None, f"Cannot reach the API at {self.base_url}: {exc}") from exc
        if response.status_code >= 400:
            problem = None
            if response.headers.get("content-type", "").startswith(
                "application/problem+json"
            ):
                try:
                    problem = response.json()
                except ValueError:
                    problem = None
            raise ApiError(response.status_code, problem, response.text[:300])
        return response.json()

    def meta_instance(self) -> dict[str, Any]:
        return self.get("/v1/meta/instance")

    def market_latest(self, symbol: str) -> dict[str, Any]:
        return self.get("/v1/market/latest", {"symbol": symbol})

    def market_ohlc(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.get(
            "/v1/market/ohlc",
            {"symbol": symbol, "from": start, "to": end, "limit": limit},
        )

    def volatility_range(
        self,
        symbol: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.get(
            "/v1/market/volatility/range",
            {"symbol": symbol, "from": start, "to": end, "limit": limit},
        )

    def sentiment_latest(self) -> dict[str, Any]:
        return self.get("/v1/sentiment/latest")

    def sentiment_hourly(
        self,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return self.get(
            "/v1/sentiment/hourly",
            {"from": start, "to": end, "limit": limit},
        )

    def freshness(self) -> dict[str, Any]:
        return self.get("/v1/freshness")

    def model_latest(self) -> dict[str, Any]:
        return self.get("/v1/model/latest")

    def quality_status(self) -> dict[str, Any]:
        return self.get("/v1/quality/status")

    def datasets(self, query: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self.get("/v1/dataset", {"q": query, "limit": limit})
