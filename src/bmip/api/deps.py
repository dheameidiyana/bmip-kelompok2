"""Shared dependencies for the Query API (W1-D, RBAC in W2-C)."""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request

from bmip.api.errors import ApiProblem
from bmip.api.keys import ROLE_ORDER, parse_key, resolve_key
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
    """Authenticate /v1/* and attach the resolved identity to the request.

    W2-C resolves three roles from ``ops.api_keys``. The single W1-D key in
    ``BMIP_API_KEY`` keeps working as ``viewer`` so existing scripts and the
    dashboard do not need a new secret; operator and admin actions need a key
    seeded by ``scripts/w2c_seed_keys.py``.
    """
    settings: Settings = request.app.state.settings
    request.state.actor = "anonymous"
    request.state.role = "anonymous"
    if not settings.api_auth_required:
        request.state.actor = "auth-disabled"
        request.state.role = "admin"
        return
    provided = request.headers.get("X-API-Key", "")
    if settings.api_key and provided and secrets.compare_digest(provided, settings.api_key):
        request.state.actor = "legacy-key"
        request.state.role = "viewer"
        return
    if provided and parse_key(provided):
        identity = _resolve(settings, provided)
        if identity is not None:
            request.state.actor = identity.owner
            request.state.role = identity.role
            request.state.key_id = identity.key_id
            return
    raise ApiProblem(
        401,
        "unauthorized",
        "Missing or invalid API key",
        "Send a valid X-API-Key header. The dashboard uses a server-side key.",
        headers={"WWW-Authenticate": "X-API-Key"},
    )


def _resolve(settings: Settings, provided: str):
    try:
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(
            settings.postgres_dsn, connect_timeout=2, row_factory=dict_row
        ) as connection:
            return resolve_key(connection, provided, salt=settings.api_key_salt)
    except Exception:  # noqa: BLE001 - an unavailable key table means 401
        return None


def require_role(minimum: str):
    """Dependency factory enforcing viewer < operator < admin."""
    needed = ROLE_ORDER[minimum]

    def dependency(request: Request) -> None:
        role = getattr(request.state, "role", "anonymous")
        if ROLE_ORDER.get(role, -1) < needed:
            raise ApiProblem(
                403,
                "forbidden",
                "Insufficient role",
                f"This action needs the {minimum} role; the caller has {role}.",
            )

    return dependency


def get_actor(request: Request) -> str:
    return getattr(request.state, "actor", "anonymous")


def get_role(request: Request) -> str:
    return getattr(request.state, "role", "anonymous")


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
