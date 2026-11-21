"""One audit row per authenticated API attempt (W2-C)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from bmip.common.config import Settings
from bmip.common.logging import get_logger

log = get_logger(__name__)


def action_for(method: str, path: str) -> str:
    if path.startswith("/v1/admin/backfill"):
        return "backfill"
    if path.startswith("/v1/admin/catalog/reload"):
        return "catalog-reload"
    if path.startswith("/v1/admin/keys/"):
        return "key-rotate"
    if path.endswith("/predict") and method.upper() == "POST":
        return "predict"
    return "read"


def record(
    settings: Settings,
    *,
    actor: str,
    role: str,
    action: str,
    target: str | None,
    method: str,
    path: str,
    status: int,
    request_id: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Insert an audit row; never raise into the request path."""
    try:
        with psycopg.connect(
            settings.postgres_dsn, autocommit=True, connect_timeout=2
        ) as connection:
            connection.execute(
                """
                INSERT INTO ops.audit_log
                    (actor, role, action, target, method, path, status,
                     request_id, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    actor or "anonymous",
                    role or "anonymous",
                    action,
                    target,
                    method,
                    path,
                    status,
                    request_id,
                    Jsonb(detail or {}),
                ),
            )
    except Exception as exc:  # noqa: BLE001 - audit must not break the API
        log.warning(
            "audit write failed",
            extra={"ctx_error": f"{type(exc).__name__}: {exc}", "ctx_path": path},
        )
