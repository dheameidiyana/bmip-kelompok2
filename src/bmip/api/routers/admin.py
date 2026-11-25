"""Operator and admin actions (W2-C)."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response, status

from bmip.api.deps import (
    build_meta,
    get_actor,
    get_repository,
    get_role,
    get_settings,
    require_role,
)
from bmip.api.errors import ApiProblem
from bmip.api.keys import new_key
from bmip.api.models import (
    BackfillOut,
    BackfillRequest,
    CatalogReloadOut,
    KeyRotateOut,
)
from bmip.common.config import Settings
from bmip.serving.loader import reload_catalog
from bmip.serving.repository import ServingRepository

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/backfill",
    response_model=BackfillOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_role("operator"))],
    summary="Queue a gold/serving backfill for an event-time range",
)
def queue_backfill(
    request: Request,
    response: Response,
    payload: BackfillRequest,
    repository: ServingRepository = Depends(get_repository),
    actor: str = Depends(get_actor),
    role: str = Depends(get_role),
) -> BackfillOut:
    if payload.start >= payload.end:
        raise ApiProblem(
            400,
            "invalid-range",
            "Invalid backfill range",
            "The start timestamp must be earlier than the end timestamp.",
        )
    request_id = f"bf-{uuid4().hex[:12]}"
    repository.insert_backfill(
        request_id=request_id,
        start=payload.start,
        end=payload.end,
        actor=actor,
        role=role,
        detail=payload.detail,
    )
    response.headers["X-Data-Source"] = "ops"
    response.headers["X-Data-Stale"] = "false"
    return BackfillOut(
        request_id=request_id,
        status="queued",
        start=payload.start,
        end=payload.end,
        meta=build_meta(request, source="serving", stale=False, count=1),
    )


@router.post(
    "/catalog/reload",
    response_model=CatalogReloadOut,
    dependencies=[Depends(require_role("admin"))],
    summary="Reload serving.catalog_datasets from ops.dataset_registry",
)
def catalog_reload(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> CatalogReloadOut:
    result = reload_catalog(settings)
    response.headers["X-Data-Source"] = "ops"
    response.headers["X-Data-Stale"] = "false"
    return CatalogReloadOut(
        datasets=int(result["datasets"]),
        meta=build_meta(
            request, source="serving", stale=False, count=int(result["datasets"])
        ),
    )


@router.post(
    "/keys/{key_id}/rotate",
    response_model=KeyRotateOut,
    dependencies=[Depends(require_role("admin"))],
    summary="Rotate one API key; the new plaintext is returned once",
)
def rotate_key(
    request: Request,
    key_id: str,
    settings: Settings = Depends(get_settings),
) -> KeyRotateOut:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        settings.postgres_dsn, row_factory=dict_row
    ) as connection:
        row = connection.execute(
            "SELECT key_id, role, owner FROM ops.api_keys WHERE key_id = %s",
            (key_id,),
        ).fetchone()
        if row is None:
            raise ApiProblem(
                404,
                "key-not-found",
                "API key not found",
                f"No API key with id {key_id!r}.",
            )
        plaintext, identity, hashed = new_key(
            str(row["role"]),
            str(row["owner"]),
            key_id=key_id,
            salt=settings.api_key_salt,
        )
        connection.execute(
            """
            UPDATE ops.api_keys
            SET key_hash = %s, revoked_at = NULL, created_at = now()
            WHERE key_id = %s
            """,
            (hashed, key_id),
        )
        connection.commit()
    return KeyRotateOut(
        key_id=identity.key_id,
        role=identity.role,
        owner=identity.owner,
        key=plaintext,
        meta=build_meta(request, source="serving", stale=False, count=1),
    )
