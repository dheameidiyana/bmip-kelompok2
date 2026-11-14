"""PyIceberg writers for silver market trades, OHLCV, and quarantine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
from pyiceberg.catalog import Catalog, load_catalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError
from pyiceberg.expressions import And, EqualTo, GreaterThanOrEqual, LessThan, Or
from pyiceberg.io import load_file_io
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    BooleanType,
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.dlq import DlqPublisher
from bmip.transform.market import (
    MarketTrade,
    SinkStats,
    aggregate_ohlcv,
    utc_datetime,
)

log = get_logger(__name__)

SILVER_NAMESPACE = "silver"
QUARANTINE_NAMESPACE = "quarantine"
TRADES_TABLE = "silver.market_trades"
OHLCV_TABLE = "silver.market_ohlcv_1m"
QUARANTINE_TABLE = "quarantine.market_trade_rejected"

TRADES_LOCATION = "s3://lakehouse/warehouse/silver.db/market_trades"
OHLCV_LOCATION = "s3://lakehouse/warehouse/silver.db/market_ohlcv_1m"
QUARANTINE_LOCATION = "s3://lakehouse/warehouse/quarantine.db/market_trade_rejected"


def _iceberg_trades_schema() -> Schema:
    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "trade_id", LongType(), required=True),
        NestedField(3, "event_ts", TimestamptzType(), required=True),
        NestedField(4, "price", DecimalType(18, 8), required=True),
        NestedField(5, "qty", DecimalType(18, 8), required=True),
        NestedField(6, "is_buyer_maker", BooleanType(), required=True),
        NestedField(7, "ingest_ts", TimestamptzType(), required=True),
        NestedField(8, "source", StringType(), required=True),
        NestedField(9, "payload_hash", StringType(), required=True),
        NestedField(10, "event_date", DateType(), required=True),
    )


def _iceberg_ohlcv_schema() -> Schema:
    return Schema(
        NestedField(1, "symbol", StringType(), required=True),
        NestedField(2, "window_start", TimestamptzType(), required=True),
        NestedField(3, "window_end", TimestamptzType(), required=True),
        NestedField(4, "open", DecimalType(18, 8), required=True),
        NestedField(5, "high", DecimalType(18, 8), required=True),
        NestedField(6, "low", DecimalType(18, 8), required=True),
        NestedField(7, "close", DecimalType(18, 8), required=True),
        NestedField(8, "volume", DecimalType(18, 8), required=True),
        NestedField(9, "quote_volume", DecimalType(18, 8), required=True),
        NestedField(10, "trade_count", LongType(), required=True),
        NestedField(11, "vwap", DecimalType(18, 8), required=True),
        NestedField(12, "event_date", DateType(), required=True),
        NestedField(13, "ingest_ts", TimestamptzType(), required=True),
        NestedField(14, "updated_at", TimestamptzType(), required=True),
    )


def _iceberg_quarantine_schema() -> Schema:
    return Schema(
        NestedField(1, "quarantine_id", StringType(), required=True),
        NestedField(2, "reason", StringType(), required=True),
        NestedField(3, "source", StringType(), required=True),
        NestedField(4, "symbol", StringType(), required=False),
        NestedField(5, "trade_id", LongType(), required=False),
        NestedField(6, "event_ts", TimestamptzType(), required=False),
        NestedField(7, "ingest_ts", TimestamptzType(), required=False),
        NestedField(8, "payload_hash", StringType(), required=False),
        NestedField(9, "raw_payload", StringType(), required=True),
        NestedField(10, "topic", StringType(), required=True),
        NestedField(11, "partition", IntegerType(), required=False),
        NestedField(12, "offset", LongType(), required=False),
        NestedField(13, "detected_at", TimestamptzType(), required=True),
        NestedField(14, "event_date", DateType(), required=True),
        NestedField(15, "details", StringType(), required=False),
    )


def _field(name: str, data_type: pa.DataType, nullable: bool = False) -> pa.Field:
    return pa.field(name, data_type, nullable=nullable)


TRADES_ARROW_SCHEMA = pa.schema(
    [
        _field("symbol", pa.large_string()),
        _field("trade_id", pa.int64()),
        _field("event_ts", pa.timestamp("us", tz="UTC")),
        _field("price", pa.decimal128(18, 8)),
        _field("qty", pa.decimal128(18, 8)),
        _field("is_buyer_maker", pa.bool_()),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
        _field("source", pa.large_string()),
        _field("payload_hash", pa.large_string()),
        _field("event_date", pa.date32()),
    ]
)

OHLCV_ARROW_SCHEMA = pa.schema(
    [
        _field("symbol", pa.large_string()),
        _field("window_start", pa.timestamp("us", tz="UTC")),
        _field("window_end", pa.timestamp("us", tz="UTC")),
        _field("open", pa.decimal128(18, 8)),
        _field("high", pa.decimal128(18, 8)),
        _field("low", pa.decimal128(18, 8)),
        _field("close", pa.decimal128(18, 8)),
        _field("volume", pa.decimal128(18, 8)),
        _field("quote_volume", pa.decimal128(18, 8)),
        _field("trade_count", pa.int64()),
        _field("vwap", pa.decimal128(18, 8)),
        _field("event_date", pa.date32()),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
        _field("updated_at", pa.timestamp("us", tz="UTC")),
    ]
)

QUARANTINE_ARROW_SCHEMA = pa.schema(
    [
        _field("quarantine_id", pa.large_string()),
        _field("reason", pa.large_string()),
        _field("source", pa.large_string()),
        _field("symbol", pa.large_string(), nullable=True),
        _field("trade_id", pa.int64(), nullable=True),
        _field("event_ts", pa.timestamp("us", tz="UTC"), nullable=True),
        _field("ingest_ts", pa.timestamp("us", tz="UTC"), nullable=True),
        _field("payload_hash", pa.large_string(), nullable=True),
        _field("raw_payload", pa.large_string()),
        _field("topic", pa.large_string()),
        _field("partition", pa.int32(), nullable=True),
        _field("offset", pa.int64(), nullable=True),
        _field("detected_at", pa.timestamp("us", tz="UTC")),
        _field("event_date", pa.date32()),
        _field("details", pa.large_string(), nullable=True),
    ]
)


def _s3_properties(settings: Settings) -> dict[str, str]:
    access_key, secret_key = settings.minio_credentials("process")
    return {
        "s3.endpoint": settings.minio_endpoint,
        "s3.access-key-id": access_key,
        "s3.secret-access-key": secret_key,
        "s3.region": settings.minio_region,
        "s3.path-style-access": "true",
        "s3.remote-signing-enabled": "false",
    }


def _date_filter(dates: list[date]):
    unique = sorted(set(dates))
    if len(unique) == 1:
        return EqualTo("event_date", unique[0])
    return Or(*[EqualTo("event_date", value) for value in unique])


def _trade_to_row(trade: MarketTrade) -> dict[str, Any]:
    return {
        "symbol": trade.symbol,
        "trade_id": trade.trade_id,
        "event_ts": trade.event_ts,
        "price": trade.price,
        "qty": trade.qty,
        "is_buyer_maker": trade.is_buyer_maker,
        "ingest_ts": trade.ingest_ts,
        "source": trade.source,
        "payload_hash": trade.payload_hash,
        "event_date": trade.event_date,
    }


def _row_to_trade(row: dict[str, Any]) -> MarketTrade:
    return MarketTrade(
        symbol=str(row["symbol"]),
        trade_id=int(row["trade_id"]),
        event_ts=utc_datetime(row["event_ts"]),
        price=Decimal(row["price"]),
        qty=Decimal(row["qty"]),
        is_buyer_maker=bool(row["is_buyer_maker"]),
        ingest_ts=utc_datetime(row["ingest_ts"]),
        source=str(row["source"]),
        payload_hash=str(row["payload_hash"]),
    )


@dataclass(frozen=True)
class SilverFreshness:
    observed_at: datetime
    latest_event_ts: datetime | None
    latest_window_end: datetime | None
    ingest_lag_seconds: float | None
    bar_age_seconds: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "latest_event_ts": _iso(self.latest_event_ts),
            "latest_window_end": _iso(self.latest_window_end),
            "ingest_lag_seconds": self.ingest_lag_seconds,
            "bar_age_seconds": self.bar_age_seconds,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def compute_silver_freshness(
    trades: list[dict[str, Any]],
    bars: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> SilverFreshness:
    observed_at = now or datetime.now(UTC)
    event_times = [utc_datetime(row["event_ts"]) for row in trades]
    window_ends = [utc_datetime(row["window_end"]) for row in bars]
    latest_event_ts = max(event_times) if event_times else None
    latest_window_end = max(window_ends) if window_ends else None
    latest_lags = [
        max((utc_datetime(row["ingest_ts"]) - utc_datetime(row["event_ts"])).total_seconds(), 0.0)
        for row, event_ts in zip(trades, event_times, strict=False)
        if event_ts == latest_event_ts
    ]
    return SilverFreshness(
        observed_at=observed_at,
        latest_event_ts=latest_event_ts,
        latest_window_end=latest_window_end,
        ingest_lag_seconds=max(latest_lags) if latest_lags else None,
        bar_age_seconds=(
            max((observed_at - latest_window_end).total_seconds(), 0.0)
            if latest_window_end is not None
            else None
        ),
    )


def _quarantine_to_row(record: dict[str, Any]) -> dict[str, Any]:
    return {field.name: record.get(field.name) for field in QUARANTINE_ARROW_SCHEMA}


class SilverWriter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.catalog: Catalog = load_catalog(
            "lakekeeper",
            type="rest",
            uri=f"{settings.lakekeeper_url.rstrip('/')}/catalog",
            warehouse=settings.lakekeeper_warehouse,
            **_s3_properties(settings),
        )

    def _ensure_namespace(self, namespace: str) -> None:
        try:
            self.catalog.create_namespace(namespace)
        except NamespaceAlreadyExistsError:
            return

    def _table(self, identifier: str):
        table = self.catalog.load_table(identifier)
        table.io = load_file_io(_s3_properties(self.settings), table.location())
        return table

    def ensure_tables(self) -> None:
        for namespace in (SILVER_NAMESPACE, QUARANTINE_NAMESPACE):
            self._ensure_namespace(namespace)
        self.catalog.create_table_if_not_exists(
            TRADES_TABLE,
            schema=_iceberg_trades_schema(),
            location=TRADES_LOCATION,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=10,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )
        self.catalog.create_table_if_not_exists(
            OHLCV_TABLE,
            schema=_iceberg_ohlcv_schema(),
            location=OHLCV_LOCATION,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=12,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )
        self.catalog.create_table_if_not_exists(
            QUARANTINE_TABLE,
            schema=_iceberg_quarantine_schema(),
            location=QUARANTINE_LOCATION,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=14,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )

    def append_trades(self, trades: list[MarketTrade]) -> tuple[list[MarketTrade], int]:
        if not trades:
            return [], 0
        table = self._table(TRADES_TABLE)
        dates = [trade.event_date for trade in trades]
        existing = table.scan(row_filter=_date_filter(dates)).to_arrow().to_pylist()
        seen = {(str(row["symbol"]), int(row["trade_id"])) for row in existing}
        fresh: list[MarketTrade] = []
        for trade in trades:
            key = (trade.symbol, trade.trade_id)
            if key in seen:
                continue
            seen.add(key)
            fresh.append(trade)
        if fresh:
            table.append(
                pa.Table.from_pylist(
                    [_trade_to_row(trade) for trade in fresh],
                    schema=TRADES_ARROW_SCHEMA,
                )
            )
        return fresh, len(trades) - len(fresh)

    def recompute_ohlcv(self, trades: list[MarketTrade]) -> int:
        if not trades:
            return 0
        affected = {(trade.symbol, trade.window_start) for trade in trades}
        dates = sorted({trade.window_start.date() for trade in trades})
        rows = (
            self._table(TRADES_TABLE)
            .scan(row_filter=_date_filter(dates))
            .to_arrow()
            .to_pylist()
        )
        selected = [
            _row_to_trade(row)
            for row in rows
            if (str(row["symbol"]), utc_datetime(row["event_ts"]).replace(second=0, microsecond=0))
            in affected
        ]
        bars = aggregate_ohlcv(selected)
        table = self._table(OHLCV_TABLE)
        existing = table.scan(row_filter=_date_filter(dates)).to_arrow().to_pylist()
        for event_date in dates:
            keep = [
                row
                for row in existing
                if row["event_date"] == event_date
                and (
                    str(row["symbol"]),
                    utc_datetime(row["window_start"]).replace(second=0, microsecond=0),
                )
                not in affected
            ]
            fresh = [bar for bar in bars if bar["event_date"] == event_date]
            table.overwrite(
                pa.Table.from_pylist([*keep, *fresh], schema=OHLCV_ARROW_SCHEMA),
                overwrite_filter=EqualTo("event_date", event_date),
            )
        return len(bars)

    def append_quarantine(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        rows = [_quarantine_to_row(record) for record in records]
        table = self._table(QUARANTINE_TABLE)
        dates = [row["event_date"] for row in rows]
        existing = table.scan(row_filter=_date_filter(dates)).to_arrow().to_pylist()
        seen = {row["quarantine_id"] for row in existing}
        fresh = []
        for row in rows:
            if row["quarantine_id"] in seen:
                continue
            seen.add(row["quarantine_id"])
            fresh.append(row)
        if fresh:
            table.append(pa.Table.from_pylist(fresh, schema=QUARANTINE_ARROW_SCHEMA))
        return len(fresh)

    def fetch_ohlcv(self, symbol: str, window_start: datetime) -> list[dict[str, Any]]:
        table = self._table(OHLCV_TABLE)
        return (
            table.scan(
                row_filter=And(
                    EqualTo("symbol", symbol),
                    EqualTo("window_start", window_start),
                )
            )
            .to_arrow()
            .to_pylist()
        )

    def fetch_ohlcv_range(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        return (
            self._table(OHLCV_TABLE)
            .scan(
                row_filter=And(
                    EqualTo("symbol", symbol),
                    GreaterThanOrEqual("window_start", start),
                    LessThan("window_start", end),
                )
            )
            .to_arrow()
            .to_pylist()
        )

    def fetch_trades(self, symbol: str, event_date: date) -> list[dict[str, Any]]:
        rows = self._table(TRADES_TABLE).scan(row_filter=_date_filter([event_date])).to_arrow()
        return [row for row in rows.to_pylist() if row["symbol"] == symbol]

    def freshness(
        self,
        *,
        symbol: str | None = None,
        now: datetime | None = None,
    ) -> SilverFreshness:
        row_filter = EqualTo("symbol", symbol) if symbol is not None else None
        trades_table = self._table(TRADES_TABLE)
        bars_table = self._table(OHLCV_TABLE)
        trade_rows = (
            trades_table.scan(row_filter=row_filter).to_arrow().to_pylist()
            if row_filter is not None
            else trades_table.scan().to_arrow().to_pylist()
        )
        bar_rows = (
            bars_table.scan(row_filter=row_filter).to_arrow().to_pylist()
            if row_filter is not None
            else bars_table.scan().to_arrow().to_pylist()
        )
        return compute_silver_freshness(trade_rows, bar_rows, now=now)

    def fetch_quarantine(
        self,
        *,
        topic: str | None = None,
        reason: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = []
        if topic is not None:
            filters.append(EqualTo("topic", topic))
        if reason is not None:
            filters.append(EqualTo("reason", reason))
        row_filter = And(*filters) if len(filters) > 1 else (filters[0] if filters else None)
        table = self._table(QUARANTINE_TABLE)
        try:
            scan = table.scan(row_filter=row_filter) if row_filter is not None else table.scan()
            return scan.to_arrow().to_pylist()
        except Exception as exc:
            log.warning("quarantine read failed", extra={"ctx_error": str(exc)})
            return []

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for identifier in (TRADES_TABLE, OHLCV_TABLE, QUARANTINE_TABLE):
            try:
                result[identifier] = len(self._table(identifier).scan().to_arrow())
            except Exception:
                result[identifier] = 0
        return result


class MarketSink:
    def __init__(self, settings: Settings) -> None:
        self.writer = SilverWriter(settings)
        self.writer.ensure_tables()
        self.dlq = DlqPublisher(settings)

    def persist(
        self,
        trades: list[MarketTrade],
        rejected: list[dict[str, Any]],
    ) -> SinkStats:
        self.dlq.publish(rejected)
        fresh, duplicates = self.writer.append_trades(trades)
        bars = self.writer.recompute_ohlcv(fresh)
        quarantined = self.writer.append_quarantine(rejected)
        return SinkStats(
            accepted=len(fresh),
            duplicates=duplicates,
            quarantined=quarantined,
            ohlcv_rows=bars,
        )

    def freshness(self, *, symbol: str | None = None) -> SilverFreshness:
        return self.writer.freshness(symbol=symbol)
