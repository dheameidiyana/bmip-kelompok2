"""Iceberg lifecycle: compaction, snapshot expiry, orphan removal, retention.

PyIceberg 0.12 exposes ``expire_snapshots`` but not ``rewrite_data_files`` or
``remove_orphan_files``. Compaction therefore rewrites a partition through
``table.overwrite`` (the same primitive the gold writer already uses), and
orphan removal reconciles the S3 listing against every manifest still
referenced by the catalog. The deviation is recorded in the C3-C handoff.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.compute as pc
from botocore.config import Config
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo, LessThan
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import DateType, LongType, NestedField

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.iceberg import ensure_namespace, load_rest_catalog, table_with_host_io

log = get_logger(__name__)

LAYER_RETENTION = {"bronze": 14, "silver": 30, "gold": 90}
TARGET_FILE_BYTES = 128 * 1024 * 1024
SNAPSHOT_DAYS = 7
ORPHAN_AGE_HOURS = 24

TABLE_CANDIDATES = (
    "bronze.market_trade_raw",
    "bronze.social_post_raw",
    "silver.market_trades",
    "silver.market_ohlcv_1m",
    "silver.social_post",
    "silver.social_sentiment",
    "gold.mart_market",
    "gold.mart_sentiment",
    "gold.mart_ml",
    "gold.predictions",
)


def _files(table) -> list[dict[str, Any]]:
    try:
        return table.inspect.files().to_pylist()
    except Exception as exc:  # noqa: BLE001 - inspect must not abort the job
        log.warning("cannot inspect files", extra={"ctx_error": str(exc)})
        return []


def _is_data(row: dict[str, Any]) -> bool:
    content = row.get("content")
    if content in (None, 0):
        return True
    text = str(content).upper()
    return "DATA" in text and "DELETE" not in text


def _stats(table) -> dict[str, Any]:
    files = _files(table)
    data = [row for row in files if _is_data(row)]
    sizes = [int(row.get("file_size_in_bytes") or 0) for row in data]
    return {
        "files": len(data),
        "bytes": sum(sizes),
        "avg_bytes": round(sum(sizes) / len(sizes), 2) if sizes else 0,
        "snapshots": len(table.snapshots()),
    }


def _partition_dates(table) -> dict[date, int]:
    counts: dict[date, int] = defaultdict(int)
    for row in _files(table):
        if not _is_data(row):
            continue
        partition = row.get("partition") or {}
        value = partition.get("event_date") if isinstance(partition, dict) else None
        if value is not None:
            counts[value] += 1
    return dict(counts)


def _row_count(table) -> int:
    return sum(int(row.get("record_count") or 0) for row in _files(table) if _is_data(row))


def compact_table(table, *, max_partitions: int = 200, max_rows: int = 500_000) -> dict[str, Any]:
    before = _stats(table)
    counts = _partition_dates(table)
    candidates = [value for value, count in sorted(counts.items()) if count > 1]
    if candidates and _row_count(table) > max_rows:
        return {
            "before": before,
            "after": before,
            "candidates": len(candidates),
            "rewritten": [],
            "skipped": f"{_row_count(table)} rows exceeds the {max_rows} local rewrite limit",
        }
    rewritten: list[dict[str, Any]] = []
    if candidates:
        arrow = table.scan().to_arrow()
        for event_date in candidates[:max_partitions]:
            mask = pc.equal(arrow["event_date"], pa.scalar(event_date, pa.date32()))
            partition = arrow.filter(mask)
            if partition.num_rows == 0:
                continue
            table.overwrite(partition, overwrite_filter=EqualTo("event_date", event_date))
            rewritten.append({"event_date": str(event_date), "rows": partition.num_rows})
        after = _stats(table)
    else:
        after = before
    return {
        "before": before,
        "after": after,
        "candidates": len(candidates),
        "rewritten": rewritten,
        "skipped": "already at one file per partition" if not candidates else None,
    }


def expire_snapshots(table, *, days: int = SNAPSHOT_DAYS) -> dict[str, Any]:
    before = len(table.snapshots())
    cutoff = datetime.now(UTC) - timedelta(days=days)
    error: str | None = None
    try:
        table.maintenance.expire_snapshots().older_than(cutoff).commit()
    except Exception as exc:  # noqa: BLE001 - no old snapshot is not a failure
        error = f"{type(exc).__name__}: {exc}"
    after = len(table.snapshots())
    return {
        "cutoff": cutoff.isoformat(),
        "before": before,
        "after": after,
        "error": error,
    }


def _s3_client(settings: Settings):
    access_key, secret_key = settings.minio_credentials("process")
    return boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=settings.minio_region,
        config=Config(s3={"addressing_style": "path"}),
    )


def _split_location(location: str) -> tuple[str, str]:
    if not location.startswith("s3://"):
        raise ValueError(f"not an s3 location: {location}")
    bucket, _, prefix = location[5:].partition("/")
    return bucket, prefix.rstrip("/")


def remove_orphans(
    table, settings: Settings, *, apply: bool = False, min_age_hours: int = ORPHAN_AGE_HOURS
) -> dict[str, Any]:
    referenced = {
        row["file_path"]
        for row in table.inspect.all_files().to_pylist()
        if row.get("file_path")
    }
    bucket, prefix = _split_location(table.location())
    client = _s3_client(settings)
    orphans: list[dict[str, Any]] = []
    checked = 0
    cutoff = datetime.now(UTC) - timedelta(hours=min_age_hours)
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/data/"):
        for item in page.get("Contents", []):
            checked += 1
            key = item["Key"]
            location = f"s3://{bucket}/{key}"
            if location in referenced:
                continue
            modified = item.get("LastModified")
            if modified and modified >= cutoff:
                continue
            orphans.append({"key": key, "bytes": item.get("Size", 0)})
    deleted = 0
    if apply:
        for orphan in orphans:
            client.delete_object(Bucket=bucket, Key=orphan["key"])
            deleted += 1
    return {
        "bucket": bucket,
        "prefix": prefix,
        "checked": checked,
        "candidates": len(orphans),
        "deleted": deleted,
        "applied": apply,
        "sample": orphans[:10],
    }


def retention_plan(table, *, days: int, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(UTC).date()
    cutoff = as_of - timedelta(days=days)
    old_dates: dict[date, int] = defaultdict(int)
    for row in _files(table):
        if not _is_data(row):
            continue
        partition = row.get("partition") or {}
        value = partition.get("event_date") if isinstance(partition, dict) else None
        if value is not None and value < cutoff:
            old_dates[value] += int(row.get("record_count") or 0)
    return {
        "cutoff": str(cutoff),
        "old_partitions": len(old_dates),
        "old_rows": sum(old_dates.values()),
        "old_dates": [str(value) for value in sorted(old_dates)[:20]],
    }


def apply_retention(table, *, days: int, as_of: date | None = None) -> dict[str, Any]:
    """Delete partitions older than the layer window.

    ``as_of`` makes the fixture deterministic; production uses today's date.
    """
    as_of = as_of or datetime.now(UTC).date()
    cutoff = as_of - timedelta(days=days)
    before = table.scan().to_arrow()
    before_rows = before.num_rows
    dates = set(before["event_date"].to_pylist()) if "event_date" in before.column_names else set()
    old_dates = sorted(value for value in dates if value is not None and value < cutoff)
    if old_dates:
        table.delete(delete_filter=LessThan("event_date", cutoff))
    after = table.scan().to_arrow()
    return {
        "cutoff": str(cutoff),
        "before_rows": before_rows,
        "after_rows": after.num_rows,
        "old_partitions": len(old_dates),
        "old_dates": [str(value) for value in old_dates[:20]],
    }


def _fixture_retention(catalog: Catalog, settings: Settings) -> dict[str, Any]:
    from pyiceberg.exceptions import NoSuchTableError

    try:
        ensure_namespace(catalog, "silver")
    except Exception as exc:  # noqa: BLE001 - 409/500 both mean "try the table"
        log.info("silver namespace check failed", extra={"ctx_error": str(exc)})
    identifier = "silver.c3c_retention_probe"
    try:
        catalog.drop_table(identifier)
    except NoSuchTableError:
        pass
    schema = Schema(
        NestedField(1, "id", LongType(), required=True),
        NestedField(2, "event_date", DateType(), required=True),
    )
    spec = PartitionSpec(
        PartitionField(source_id=2, field_id=1000, transform=IdentityTransform(), name="event_date")
    )
    import uuid

    location = f"s3://lakehouse/warehouse/silver.db/c3c_retention_probe_{uuid.uuid4().hex[:8]}"
    table = catalog.create_table(
        identifier,
        schema=schema,
        partition_spec=spec,
        location=location,
    )
    print("fixture: table created", flush=True)
    table = table_with_host_io(catalog, settings, identifier, "process")
    today = datetime.now(UTC).date()
    payload = pa.Table.from_arrays(
        [
            pa.array([1, 2, 3], type=pa.int64()),
            pa.array(
                [today - timedelta(days=30), today, today], type=pa.date32()
            ),
        ],
        schema=pa.schema(
            [
                pa.field("id", pa.int64(), nullable=False),
                pa.field("event_date", pa.date32(), nullable=False),
            ]
        ),
    )
    table.overwrite(payload)
    print("fixture: rows written", flush=True)
    result = apply_retention(table, days=14)
    print("fixture: retention applied", flush=True)
    result.update(
        {
            "table": identifier,
            "expected_after": 2,
            "result": (
                "PASS"
                if result["after_rows"] == 2 and result["before_rows"] == 3
                else "FAIL"
            ),
        }
    )
    catalog.drop_table(identifier)
    print("fixture: table dropped", flush=True)
    return result


def run(
    settings: Settings,
    *,
    compact: bool = True,
    expire: bool = True,
    orphans: bool = False,
    retention_apply: set[str] | None = None,
    as_of: date | None = None,
    tables: list[str] | None = None,
) -> dict[str, Any]:
    catalog = load_rest_catalog(settings, "process")
    report: dict[str, Any] = {
        "tables": {},
        "fixture_retention": None,
        "started_at": datetime.now(UTC).isoformat(),
    }
    for identifier in tables or TABLE_CANDIDATES:
        try:
            table = table_with_host_io(catalog, settings, identifier, "process")
        except Exception as exc:  # noqa: BLE001 - missing table is reported, not fatal
            report["tables"][identifier] = {"status": "missing", "detail": str(exc)[:300]}
            continue
        entry: dict[str, Any] = {"status": "ok"}
        try:
            layer = identifier.split(".", 1)[0]
            entry["retention_plan"] = retention_plan(
                table, days=LAYER_RETENTION[layer], as_of=as_of
            )
            if compact and layer != "bronze":
                entry["compaction"] = compact_table(table)
            if expire:
                entry["snapshots"] = expire_snapshots(table)
            if orphans:
                entry["orphans"] = remove_orphans(table, settings, apply=True)
            if retention_apply and layer in retention_apply:
                entry["retention"] = apply_retention(
                    table, days=LAYER_RETENTION[layer], as_of=as_of
                )
            entry["final"] = _stats(table)
        except Exception as exc:  # noqa: BLE001 - keep the other tables moving
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report["tables"][identifier] = entry
    report["fixture_retention"] = _fixture_retention(catalog, settings)
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def json_reference(value: Any) -> str:
    return json.dumps(value, default=str)
