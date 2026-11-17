"""Sentiment endpoints (W1-D)."""

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
    window,
)
from bmip.api.errors import ApiProblem
from bmip.api.lake import LakeUnavailable
from bmip.api.models import SentimentHour, SentimentLatestOut, SentimentPage
from bmip.api.routers.market import _apply_cursor, _trim
from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.serving.repository import Page, ServingRepository

log = get_logger(__name__)
router = APIRouter(prefix="/sentiment", tags=["sentiment"])


@router.get(
    "/latest",
    response_model=SentimentLatestOut,
    summary="Latest hourly sentiment aggregate",
)
def sentiment_latest(
    request: Request,
    response: Response,
    repository: ServingRepository = Depends(get_repository),
) -> SentimentLatestOut:
    row = repository.sentiment_latest()
    now, clock = get_clock(request)
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return SentimentLatestOut(
        data=SentimentHour.model_validate(row) if row else None,
        meta=build_meta(
            request,
            source="serving",
            stale=False,
            freshness=freshness_payload(
                repository.freshness_one("sentiment"), now=now, clock=clock
            ),
        ),
    )


@router.get(
    "/hourly",
    response_model=SentimentPage,
    summary="Hourly sentiment series (defaults to the most recent page)",
)
def sentiment_hourly(
    request: Request,
    response: Response,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int | None = Query(None),
    cursor: str | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    lake=Depends(get_lake),
    settings: Settings = Depends(get_settings),
) -> SentimentPage:
    return _range(
        request,
        response,
        repository,
        lake,
        settings,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/range",
    response_model=SentimentPage,
    summary="Hourly sentiment range with explicit from/to",
)
def sentiment_range(
    request: Request,
    response: Response,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    limit: int | None = Query(None),
    cursor: str | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    lake=Depends(get_lake),
    settings: Settings = Depends(get_settings),
) -> SentimentPage:
    if start is None or end is None:
        raise ApiProblem(
            400,
            "missing-range",
            "Missing time range",
            "The /v1/sentiment/range endpoint requires both 'from' and 'to'.",
        )
    return _range(
        request,
        response,
        repository,
        lake,
        settings,
        start=start,
        end=end,
        limit=limit,
        cursor=cursor,
    )


router.add_api_route(
    "/timeseries",
    sentiment_hourly,
    methods=["GET"],
    response_model=SentimentPage,
    name="sentiment_timeseries_alias",
    summary="Alias of /v1/sentiment/hourly (ARCHITECTURE naming)",
    include_in_schema=True,
)


def _range(
    request: Request,
    response: Response,
    repository: ServingRepository,
    lake: Any,
    settings: Settings,
    *,
    start: datetime | None,
    end: datetime | None,
    limit: int | None,
    cursor: str | None,
) -> SentimentPage:
    start, end = window(start, end, settings)
    size = page_limit(limit, settings)
    end = _apply_cursor(end, cursor)
    page, source, stale = _sentiment_range(
        lake, repository, start, end, size, request
    )
    now, clock = get_clock(request)
    response.headers["X-Data-Source"] = source
    response.headers["X-Data-Stale"] = "true" if stale else "false"
    return SentimentPage(
        data=[SentimentHour.model_validate(row) for row in page.rows],
        meta=build_meta(
            request,
            source=source,
            stale=stale,
            freshness=freshness_payload(
                repository.freshness_one("sentiment"), now=now, clock=clock
            ),
            count=len(page.rows),
            next_cursor=page.next_cursor,
        ),
    )


def _sentiment_range(
    lake: Any,
    repository: ServingRepository,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    request: Request,
) -> tuple[Page, str, bool]:
    try:
        rows = lake.sentiment_range(start, end, limit + 1)
        return _trim(rows, limit), "lake", False
    except LakeUnavailable as exc:
        log.warning(
            "sentiment range falling back to serving",
            extra={"ctx_reason": f"{type(exc).__name__}: {exc}"},
        )
        request.app.state.metrics["fallbacks"] += 1
        page = repository.sentiment_range(
            start=start, end=end, limit=limit, cursor=None
        )
        return page, "serving", True
