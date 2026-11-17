"""Dataset catalogue endpoints (W1-D)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from bmip.api.deps import (
    build_meta,
    get_repository,
    get_settings,
    page_limit,
)
from bmip.api.errors import ApiProblem
from bmip.api.models import ColumnOut, DatasetOut, DatasetPage, DatasetSchemaOut
from bmip.common.config import Settings
from bmip.serving.registry import iceberg_columns, postgres_columns
from bmip.serving.repository import ServingRepository

router = APIRouter(prefix="/dataset", tags=["catalog"])
catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("", response_model=DatasetPage, summary="List catalogue datasets")
def list_datasets(
    request: Request,
    response: Response,
    q: str | None = Query(None, description="Search name, id, description, owner, tags"),
    domain: str | None = Query(None),
    layer: str | None = Query(None),
    owner: str | None = Query(None),
    limit: int | None = Query(None),
    cursor: str | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> DatasetPage:
    size = page_limit(limit, settings)
    page = repository.datasets(
        q=q,
        domain=domain,
        layer=layer,
        owner=owner,
        limit=size,
        cursor=cursor,
    )
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return DatasetPage(
        data=[DatasetOut.model_validate(row) for row in page.rows],
        meta=build_meta(
            request,
            source="serving",
            stale=False,
            count=len(page.rows),
            next_cursor=page.next_cursor,
        ),
    )


@router.get(
    "/{dataset_id}/schema",
    response_model=DatasetSchemaOut,
    summary="Columns of one dataset, from Iceberg or PostgreSQL",
)
def dataset_schema(
    request: Request,
    response: Response,
    dataset_id: str,
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> DatasetSchemaOut:
    row = repository.dataset(dataset_id)
    if row is None:
        raise ApiProblem(
            404,
            "dataset-not-found",
            "Dataset not found",
            f"No dataset with id {dataset_id!r} is registered.",
        )
    columns, source = _columns(repository, settings, row)
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"
    return DatasetSchemaOut(
        dataset=DatasetOut.model_validate(row),
        columns=[ColumnOut.model_validate(column) for column in columns],
        schema_source=source,
        meta=build_meta(request, source="serving", stale=False, count=len(columns)),
    )


@catalog_router.get(
    "/search",
    response_model=DatasetPage,
    summary="Alias of /v1/dataset (ARCHITECTURE naming)",
)
def catalog_search(
    request: Request,
    response: Response,
    q: str | None = Query(None),
    domain: str | None = Query(None),
    layer: str | None = Query(None),
    owner: str | None = Query(None),
    limit: int | None = Query(None),
    cursor: str | None = Query(None),
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> DatasetPage:
    return list_datasets(
        request,
        response,
        q=q,
        domain=domain,
        layer=layer,
        owner=owner,
        limit=limit,
        cursor=cursor,
        repository=repository,
        settings=settings,
    )


def _columns(
    repository: ServingRepository, settings: Settings, row: dict[str, Any]
) -> tuple[list[dict[str, Any]], str]:
    stored = row.get("schema_json")
    if stored:
        return list(stored), "postgres" if row["kind"] == "postgres" else "iceberg"
    if row["kind"] == "iceberg":
        live = iceberg_columns(settings, row["location"])
        if live:
            return live, "iceberg"
        return [], "unavailable"
    try:
        live = postgres_columns(repository.connection, row["location"])
    except Exception:  # noqa: BLE001 - metadata lookup must not 500
        return [], "unavailable"
    return live, "postgres" if live else "unavailable"
