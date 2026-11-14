"""Data-quality status endpoint (W1-D)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from bmip.api.deps import build_meta, get_repository
from bmip.api.models import QualityOut
from bmip.serving.repository import ServingRepository

router = APIRouter(tags=["quality"])


@router.get(
    "/quality/status",
    response_model=QualityOut,
    summary="Last Great Expectations run and its failures",
)
def quality_status(
    request: Request,
    response: Response,
    repository: ServingRepository = Depends(get_repository),
) -> QualityOut:
    data = repository.quality_status()
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return QualityOut(
        data=data,
        meta=build_meta(request, source="serving", stale=False, count=len(data)),
    )


@router.get(
    "/dq/results",
    response_model=QualityOut,
    summary="Alias of /v1/quality/status (ARCHITECTURE naming)",
    include_in_schema=True,
)
def dq_results(
    request: Request,
    response: Response,
    repository: ServingRepository = Depends(get_repository),
    scope: str | None = Query(None, description="Reserved: filter by silver/gold"),
) -> QualityOut:
    return quality_status(request, response, repository)
