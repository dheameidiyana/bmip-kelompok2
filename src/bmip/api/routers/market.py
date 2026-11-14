"""Market endpoints (W1-D): latest, OHLC range, volatility."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from bmip.api.deps import (
    build_meta,
    freshness_payload,
    get_clock,
    get_lake,
    get_repository,
    get_settings,
    page_limit,
    validate_symbol,
    window,
)
from bmip.api.errors import ApiProblem
from bmip.api.lake import LakeUnavailable
from bmip.api.models import (
    DEFAULT_SYMBOL,
    MarketBar,
    MarketBarPage,
    MarketLatestOut,
    VolatilityLatestOut,
    VolatilityPage,
)
from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.serving.repository import Page, ServingRepository, decode_cursor, encode_cursor

log = get_logger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


@router.get(
    "/latest",
    response_model=MarketLatestOut,
    summary="Latest hourly bar and volatility for a symbol",
)
def market_latest(
    request: Request,
    response: Response,
    symbol: str = Query(DEFAULT_SYMBOL, description="Trading pair, allowlisted"),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> MarketLatestOut:
    symbol = validate_symbol(symbol, settings)
    row = repository.market_latest(symbol)
    now, clock = get_clock(request)
    fresh = freshness_payload(
        repository.freshness_one("market"), now=now, clock=clock
    )
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return MarketLatestOut(
        data=MarketBar.model_validate(row) if row else None,
        meta=build_meta(request, source="serving", stale=False, freshness=fresh),
    )


@router.get(
    "/ohlc",
    response_model=MarketBarPage,
    summary="Hourly OHLC range (DuckDB over Iceberg, PostgreSQL fallback)",
)
def market_ohlc(
    request: Request,
    response: Response,
    symbol: str = Query(DEFAULT_SYMBOL, description="Trading pair, allowlisted"),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int | None = Query(None, description="Page size, max 1000"),
    cursor: str | None = Query(None, description="Opaque keyset cursor"),
    repository: ServingRepository = Depends(get_repository),
    lake=Depends(get_lake),
    settings: Settings = Depends(get_settings),
) -> MarketBarPage:
    symbol = validate_symbol(symbol, settings)
    start, end = window(start, end, settings)
    size = page_limit(limit, settings)
    end = _apply_cursor(end, cursor)

    page, source, stale = _market_range(lake, repository, symbol, start, end, size, request)
    now, clock = get_clock(request)
    fresh = freshness_payload(
        repository.freshness_one("market"), now=now, clock=clock
    )
    response.headers["X-Data-Source"] = source
    response.headers["X-Data-Stale"] = "true" if stale else "false"
    return MarketBarPage(
        data=[MarketBar.model_validate(row) for row in page.rows],
        meta=build_meta(
            request,
            source=source,
            stale=stale,
            freshness=fresh,
            count=len(page.rows),
            next_cursor=page.next_cursor,
        ),
    )


router.add_api_route(
    "/ohlcv",
    market_ohlc,
    methods=["GET"],
    response_model=MarketBarPage,
    name="market_ohlcv_alias",
    summary="Alias of /v1/market/ohlc (ARCHITECTURE naming)",
    include_in_schema=True,
)


@router.get(
    "/volatility/latest",
    response_model=VolatilityLatestOut,
    summary="Latest realized and EWMA volatility",
)
def volatility_latest(
    request: Request,
    response: Response,
    symbol: str = Query(DEFAULT_SYMBOL),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> VolatilityLatestOut:
    symbol = validate_symbol(symbol, settings)
    row = repository.volatility_latest(symbol)
    now, clock = get_clock(request)
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return VolatilityLatestOut(
        data=_volatility(row),
        meta=build_meta(
            request,
            source="serving",
            stale=False,
            freshness=freshness_payload(
                repository.freshness_one("market"), now=now, clock=clock
            ),
        ),
    )


@router.get(
    "/volatility/range",
    response_model=VolatilityPage,
    summary="Realized volatility range",
)
def volatility_range(
    request: Request,
    response: Response,
    symbol: str = Query(DEFAULT_SYMBOL),
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int | None = Query(None),
    cursor: str | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    lake=Depends(get_lake),
    settings: Settings = Depends(get_settings),
) -> VolatilityPage:
    symbol = validate_symbol(symbol, settings)
    start, end = window(start, end, settings)
    size = page_limit(limit, settings)
    end = _apply_cursor(end, cursor)
    page, source, stale = _market_range(lake, repository, symbol, start, end, size, request)
    now, clock = get_clock(request)
    response.headers["X-Data-Source"] = source
    response.headers["X-Data-Stale"] = "true" if stale else "false"
    return VolatilityPage(
        data=[_volatility(row) for row in page.rows],
        meta=build_meta(
            request,
            source=source,
            stale=stale,
            freshness=freshness_payload(
                repository.freshness_one("market"), now=now, clock=clock
            ),
            count=len(page.rows),
            next_cursor=page.next_cursor,
        ),
    )


router.add_api_route(
    "/volatility",
    volatility_range,
    methods=["GET"],
    response_model=VolatilityPage,
    name="market_volatility_alias",
    summary="Alias of /v1/market/volatility/range (ARCHITECTURE naming)",
    include_in_schema=True,
)


def _market_range(
    lake: Any,
    repository: ServingRepository,
    symbol: str,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    request: Request,
) -> tuple[Page, str, bool]:
    """Lake first, PostgreSQL second, with an explicit stale marker."""
    try:
        rows = lake.market_range(symbol, start, end, limit + 1)
        return _trim(rows, limit), "lake", False
    except LakeUnavailable as exc:
        log.warning(
            "market range falling back to serving",
            extra={"ctx_reason": f"{type(exc).__name__}: {exc}", "ctx_symbol": symbol},
        )
        request.app.state.metrics["fallbacks"] += 1
        page = repository.market_hourly(
            symbol, start=start, end=end, limit=limit, cursor=None
        )
        return page, "serving", True


def _trim(rows: list[dict[str, Any]], limit: int) -> Page:
    if len(rows) > limit:
        rows = rows[:limit]
        return Page(rows=rows, next_cursor=encode_cursor(rows[-1]["window_start"]))
    return Page(rows=rows)


def _apply_cursor(end: datetime | None, cursor: str | None) -> datetime | None:
    if not cursor:
        return end
    try:
        boundary = decode_cursor(cursor)
    except ValueError as exc:
        raise ApiProblem(
            400,
            "invalid-cursor",
            "Invalid cursor",
            "Pass a cursor returned by a previous page of the same endpoint.",
        ) from exc
    if end is None or boundary < end:
        return boundary
    return end


def _volatility(row: dict[str, Any] | None):
    if row is None:
        return None
    from bmip.api.models import VolatilityPoint

    return VolatilityPoint.model_validate(row)
