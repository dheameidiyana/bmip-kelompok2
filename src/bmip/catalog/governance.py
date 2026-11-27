"""Governance workflow for the BMIP catalog (C3-C).

The registry is the source of truth (ARCHITECTURE 14.5). These operations are
deliberately CLI-first: they are audit-producing administrative actions, not
dashboard clicks. Every change writes one ``ops.audit_log`` row and refreshes
``serving.catalog_datasets`` so the API and the catalog portal see it at once.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from bmip.common.config import Settings, get_settings
from bmip.common.logging import get_logger

log = get_logger(__name__)

LAYER_RETENTION = {"bronze": 14, "silver": 30, "gold": 90}
REQUIRED_FIELDS = (
    "id",
    "name",
    "layer",
    "domain",
    "kind",
    "location",
    "description",
    "owner",
    "classification",
    "retention_days",
)
VALID_STATUS = {"active", "deprecated", "retired"}
VALID_ROLES = {"viewer", "operator", "admin"}
WRITABLE_FIELDS = {
    "name",
    "description",
    "owner",
    "classification",
    "retention_days",
    "refresh_schedule",
    "sla",
    "license",
    "contains_pii",
    "tags",
    "contract_version",
    "change_note",
}


class GovernanceError(ValueError):
    """Raised when a governance action is invalid or not permitted."""


def _connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        settings.postgres_dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
    )


def _audit(
    connection: psycopg.Connection,
    *,
    action: str,
    target: str,
    actor: str,
    role: str,
    detail: dict[str, Any],
    status: int = 200,
) -> int:
    row = connection.execute(
        """
        INSERT INTO ops.audit_log
            (actor, role, action, target, method, path, status, detail)
        VALUES (%s, %s, %s, %s, 'CLI', %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            actor,
            role,
            action,
            target,
            f"governance:{action.split('.')[-1]}",
            status,
            json.dumps(detail, default=str),
        ),
    ).fetchone()
    return int(row["id"])


def _require_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise GovernanceError(f"unknown role {role!r}")
    if role != "admin":
        raise GovernanceError("governance actions require the admin role")


def _refresh_serving(settings: Settings) -> int:
    """Copy the registry rows into serving without touching Iceberg schemas.

    The full ``reload_catalog`` path enriches schemas from Iceberg, which is the
    right thing for the admin reload but too slow for a governance test. The
    governance action only changes business metadata, so a local row copy keeps
    the serving view consistent in milliseconds.
    """
    from bmip.serving.repository import ServingRepository

    with _connect(settings) as connection:
        rows = connection.execute(
            """
            SELECT id, name, layer, domain, kind, location, description, owner,
                   classification, retention_days, refresh_schedule, sla, license,
                   contains_pii, tags, auto_classification, status, deprecated_at,
                   removal_date, contract_version
            FROM ops.dataset_registry
            ORDER BY id
            """
        ).fetchall()
        repository = ServingRepository(settings, connection=connection)
        written = repository.upsert_registry(rows)
        if rows:
            connection.execute(
                "DELETE FROM serving.catalog_datasets WHERE id <> ALL(%s)",
                ([row["id"] for row in rows],),
            )
        else:
            connection.execute("DELETE FROM serving.catalog_datasets")
    return written


def _validate_dataset(payload: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_FIELDS if payload.get(field) in (None, "")]
    if missing:
        raise GovernanceError(f"dataset is missing required fields: {missing}")
    if payload["layer"] not in {"bronze", "silver", "gold", "serving"}:
        raise GovernanceError(f"invalid layer {payload['layer']!r}")
    if payload["kind"] not in {"iceberg", "postgres"}:
        raise GovernanceError(f"invalid kind {payload['kind']!r}")
    if int(payload["retention_days"]) <= 0:
        raise GovernanceError("retention_days must be positive")


