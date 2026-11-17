"""Shared dependencies for the Query API (W1-D)."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request

from bmip.api.errors import ApiProblem
from bmip.api.models import Meta
from bmip.common.config import Settings
from bmip.serving.freshness import clock_for, parse_as_of
from bmip.serving.repository import Page, ServingRepository


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_instance(request: Request) -> str:
    return request.app.state.instance


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def require_api_key(request: Request) -> None:
    """Authenticate /v1/* with a constant-time compare.

    W1-D keeps one service key in the environment. W2-C replaces this with a
    hashed key table plus roles; the dependency signature stays the same so no
    router changes.
    """
    settings: Settings = request.app.state.settings
    if not settings.api_auth_required:
        return
    provided = request.headers.get("X-API-Key", "")
    expected = settings.api_key
    if not expected:
        raise ApiProblem(
            503,
            "api-key-not-configured",
            "API key is not configured",
            "Set BMIP_API_KEY for this deployment before calling /v1 endpoints.",
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise ApiProblem(
            401,
            "unauthorized",
            "Missing or invalid API key",
            "Send a valid X-API-Key header. The dashboard uses a server-side key.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )


def get_repository(request: Request) -> Iterator[ServingRepository]:
    settings: Settings = request.app.state.settings
    repository = ServingRepository(settings)
    try:
        yield repository
    finally:
        repository.close()


def get_lake(request: Request):
    return request.app.state.lake


def get_clock(request: Request) -> tuple[datetime, str]:
    settings: Settings = request.app.state.settings
    return clock_for(parse_as_of(settings.bmip_as_of))


def validate_symbol(symbol: str, settings: Settings) -> str:
    cleaned = (symbol or "").strip().upper()
    if cleaned not in settings.market_symbols:
        raise ApiProblem(
            400,
            "unknown-symbol",
            "Unknown symbol",
            f"Symbol must be one of {list(settings.market_symbols)}; got {symbol!r}.",
        )
    return cleaned


def window(
    start: datetime | None,
    end: datetime | None,
    settings: Settings,
) -> tuple[datetime | None, datetime | None]:
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if start is not None and end is not None:
        if start >= end:
            raise ApiProblem(
                400,
                "invalid-range",
                "Invalid time range",
                "The 'from' parameter must be earlier than 'to'.",
            )
        if end - start > timedelta(days=settings.serving_max_range_days):
            raise ApiProblem(
                400,
                "invalid-range",
                "Invalid time range",
                f"The requested range exceeds {settings.serving_max_range_days} days.",
            )
    return start, end


def page_limit(limit: int | None, settings: Settings) -> int:
    value = settings.serving_page_size_default if limit is None else int(limit)
    if value < 1:
        raise ApiProblem(
            422, "invalid-limit", "Invalid limit", "limit must be at least 1."
        )
    if value > settings.serving_page_size_max:
        raise ApiProblem(
            422,
            "invalid-limit",
            "Invalid limit",
            f"limit must be at most {settings.serving_page_size_max}.",
        )
    return value


def cursor_value(cursor: str | None) -> str | None:
    return cursor or None


def build_meta(
    request: Request,
    *,
    source: str,
    stale: bool,
    freshness: dict[str, Any] | None = None,
    count: int | None = None,
    next_cursor: str | None = None,
) -> Meta:
    now, clock = get_clock(request)
    return Meta(
        request_id=get_request_id(request),
        instance=get_instance(request),
        source=source,  # type: ignore[arg-type]
        stale=stale,
        clock=clock,  # type: ignore[arg-type]
        as_of=now,
        count=count,
        next_cursor=next_cursor,
        freshness=freshness,  # type: ignore[arg-type]
    )


def freshness_payload(
    stored: dict[str, Any] | None,
    *,
    now: datetime,
    clock: str,
) -> dict[str, Any] | None:
    """Recompute age at request time so a badge never freezes between loads."""
    if not stored:
        return None
    from bmip.serving.freshness import compute

    return compute(
        str(stored["metric"]),
        stored.get("data_ts"),
        int(stored["slo_seconds"]),
        now=now,
        clock=clock,
    ).as_dict()


def page_meta(page: Page, request: Request, *, source: str, stale: bool) -> Meta:
    return build_meta(
        request,
        source=source,
        stale=stale,
        count=len(page.rows),
        next_cursor=page.next_cursor,
    )
