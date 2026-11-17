"""RFC 7807 problem documents for the Query API (W1-D)."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

PROBLEM_BASE = "https://bmip.local/problems"
PROBLEM_MEDIA_TYPE = "application/problem+json"


class ApiProblem(Exception):
    """An error the API is allowed to show the client."""

    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(
    request: Request,
    *,
    status: int,
    slug: str,
    title: str,
    detail: str,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or "unknown"
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE}/{slug}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id,
    }
    if extra:
        body.update(extra)
    response_headers = {"X-Request-ID": request_id, **(headers or {})}
    return JSONResponse(
        status_code=status,
        content=body,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=response_headers,
    )
