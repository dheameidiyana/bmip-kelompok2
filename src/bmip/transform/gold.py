"""Gold mart publisher: dbt computes in DuckDB, PyIceberg commits (W1-C).

dbt materialises ``gold.mart_*`` inside the local DuckDB target. This module
reads those tables back as Arrow and overwrites one Iceberg partition per
``event_date``, which is the merge policy the workplan requires. A rerun with
the same input therefore replaces the partition instead of appending rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DateType,
    DecimalType,
    DoubleType,
    ListType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.iceberg import ensure_namespace, load_rest_catalog, table_with_host_io

log = get_logger(__name__)

GOLD_NAMESPACE = "gold"
MART_MARKET = "gold.mart_market"
MART_SENTIMENT = "gold.mart_sentiment"
MART_ML = "gold.mart_ml"

MART_TABLES = (MART_MARKET, MART_SENTIMENT, MART_ML)

LOCATIONS = {
    MART_MARKET: "s3://lakehouse/warehouse/gold.db/mart_market",
    MART_SENTIMENT: "s3://lakehouse/warehouse/gold.db/mart_sentiment",
    MART_ML: "s3://lakehouse/warehouse/gold.db/mart_ml",
}

DECIMAL = DecimalType(18, 8)


def _iceberg_market_schema() -> Schema:
    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "window_start", TimestamptzType(), required=True),
        NestedField(3, "open", DECIMAL, required=True),
        NestedField(4, "high", DECIMAL, required=True),
        NestedField(5, "low", DECIMAL, required=True),
        NestedField(6, "close", DECIMAL, required=True),
        NestedField(7, "volume", DECIMAL, required=True),
        NestedField(8, "quote_volume", DECIMAL, required=True),
        NestedField(9, "trade_count", LongType(), required=True),
        NestedField(10, "vwap", DECIMAL, required=True),
        NestedField(11, "log_return_1h", DoubleType(), required=False),
        NestedField(12, "realized_vol_1h", DoubleType(), required=False),
        NestedField(13, "rv_ewma_24h", DoubleType(), required=False),
        NestedField(14, "source", StringType(), required=True),
        NestedField(15, "updated_at", TimestamptzType(), required=True),
        NestedField(16, "event_date", DateType(), required=True),
    )


def _iceberg_sentiment_schema() -> Schema:
    return Schema(
        NestedField(1, "window_start", TimestamptzType(), required=True),
        NestedField(2, "post_count", LongType(), required=True),
        NestedField(3, "unique_authors", LongType(), required=True),
        NestedField(4, "mean_sentiment", DoubleType(), required=False),
        NestedField(5, "positive_share", DoubleType(), required=False),
        NestedField(6, "negative_share", DoubleType(), required=False),
        NestedField(7, "neutral_share", DoubleType(), required=False),
        NestedField(8, "total_likes", LongType(), required=True),
        NestedField(9, "total_reposts", LongType(), required=True),
        NestedField(10, "total_replies", LongType(), required=True),
        NestedField(11, "engagement_per_post", DoubleType(), required=False),
        NestedField(
            12,
            "top_hashtags",
            ListType(element_id=13, element_type=StringType(), element_required=False),
            required=False,
        ),
        NestedField(14, "sentiment_model_version", StringType(), required=True),
        NestedField(15, "updated_at", TimestamptzType(), required=True),
        NestedField(16, "event_date", DateType(), required=True),
    )


def _iceberg_ml_schema() -> Schema:
    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "window_start", TimestamptzType(), required=True),
        NestedField(3, "ret_5m", DoubleType(), required=False),
        NestedField(4, "ret_15m", DoubleType(), required=False),
        NestedField(5, "ret_60m", DoubleType(), required=False),
        NestedField(6, "rv_5m", DoubleType(), required=False),
        NestedField(7, "rv_15m", DoubleType(), required=False),
        NestedField(8, "rv_60m", DoubleType(), required=False),
        NestedField(9, "volume_z_60m", DoubleType(), required=False),
        NestedField(10, "trade_count_60m", LongType(), required=False),
        NestedField(11, "hl_range_1m", DoubleType(), required=False),
        NestedField(12, "vwap_dev", DoubleType(), required=False),
        NestedField(13, "sent_mean_1h", DoubleType(), required=False),
        NestedField(14, "sent_pos_share", DoubleType(), required=False),
        NestedField(15, "sent_neg_share", DoubleType(), required=False),
        NestedField(16, "post_count_1h", LongType(), required=False),
        NestedField(17, "engagement_1h", DoubleType(), required=False),
        NestedField(18, "label_rv_next_1h", DoubleType(), required=False),
        NestedField(19, "label_start", TimestamptzType(), required=False),
        NestedField(20, "label_end", TimestamptzType(), required=False),
        NestedField(21, "feature_snapshot_id", StringType(), required=True),
        NestedField(22, "dq_status", StringType(), required=True),
        NestedField(23, "event_date", DateType(), required=True),
    )


def _field(name: str, data_type: pa.DataType, nullable: bool = False) -> pa.Field:
    return pa.field(name, data_type, nullable=nullable)


TS = pa.timestamp("us", tz="UTC")
MARKET_ARROW_SCHEMA = pa.schema(
    [
        _field("symbol", pa.large_string()),
        _field("window_start", TS),
        _field("open", pa.decimal128(18, 8)),
        _field("high", pa.decimal128(18, 8)),
        _field("low", pa.decimal128(18, 8)),
        _field("close", pa.decimal128(18, 8)),
        _field("volume", pa.decimal128(18, 8)),
        _field("quote_volume", pa.decimal128(18, 8)),
        _field("trade_count", pa.int64()),
        _field("vwap", pa.decimal128(18, 8)),
        _field("log_return_1h", pa.float64(), nullable=True),
        _field("realized_vol_1h", pa.float64(), nullable=True),
        _field("rv_ewma_24h", pa.float64(), nullable=True),
        _field("source", pa.large_string()),
        _field("updated_at", TS),
        _field("event_date", pa.date32()),
    ]
)

SENTIMENT_ARROW_SCHEMA = pa.schema(
    [
        _field("window_start", TS),
        _field("post_count", pa.int64()),
        _field("unique_authors", pa.int64()),
        _field("mean_sentiment", pa.float64(), nullable=True),
        _field("positive_share", pa.float64(), nullable=True),
        _field("negative_share", pa.float64(), nullable=True),
        _field("neutral_share", pa.float64(), nullable=True),
        _field("total_likes", pa.int64()),
        _field("total_reposts", pa.int64()),
        _field("total_replies", pa.int64()),
        _field("engagement_per_post", pa.float64(), nullable=True),
        _field("top_hashtags", pa.list_(pa.large_string()), nullable=True),
        _field("sentiment_model_version", pa.large_string()),
        _field("updated_at", TS),
        _field("event_date", pa.date32()),
    ]
)

ML_ARROW_SCHEMA = pa.schema(
    [
        _field("symbol", pa.large_string()),
        _field("window_start", TS),
        _field("ret_5m", pa.float64(), nullable=True),
        _field("ret_15m", pa.float64(), nullable=True),
        _field("ret_60m", pa.float64(), nullable=True),
        _field("rv_5m", pa.float64(), nullable=True),
        _field("rv_15m", pa.float64(), nullable=True),
        _field("rv_60m", pa.float64(), nullable=True),
        _field("volume_z_60m", pa.float64(), nullable=True),
        _field("trade_count_60m", pa.int64(), nullable=True),
        _field("hl_range_1m", pa.float64(), nullable=True),
        _field("vwap_dev", pa.float64(), nullable=True),
        _field("sent_mean_1h", pa.float64(), nullable=True),
        _field("sent_pos_share", pa.float64(), nullable=True),
        _field("sent_neg_share", pa.float64(), nullable=True),
        _field("post_count_1h", pa.int64(), nullable=True),
        _field("engagement_1h", pa.float64(), nullable=True),
        _field("label_rv_next_1h", pa.float64(), nullable=True),
        _field("label_start", TS, nullable=True),
        _field("label_end", TS, nullable=True),
        _field("feature_snapshot_id", pa.large_string()),
        _field("dq_status", pa.large_string()),
        _field("event_date", pa.date32()),
    ]
)

SCHEMAS = {
    MART_MARKET: (_iceberg_market_schema, MARKET_ARROW_SCHEMA),
    MART_SENTIMENT: (_iceberg_sentiment_schema, SENTIMENT_ARROW_SCHEMA),
    MART_ML: (_iceberg_ml_schema, ML_ARROW_SCHEMA),
}


def coerce(table: pa.Table, schema: pa.Schema) -> pa.Table:
    """Select the contract columns in order and cast them to the Iceberg types."""
    missing = [name for name in schema.names if name not in table.column_names]
    if missing:
        raise ValueError(f"gold table is missing columns: {', '.join(missing)}")
    columns = [table.column(name).cast(schema.field(name).type) for name in schema.names]
    return pa.Table.from_arrays(columns, schema=schema)


@dataclass(frozen=True)
class GoldPublishResult:
    table: str
    rows: int
    partitions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rows": self.rows,
            "partitions": self.partitions,
        }


class GoldWriter:
    def __init__(
        self,
        settings: Settings,
        catalog: Catalog | None = None,
        service: str = "dbt",
    ) -> None:
        self.settings = settings
        self.service = service
        self.catalog = catalog or load_rest_catalog(settings, service)

    def ensure_tables(self) -> None:
        ensure_namespace(self.catalog, GOLD_NAMESPACE)
        for identifier in MART_TABLES:
            iceberg_schema, _ = SCHEMAS[identifier]
            schema_obj = iceberg_schema()
            self.catalog.create_table_if_not_exists(
                identifier,
                schema=schema_obj,
                location=LOCATIONS[identifier],
                partition_spec=PartitionSpec(
                    PartitionField(
                        source_id=schema_obj.find_field("event_date").field_id,
                        field_id=1000,
                        transform=IdentityTransform(),
                        name="event_date",
                    )
                ),
            )

    def _table(self, identifier: str):
        return table_with_host_io(self.catalog, self.settings, identifier, self.service)

    def publish_arrow(self, identifier: str, arrow: pa.Table) -> GoldPublishResult:
        _, arrow_schema = SCHEMAS[identifier]
        prepared = coerce(arrow, arrow_schema)
        table = self._table(identifier)
        dates = sorted(
            {
                value.date() if hasattr(value, "date") else value
                for value in prepared.column("event_date").to_pylist()
            }
        )
        if not dates:
            return GoldPublishResult(identifier, 0, 0)
        for event_date in dates:
            mask = pa.compute.equal(
                prepared.column("event_date"), pa.scalar(event_date, pa.date32())
            )
            partition = prepared.filter(mask)
            table.overwrite(partition, overwrite_filter=EqualTo("event_date", event_date))
        log.info(
            "gold partition overwrite",
            extra={
                "ctx_table": identifier,
                "ctx_rows": prepared.num_rows,
                "ctx_partitions": len(dates),
            },
        )
        return GoldPublishResult(identifier, prepared.num_rows, len(dates))

    def publish_from_duckdb(self, duckdb_path: str | Path) -> list[GoldPublishResult]:
        """Read the dbt marts from DuckDB and commit them to Iceberg."""
        import duckdb

        path = Path(duckdb_path)
        if not path.exists():
            raise FileNotFoundError(f"DuckDB target not found: {path}")
        results: list[GoldPublishResult] = []
        with duckdb.connect(str(path)) as connection:
            for identifier in MART_TABLES:
                schema, table_name = identifier.split(".")
                arrow = connection.execute(
                    f'select * from "{schema}"."{table_name}"'
                ).fetch_arrow_table()
                results.append(self.publish_arrow(identifier, arrow))
        return results

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for identifier in MART_TABLES:
            try:
                result[identifier] = len(self._table(identifier).scan().to_arrow())
            except Exception:
                result[identifier] = 0
        return result

    def fetch(self, identifier: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        rows = self._table(identifier).scan().to_arrow().to_pylist()
        rows.sort(key=lambda row: (row["window_start"], row.get("symbol") or ""))
        return rows[:limit] if limit else rows

    def partition_dates(self, identifier: str) -> list[date]:
        rows = self._table(identifier).scan().to_arrow().column("event_date").to_pylist()
        return sorted({value for value in rows if value is not None})
