"""HTTP client for the catalogue portal (W2-C).

The portal follows the same rule as the dashboard: it reads the Query API and
never opens PostgreSQL or Iceberg directly.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from bmip.dashboard.client import ApiError

DEFAULT_BASE_URL = "http://localhost:8000"


class CatalogClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("BMIP_API_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("BMIP_API_KEY", "")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        cleaned = {
            key: value for key, value in (params or {}).items() if value is not None
        }
        try:
            response = httpx.get(
                f"{self.base_url}{path}",
                params=cleaned,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ApiError(0, None, f"Cannot reach the API at {self.base_url}: {exc}") from exc
        return self._decode(response)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload or {},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            raise ApiError(0, None, f"Cannot reach the API at {self.base_url}: {exc}") from exc
        return self._decode(response)

    def _decode(self, response: httpx.Response) -> dict[str, Any]:
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

    def whoami(self) -> dict[str, Any]:
        return self.get("/v1/auth/whoami")

    def datasets(
        self,
        *,
        query: str | None = None,
        domain: str | None = None,
        layer: str | None = None,
        owner: str | None = None,
        classification: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self.get(
            "/v1/dataset",
            {
                "q": query,
                "domain": domain,
                "layer": layer,
                "owner": owner,
                "classification": classification,
                "limit": limit,
            },
        )

    def dataset(self, dataset_id: str) -> dict[str, Any]:
        return self.get(f"/v1/dataset/{dataset_id}")

    def schema(self, dataset_id: str) -> dict[str, Any]:
        return self.get(f"/v1/dataset/{dataset_id}/schema")

    def lineage(self, dataset_id: str) -> dict[str, Any]:
        return self.get(f"/v1/lineage/{dataset_id}")

    def quality(self) -> dict[str, Any]:
        return self.get("/v1/quality/status")

    def freshness(self) -> dict[str, Any]:
        return self.get("/v1/freshness")

    def reload_catalog(self) -> dict[str, Any]:
        return self.post("/v1/admin/catalog/reload")

    def queue_backfill(self, start: str, end: str) -> dict[str, Any]:
        return self.post(
            "/v1/admin/backfill",
            {"start": start, "end": end},
        )
