"""Append-only bronze tables backed by PyIceberg and Lakekeeper."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.io import load_file_io
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    BooleanType,
    DateType,
    DecimalType,
    ListType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from bmip.common.config import Settings


def _iceberg_market_schema() -> Schema:
    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "trade_id", LongType(), required=True),
        NestedField(3, "event_ts", TimestamptzType(), required=True),
        NestedField(4, "price", DecimalType(18, 8), required=True),
        NestedField(5, "qty", DecimalType(18, 8), required=True),
        NestedField(6, "is_buyer_maker", BooleanType(), required=True),
        NestedField(7, "ingest_ts", TimestamptzType(), required=True),
        NestedField(8, "source", StringType(), required=True),
        NestedField(9, "schema_version", StringType(), required=True),
        NestedField(10, "payload_hash", StringType(), required=True),
        NestedField(11, "batch_id", StringType(), required=True),
        NestedField(12, "raw_payload", StringType(), required=True),
        NestedField(13, "event_date", DateType(), required=True),
    )


def _iceberg_social_schema() -> Schema:
    return Schema(
        NestedField(1, "post_uri", StringType(), required=True),
        NestedField(2, "author_did", StringType(), required=True),
        NestedField(3, "author_handle", StringType(), required=False),
        NestedField(4, "created_at", TimestamptzType(), required=True),
        NestedField(5, "lang", StringType(), required=False),
        NestedField(6, "text", StringType(), required=True),
        NestedField(
            7,
            "hashtags",
            ListType(element_id=8, element_type=StringType(), element_required=False),
            required=False,
        ),
        NestedField(9, "like_count", LongType(), required=True),
        NestedField(10, "repost_count", LongType(), required=True),
        NestedField(11, "reply_count", LongType(), required=True),
        NestedField(12, "quote_count", LongType(), required=True),
        NestedField(13, "source", StringType(), required=True),
        NestedField(14, "schema_version", StringType(), required=True),
        NestedField(15, "raw_ref", StringType(), required=True),
        NestedField(16, "payload_hash", StringType(), required=True),
        NestedField(17, "batch_id", StringType(), required=True),
        NestedField(18, "raw_payload", StringType(), required=True),
        NestedField(19, "event_date", DateType(), required=True),
        NestedField(20, "ingest_ts", TimestamptzType(), required=True),
    )


def _field(name: str, data_type: pa.DataType, nullable: bool = False) -> pa.Field:
    return pa.field(name, data_type, nullable=nullable)


MARKET_ARROW_SCHEMA = pa.schema(
    [
        _field("symbol", pa.large_string()),
        _field("trade_id", pa.int64()),
        _field("event_ts", pa.timestamp("us", tz="UTC")),
        _field("price", pa.decimal128(18, 8)),
        _field("qty", pa.decimal128(18, 8)),
        _field("is_buyer_maker", pa.bool_()),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
        _field("source", pa.large_string()),
        _field("schema_version", pa.large_string()),
        _field("payload_hash", pa.large_string()),
        _field("batch_id", pa.large_string()),
        _field("raw_payload", pa.large_string()),
        _field("event_date", pa.date32()),
    ]
)

SOCIAL_ARROW_SCHEMA = pa.schema(
    [
        _field("post_uri", pa.large_string()),
        _field("author_did", pa.large_string()),
        _field("author_handle", pa.large_string(), nullable=True),
        _field("created_at", pa.timestamp("us", tz="UTC")),
        _field("lang", pa.large_string(), nullable=True),
        _field("text", pa.large_string()),
        _field("hashtags", pa.list_(pa.large_string()), nullable=True),
        _field("like_count", pa.int64()),
        _field("repost_count", pa.int64()),
        _field("reply_count", pa.int64()),
        _field("quote_count", pa.int64()),
        _field("source", pa.large_string()),
        _field("schema_version", pa.large_string()),
        _field("raw_ref", pa.large_string()),
        _field("payload_hash", pa.large_string()),
        _field("batch_id", pa.large_string()),
        _field("raw_payload", pa.large_string()),
        _field("event_date", pa.date32()),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
    ]
)

MARKET_TABLE = "bronze.market_trade_raw"
SOCIAL_TABLE = "bronze.social_post_raw"


def _s3_properties(settings: Settings) -> dict[str, str]:
    access_key, secret_key = settings.minio_credentials("ingest")
    return {
        "s3.endpoint": settings.minio_endpoint,
        "s3.access-key-id": access_key,
        "s3.secret-access-key": secret_key,
        "s3.region": settings.minio_region,
        "s3.path-style-access": "true",
        "s3.remote-signing-enabled": "false",
    }


class BronzeWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.catalog: Catalog = load_catalog(
            "lakekeeper",
            type="rest",
            uri=f"{settings.lakekeeper_url.rstrip('/')}/catalog",
            warehouse=settings.lakekeeper_warehouse,
            **_s3_properties(settings),
        )

    def ensure_tables(self) -> None:
        self.catalog.create_table_if_not_exists(
            MARKET_TABLE,
            schema=_iceberg_market_schema(),
            location="s3://lakehouse/warehouse/bronze.db/market_trade_raw",
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=13,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )
        self.catalog.create_table_if_not_exists(
            SOCIAL_TABLE,
            schema=_iceberg_social_schema(),
            location="s3://lakehouse/warehouse/bronze.db/social_post_raw",
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=19,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )

    def _table(self, identifier: str):
        table = self.catalog.load_table(identifier)
        table.io = load_file_io(_s3_properties(self.settings), table.location())
        return table

    def append_market(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        arrow = pa.Table.from_pylist(rows, schema=MARKET_ARROW_SCHEMA)
        self._table(MARKET_TABLE).append(arrow)

    def append_social(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        arrow = pa.Table.from_pylist(rows, schema=SOCIAL_ARROW_SCHEMA)
        self._table(SOCIAL_TABLE).append(arrow)

    def counts(self) -> list[dict[str, Any]]:
        results = []
        for identifier, column in (
            (MARKET_TABLE, "event_ts"),
            (SOCIAL_TABLE, "created_at"),
        ):
            try:
                rows = self._table(identifier).scan().to_arrow().to_pylist()
            except Exception as exc:  # table may not exist yet
                results.append(
                    {
                        "table": identifier,
                        "row_count": 0,
                        "min_ts": None,
                        "max_ts": None,
                        "error": str(exc),
                    }
                )
                continue
            timestamps = [row[column] for row in rows if row.get(column) is not None]
            results.append(
                {
                    "table": identifier,
                    "row_count": len(rows),
                    "min_ts": min(timestamps) if timestamps else None,
                    "max_ts": max(timestamps) if timestamps else None,
                    "error": None,
                }
            )
        return results


def build_market_row(record: dict[str, Any], batch_id: str, raw_payload: str) -> dict[str, Any]:
    event_ts: datetime = record["event_ts"]
    return {
        "symbol": record["symbol"],
        "trade_id": record["trade_id"],
        "event_ts": event_ts,
        "price": Decimal(record["price"]),
        "qty": Decimal(record["qty"]),
        "is_buyer_maker": record["is_buyer_maker"],
        "ingest_ts": record["ingest_ts"],
        "source": record["source"],
        "schema_version": record["schema_version"],
        "payload_hash": record["payload_hash"],
        "batch_id": batch_id,
        "raw_payload": raw_payload,
        "event_date": event_ts.date(),
    }


def build_social_row(record: dict[str, Any], batch_id: str, raw_payload: str) -> dict[str, Any]:
    created_at: datetime = record["created_at"]
    return {
        "post_uri": record["post_uri"],
        "author_did": record["author_did"],
        "author_handle": record.get("author_handle"),
        "created_at": created_at,
        "lang": record.get("lang"),
        "text": record["text"],
        "hashtags": record.get("hashtags") or [],
        "like_count": record["like_count"],
        "repost_count": record["repost_count"],
        "reply_count": record["reply_count"],
        "quote_count": record["quote_count"],
        "source": record["source"],
        "schema_version": record["schema_version"],
        "raw_ref": record["raw_ref"],
        "payload_hash": record["payload_hash"],
        "batch_id": batch_id,
        "raw_payload": raw_payload,
        "event_date": created_at.astimezone(UTC).date(),
        "ingest_ts": record["ingest_ts"],
    }