def register(
    dataset: dict[str, Any],
    *,
    actor: str,
    role: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    _require_role(role)
    settings = settings or get_settings()
    _validate_dataset(dataset)
    with _connect(settings) as connection:
        existing = connection.execute(
            "SELECT id FROM ops.dataset_registry WHERE id = %s", (dataset["id"],)
        ).fetchone()
        if existing:
            raise GovernanceError(f"dataset already registered: {dataset['id']}")
        connection.execute(
            """
            INSERT INTO ops.dataset_registry
                (id, name, layer, domain, kind, location, description, owner,
                 classification, retention_days, refresh_schedule, sla, license,
                 contains_pii, tags, contract_version, change_note, status,
                 updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, 'active', now())
            """,
            (
                dataset["id"],
                dataset["name"],
                dataset["layer"],
                dataset["domain"],
                dataset["kind"],
                dataset["location"],
                dataset["description"],
                dataset["owner"],
                dataset["classification"],
                int(dataset["retention_days"]),
                dataset.get("refresh_schedule"),
                dataset.get("sla"),
                dataset.get("license"),
                bool(dataset.get("contains_pii", False)),
                list(dataset.get("tags") or ()),
                dataset.get("contract_version"),
                dataset.get("change_note"),
            ),
        )
        audit_id = _audit(
            connection,
            action="governance.register",
            target=str(dataset["id"]),
            actor=actor,
            role=role,
            detail={"contract_version": dataset.get("contract_version")},
        )
        written = _refresh_serving(settings)
    return {
        "action": "register",
        "id": dataset["id"],
        "audit_id": audit_id,
        "serving_rows": written,
    }


def change(
    dataset_id: str,
    changes: dict[str, Any],
    *,
    actor: str,
    role: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    _require_role(role)
    settings = settings or get_settings()
    unknown = set(changes) - WRITABLE_FIELDS
    if unknown:
        raise GovernanceError(f"fields are not writable: {sorted(unknown)}")
    if not changes:
        raise GovernanceError("no changes supplied")
    assignments = ", ".join(f"{field} = %s" for field in changes)
    with _connect(settings) as connection:
        exists = connection.execute(
            "SELECT id FROM ops.dataset_registry WHERE id = %s", (dataset_id,)
        ).fetchone()
        if not exists:
            raise GovernanceError(f"unknown dataset: {dataset_id}")
        connection.execute(
            f"UPDATE ops.dataset_registry SET {assignments}, updated_at = now() WHERE id = %s",
            (*changes.values(), dataset_id),
        )
        audit_id = _audit(
            connection,
            action="governance.change",
            target=dataset_id,
            actor=actor,
            role=role,
            detail={"changes": changes},
        )
        written = _refresh_serving(settings)
    return {"action": "change", "id": dataset_id, "audit_id": audit_id, "serving_rows": written}


def deprecate(
    dataset_id: str,
    *,
    removal_date: date,
    note: str,
    actor: str,
    role: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    _require_role(role)
    settings = settings or get_settings()
    if removal_date < date.today():
        raise GovernanceError("removal_date must be today or later")
    with _connect(settings) as connection:
        exists = connection.execute(
            "SELECT id FROM ops.dataset_registry WHERE id = %s", (dataset_id,)
        ).fetchone()
        if not exists:
            raise GovernanceError(f"unknown dataset: {dataset_id}")
        connection.execute(
            """
            UPDATE ops.dataset_registry
            SET status = 'deprecated', deprecated_at = now(),
                removal_date = %s, change_note = %s, updated_at = now()
            WHERE id = %s
            """,
            (removal_date, note, dataset_id),
        )
        audit_id = _audit(
            connection,
            action="governance.deprecate",
            target=dataset_id,
            actor=actor,
            role=role,
            detail={"removal_date": str(removal_date), "note": note},
        )
        written = _refresh_serving(settings)
    return {"action": "deprecate", "id": dataset_id, "audit_id": audit_id, "serving_rows": written}


def delete(
    dataset_id: str,
    *,
    actor: str,
    role: str,
    confirm: bool,
    settings: Settings | None = None,
) -> dict[str, Any]:
    _require_role(role)
    if not confirm:
        raise GovernanceError("delete requires confirm=True")
    settings = settings or get_settings()
    with _connect(settings) as connection:
        row = connection.execute(
            "SELECT status, removal_date FROM ops.dataset_registry WHERE id = %s",
            (dataset_id,),
        ).fetchone()
        if not row:
            raise GovernanceError(f"unknown dataset: {dataset_id}")
        if row["status"] != "deprecated":
            raise GovernanceError("deprecate the dataset before deleting it")
        if row["removal_date"] and row["removal_date"] > date.today():
            raise GovernanceError("removal_date is in the future; wait or force with a new date")
        connection.execute("DELETE FROM ops.dataset_registry WHERE id = %s", (dataset_id,))
        audit_id = _audit(
            connection,
            action="governance.delete",
            target=dataset_id,
            actor=actor,
            role=role,
            detail={"status": row["status"], "removal_date": str(row["removal_date"])},
        )
        written = _refresh_serving(settings)
    return {"action": "delete", "id": dataset_id, "audit_id": audit_id, "serving_rows": written}


def gaps(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    with _connect(settings) as connection:
        rows = connection.execute(
            """
            SELECT id, name, owner, description, classification, retention_days,
                   layer, refresh_schedule, status, removal_date, updated_at
            FROM ops.dataset_registry
            ORDER BY id
            """
        ).fetchall()
        serving = {
            row["id"]: row
            for row in connection.execute(
                """
                SELECT id, owner, description, classification, retention_days, status
                FROM serving.catalog_datasets
                """
            ).fetchall()
        }
    payload: dict[str, list[dict[str, Any]]] = {
        "missing_owner": [],
        "missing_description": [],
        "missing_classification": [],
        "retention_mismatch": [],
        "past_removal": [],
        "deprecated": [],
        "serving_mismatch": [],
    }
    for row in rows:
        if not row["owner"]:
            payload["missing_owner"].append({"id": row["id"]})
        if not row["description"]:
            payload["missing_description"].append({"id": row["id"]})
        if not row["classification"]:
            payload["missing_classification"].append({"id": row["id"]})
        expected = LAYER_RETENTION.get(row["layer"])
        if expected is not None and int(row["retention_days"]) != expected:
            payload["retention_mismatch"].append(
                {"id": row["id"], "expected": expected, "actual": int(row["retention_days"])}
            )
        if row["removal_date"] and row["removal_date"] < date.today():
            payload["past_removal"].append(
                {"id": row["id"], "removal_date": str(row["removal_date"])}
            )
        if row["status"] != "active":
            payload["deprecated"].append({"id": row["id"], "status": row["status"]})
        copy = serving.get(row["id"])
        if copy is None or any(
            copy[field] != row[field]
            for field in ("owner", "description", "classification", "status")
        ) or int(copy["retention_days"]) != int(row["retention_days"]):
            payload["serving_mismatch"].append({"id": row["id"]})
    return {"datasets": len(rows), "gaps": payload}


def metadata_consistency(settings: Settings | None = None) -> dict[str, Any]:
    """Check registry completeness, retention, and serving-copy parity.

    ``refresh_schedule`` is treated as the declared contract; the actual
    metadata touch is ``updated_at``. Serving must have been refreshed after the
    registry change (two-minute tolerance for clock/commit order).
    """
    settings = settings or get_settings()
    with _connect(settings) as connection:
        registry = connection.execute(
            """
            SELECT id, layer, owner, description, classification, retention_days,
                   refresh_schedule, status, removal_date, updated_at
            FROM ops.dataset_registry
            ORDER BY id
            """
        ).fetchall()
        serving = {
            row["id"]: row
            for row in connection.execute(
                """
                SELECT id, layer, owner, description, classification, retention_days,
                       status, updated_at
                FROM serving.catalog_datasets
                """
            ).fetchall()
        }
    failures: list[str] = []
    for row in registry:
        for field in ("owner", "description", "classification"):
            if not row[field]:
                failures.append(f"{row['id']}: missing {field}")
        if not row["refresh_schedule"]:
            failures.append(f"{row['id']}: missing refresh_schedule")
        if row["status"] not in VALID_STATUS:
            failures.append(f"{row['id']}: invalid status {row['status']}")
        expected = LAYER_RETENTION.get(row["layer"])
        if expected is not None and int(row["retention_days"]) != expected:
            failures.append(
                f"{row['id']}: retention {row['retention_days']} != {expected} for {row['layer']}"
            )
        copy = serving.get(row["id"])
        if copy is None:
            failures.append(f"{row['id']}: missing from serving.catalog_datasets")
            continue
        for field in ("owner", "description", "classification", "status"):
            if copy[field] != row[field]:
                failures.append(f"{row['id']}: serving {field} differs from registry")
        if int(copy["retention_days"]) != int(row["retention_days"]):
            failures.append(f"{row['id']}: serving retention differs")
        delta = (copy["updated_at"] - row["updated_at"]).total_seconds()
        if delta < -120:
            failures.append(f"{row['id']}: serving copy is older than the registry row")
    orphaned = sorted(set(serving) - {row["id"] for row in registry})
    if orphaned:
        failures.append(f"serving has orphaned ids: {orphaned}")
    return {
        "id": "metadata_consistency",
        "timestamp": datetime.now(UTC).isoformat(),
        "datasets": len(registry),
        "serving_datasets": len(serving),
        "failures": failures,
        "result": "PASS" if not failures else "FAIL",
    }
