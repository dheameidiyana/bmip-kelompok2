"""OpenLineage event and dataset helpers.

The payload follows the OpenLineage RunEvent schema (2-0-2). Dataset names use
the convention in ARCHITECTURE section 14.2:

* Iceberg: ``s3://lakehouse/warehouse/<layer>.db/<table>``
* PostgreSQL serving: ``postgres://serving/<table>``
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

PRODUCER = os.getenv(
    "OPENLINEAGE_PRODUCER", "https://github.com/dheameidiyana/bmip-kelompok2"
)
DATASET_NAMESPACE = os.getenv(
    "OPENLINEAGE_DATASET_NAMESPACE", "s3://lakehouse/warehouse"
)
SERVING_NAMESPACE = os.getenv("OPENLINEAGE_SERVING_NAMESPACE", "postgres://serving")
SCHEMA_URL = (
    "https://openlineage.io/spec/2-0-2/OpenLineage.json#/$defs/RunEvent"
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _facet(name: str, payload: dict[str, Any], schema: str) -> dict[str, Any]:
    return {
        "_producer": PRODUCER,
        "_schemaURL": f"https://openlineage.io/spec/facets/2-0-2/{schema}",
        **payload,
        "_facetName": name,
    }


def schema_facet(columns: list[dict[str, Any]]) -> dict[str, Any]:
    fields = []
    for column in columns:
        entry = {
            "name": str(column.get("name")),
            "type": str(column.get("type") or column.get("data_type") or "string"),
        }
        description = column.get("description") or column.get("doc")
        if description:
            entry["description"] = str(description)
        fields.append(entry)
    return _facet("schema", {"fields": fields}, "SchemaDatasetFacet.json")


def error_facet(message: str) -> dict[str, Any]:
    return _facet(
        "errorMessage",
        {"message": message[:4000], "programmingLanguage": "PYTHON"},
        "ErrorMessageRunFacet.json",
    )


def dataset_ref(
    layer: str,
    table: str,
    *,
    facets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an OpenLineage dataset reference for a BMIP layer table."""
    layer = layer.strip().lower()
    table = table.strip()
    if layer == "serving":
        namespace, name = SERVING_NAMESPACE, table
    else:
        namespace, name = DATASET_NAMESPACE, f"{layer}.db/{table}"
    return {"namespace": namespace, "name": name, "facets": facets or {}}


def build_run_event(
    *,
    event_type: str,
    job_name: str,
    run_id: str | None = None,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    namespace: str = "bmip_batch",
    run_facets: dict[str, Any] | None = None,
    job_facets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one OpenLineage RunEvent dictionary."""
    event = {
        "eventType": event_type,
        "eventTime": utc_now(),
        "producer": PRODUCER,
        "schemaURL": SCHEMA_URL,
        "run": {"runId": run_id or str(uuid4()), "facets": run_facets or {}},
        "job": {"namespace": namespace, "name": job_name, "facets": job_facets or {}},
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
    }
    return event
