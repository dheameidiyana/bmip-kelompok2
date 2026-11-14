"""Model metadata endpoint (W1-D).

Training and the registry belong to W2-A. This endpoint exists so the
dashboard can say "belum ada model" explicitly instead of rendering a fake
prediction.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response

from bmip.api.deps import build_meta, get_repository
from bmip.api.models import ModelOut
from bmip.serving.repository import ServingRepository

router = APIRouter(tags=["model"])

NO_MODEL_DETAIL = (
    "No champion model is registered yet. Training, the MLflow registry, and "
    "the promotion gate are W2-A scope; until then the platform reports this "
    "state instead of a synthetic prediction."
)


@router.get(
    "/model/latest",
    response_model=ModelOut,
    summary="Champion model metadata, or an explicit not_available state",
)
def model_latest(
    request: Request,
    response: Response,
    name: str = Query("volatility_model", description="Registered model name"),
    repository: ServingRepository = Depends(get_repository),
) -> ModelOut:
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    meta = build_meta(request, source="serving", stale=False)
    row = repository.model_latest(name)
    if row is None:
        return ModelOut(
            status="not_available",
            model_name=name,
            detail=NO_MODEL_DETAIL,
            meta=meta,
        )
    return ModelOut(
        status="available",
        model_name=str(row["model_name"]),
        version=str(row["version"]),
        alias=row.get("alias"),
        metrics=dict(row.get("metrics") or {}),
        meta=meta,
    )
