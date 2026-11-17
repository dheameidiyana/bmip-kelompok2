"""Freshness endpoint (W1-D)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from bmip.api.deps import build_meta, freshness_payload, get_clock, get_repository
from bmip.api.models import FreshnessListOut, FreshnessOut
from bmip.serving.repository import ServingRepository

router = APIRouter(tags=["freshness"])


@router.get(
    "/freshness",
    response_model=FreshnessListOut,
    summary="Age of every serving metric against its SLO",
)
def freshness(
    request: Request,
    response: Response,
    repository: ServingRepository = Depends(get_repository),
) -> FreshnessListOut:
    rows = repository.freshness()
    now, clock = get_clock(request)
    data = [
        FreshnessOut.model_validate(freshness_payload(row, now=now, clock=clock))
        for row in rows
        if row
    ]
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return FreshnessListOut(
        data=data,
        meta=build_meta(request, source="serving", stale=False, count=len(data)),
    )
