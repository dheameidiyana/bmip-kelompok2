"""Validate source records, write bronze, and record one ledger row per batch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.ingestion.bronze import (
    BronzeWriter,
    build_market_row,
    build_social_row,
)
from bmip.ingestion.contracts import (
    ContractIssue,
    validate_market_trade,
    validate_social_post,
)
from bmip.ingestion.hashing import canonical_json, records_checksum
from bmip.ingestion.kafka import publish_market_trades
from bmip.ingestion.ledger import (
    advance_watermark,
    begin_batch,
    finish_batch,
    get_batch,
)
from bmip.ingestion.quarantine import write_quarantine

log = get_logger(__name__)

IDENTICAL = "skipped_identical"


@dataclass(frozen=True)
class BatchResult:
    batch_id: str
    source: str
    row_count: int
    checksum: str
    status: str
    bronze_table: str
    quarantined: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "source": self.source,
            "row_count": self.row_count,
            "checksum": self.checksum,
            "status": self.status,
            "bronze_table": self.bronze_table,
            "quarantined": self.quarantined,
        }


def _rejected(raw: Any, issues: list[ContractIssue]) -> dict[str, Any]:
    return {
        "raw": raw,
        "errors": [{"path": issue.path, "message": issue.message} for issue in issues],
    }


def prepare_market(
    items: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    valid: list[tuple[dict[str, Any], str]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        raw = item.pop("_raw", item)
        result = validate_market_trade(item)
        if not result.ok or result.model is None:
            rejected.append(_rejected(raw, result.errors))
            continue
        record = result.model.model_dump(mode="python")
        valid.append((record, canonical_json(raw)))
    return valid, rejected


def prepare_social(
    items: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], str]], list[dict[str, Any]]]:
    valid: list[tuple[dict[str, Any], str]] = []
    rejected: list[dict[str, Any]] = []
    for item in items:
        raw = item.pop("_raw", item)
        result = validate_social_post(item)
        if not result.ok or result.model is None:
            rejected.append(_rejected(raw, result.errors))
            continue
        record = result.model.model_dump(mode="python")
        valid.append((record, canonical_json(raw)))
    return valid, rejected


def _window(records: list[dict[str, Any]], column: str) -> tuple[datetime, datetime]:
    values = [record[column] for record in records]
    return min(values), max(values)


def _run_batch(
    settings: Settings,
    records: list[dict[str, Any]],
    raw_payloads: list[str],
    source: str,
    bronze_table: str,
    writer: BronzeWriter,
    publish: bool,
    quarantined: int,
) -> BatchResult:
    window_start, window_end = _window(records, "event_ts" if source != "bluesky" else "created_at")
    checksum = records_checksum(record["payload_hash"] for record in records)
    if source == "bluesky":
        batch_id = (
            f"social-bluesky-{window_start.astimezone(UTC):%Y%m%dT%H%M%S}"
            f"-{checksum[:8]}"
        )
    else:
        batch_id = (
            f"market-{source}-{window_start.astimezone(UTC):%Y%m%dT%H%M%S}"
            f"-{max(record['trade_id'] for record in records)}"
        )

    existing = get_batch(settings.postgres_dsn, batch_id)
    if existing and existing.checksum == checksum and existing.status in ("succeeded", IDENTICAL):
        finish_batch(
            settings.postgres_dsn,
            batch_id,
            IDENTICAL,
            existing.row_count,
            checksum,
        )
        log.info(
            "batch skipped because the checksum is unchanged",
            extra={"ctx_batch_id": batch_id, "ctx_checksum": checksum},
        )
        if source == "bluesky":
            advance_watermark(settings.postgres_dsn, "bluesky", window_end)
        return BatchResult(
            batch_id,
            source,
            existing.row_count,
            checksum,
            IDENTICAL,
            bronze_table,
            quarantined,
        )

    begin_batch(
        settings.postgres_dsn,
        batch_id,
        source,
        window_start,
        window_end,
        checksum,
    )
    try:
        if publish:
            publish_market_trades(settings.redpanda_brokers, settings.market_topic, records)
        if source == "bluesky":
            rows = [
                build_social_row(record, batch_id, raw)
                for record, raw in zip(records, raw_payloads, strict=True)
            ]
            writer.append_social(rows)
        else:
            rows = [
                build_market_row(record, batch_id, raw)
                for record, raw in zip(records, raw_payloads, strict=True)
            ]
            writer.append_market(rows)
        finish_batch(settings.postgres_dsn, batch_id, "succeeded", len(records), checksum)
        if source == "bluesky":
            advance_watermark(settings.postgres_dsn, "bluesky", window_end)
    except Exception:
        finish_batch(settings.postgres_dsn, batch_id, "failed", 0, checksum)
        raise
    log.info(
        "batch written to bronze",
        extra={
            "ctx_batch_id": batch_id,
            "ctx_rows": len(records),
            "ctx_checksum": checksum,
        },
    )
    return BatchResult(
        batch_id,
        source,
        len(records),
        checksum,
        "succeeded",
        bronze_table,
        quarantined,
    )


def run_market_batch(
    settings: Settings,
    items: list[dict[str, Any]],
    publish: bool = True,
    writer: BronzeWriter | None = None,
) -> BatchResult:
    valid, rejected = prepare_market(items)
    quarantine_key = write_quarantine(settings, "market", rejected)
    if not valid:
        raise ValueError(
            f"no valid market trades (rejected={len(rejected)}, quarantine={quarantine_key})"
        )
    records = [record for record, _ in valid]
    raw_payloads = [raw for _, raw in valid]
    writer = writer or BronzeWriter(settings)
    writer.ensure_tables()
    return _run_batch(
        settings,
        records,
        raw_payloads,
        records[0]["source"],
        "bronze.market_trade_raw",
        writer,
        publish,
        len(rejected),
    )


def run_social_batch(
    settings: Settings,
    items: list[dict[str, Any]],
    writer: BronzeWriter | None = None,
) -> BatchResult:
    valid, rejected = prepare_social(items)
    quarantine_key = write_quarantine(settings, "social", rejected)
    if not valid:
        raise ValueError(
            f"no valid social posts (rejected={len(rejected)}, quarantine={quarantine_key})"
        )
    records = [record for record, _ in valid]
    raw_payloads = [raw for _, raw in valid]
    writer = writer or BronzeWriter(settings)
    writer.ensure_tables()
    return _run_batch(
        settings,
        records,
        raw_payloads,
        "bluesky",
        "bronze.social_post_raw",
        writer,
        False,
        len(rejected),
    )
