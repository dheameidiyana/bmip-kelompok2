"""Unit tests for the gold publisher contract (W1-C)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest

from bmip.transform.gold import (
    MARKET_ARROW_SCHEMA,
    MART_MARKET,
    MART_ML,
    MART_SENTIMENT,
    ML_ARROW_SCHEMA,
    SCHEMAS,
    SENTIMENT_ARROW_SCHEMA,
    coerce,
)


def _market_row():
    return {
        "event_date": date(2026, 11, 10),
        "symbol": "BTCUSDT",
        "window_start": datetime(2026, 11, 10, 1, tzinfo=UTC),
        "open": Decimal("100.00000000"),
        "high": Decimal("101.00000000"),
        "low": Decimal("99.00000000"),
        "close": Decimal("100.50000000"),
        "volume": Decimal("2.00000000"),
        "quote_volume": Decimal("201.00000000"),
        "trade_count": 10,
        "vwap": Decimal("100.50000000"),
        "log_return_1h": 0.01,
        "realized_vol_1h": 0.02,
        "rv_ewma_24h": 0.015,
        "source": "binance_vision",
        "updated_at": datetime(2026, 11, 10, 2, tzinfo=UTC),
    }


def test_schemas_are_partitioned_by_event_date():
    for identifier, (_, arrow_schema) in SCHEMAS.items():
        assert "event_date" in arrow_schema.names, identifier
    assert MARKET_ARROW_SCHEMA.names[0] == "symbol"
    assert SENTIMENT_ARROW_SCHEMA.names[0] == "window_start"
    assert ML_ARROW_SCHEMA.names[0] == "symbol"
    assert {"event_hour", "snapshot_id"} <= set(ML_ARROW_SCHEMA.names)


def test_coerce_reorders_and_casts_columns():
    row = _market_row()
    shuffled = pa.Table.from_pylist(
        [{key: row[key] for key in reversed(list(row))}],
    )
    result = coerce(shuffled, MARKET_ARROW_SCHEMA)
    assert result.column_names == MARKET_ARROW_SCHEMA.names
    assert result.schema.field("open").type == pa.decimal128(18, 8)
    assert result.column("trade_count").to_pylist() == [10]
    assert result.column("symbol").to_pylist() == ["BTCUSDT"]


def test_coerce_rejects_missing_contract_column():
    row = _market_row()
    row.pop("rv_ewma_24h")
    table = pa.Table.from_pylist([row])
    with pytest.raises(ValueError, match="rv_ewma_24h"):
        coerce(table, MARKET_ARROW_SCHEMA)


def test_mart_identifiers_are_gold_namespaced():
    assert MART_MARKET.startswith("gold.")
    assert MART_SENTIMENT.startswith("gold.")
    assert MART_ML.startswith("gold.")
