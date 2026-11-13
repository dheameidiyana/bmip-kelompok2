"""Tests for silver Arrow/Iceberg row conversion without a live catalog."""

from __future__ import annotations

from datetime import UTC, datetime

import pyarrow as pa

from bmip.transform.market import aggregate_ohlcv, parse_trade, quarantine_record
from bmip.transform.silver import (
    OHLCV_ARROW_SCHEMA,
    QUARANTINE_ARROW_SCHEMA,
    TRADES_ARROW_SCHEMA,
    MarketSink,
    _quarantine_to_row,
    _row_to_trade,
    _trade_to_row,
    compute_silver_freshness,
)

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def _trade(trade_id: int = 1, event_ts: str = "2026-11-10T14:00:01.100Z"):
    raw = {
        "symbol": "BTCUSDT",
        "trade_id": trade_id,
        "event_ts": event_ts,
        "price": 68000.5,
        "qty": 0.01,
        "is_buyer_maker": False,
    }
    trade, error = parse_trade(raw, now=NOW)
    assert error is None
    assert trade is not None
    return trade


def test_trade_arrow_roundtrip() -> None:
    trade = _trade()

    table = pa.Table.from_pylist([_trade_to_row(trade)], schema=TRADES_ARROW_SCHEMA)
    restored = _row_to_trade(table.to_pylist()[0])

    assert restored.symbol == trade.symbol
    assert restored.trade_id == trade.trade_id
    assert restored.price == trade.price
    assert restored.qty == trade.qty
    assert restored.event_ts == trade.event_ts


def test_ohlcv_arrow_schema_accepts_aggregate() -> None:
    bars = aggregate_ohlcv([_trade()], updated_at=NOW)

    table = pa.Table.from_pylist(bars, schema=OHLCV_ARROW_SCHEMA)

    assert table.num_rows == 1
    assert table.to_pylist()[0]["trade_count"] == 1


def test_quarantine_arrow_schema_accepts_record() -> None:
    record = quarantine_record(
        "malformed_json",
        "{oops",
        topic="market.trades",
        partition=0,
        offset=7,
    )

    table = pa.Table.from_pylist(
        [_quarantine_to_row(record)],
        schema=QUARANTINE_ARROW_SCHEMA,
    )

    restored = table.to_pylist()[0]
    assert restored["reason"] == "malformed_json"
    assert restored["raw_payload"] == "{oops"
    assert restored["offset"] == 7


class _FakeWriter:
    def __init__(self) -> None:
        self.appended: list[object] = []
        self.quarantine: list[dict[str, object]] = []
        self.recomputed: list[object] = []

    def append_trades(self, trades):
        self.appended.extend(trades)
        return trades, 1

    def recompute_ohlcv(self, trades):
        self.recomputed.extend(trades)
        return 1

    def append_quarantine(self, records):
        self.quarantine.extend(records)
        return len(records)


class _FakeDlq:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def publish(self, records):
        self.records.extend(records)


def test_compute_silver_freshness_uses_ingest_lag_and_bar_age() -> None:
    trades = [
        {
            "event_ts": "2026-11-13T00:00:10Z",
            "ingest_ts": "2026-11-13T00:00:12Z",
        },
        {
            "event_ts": "2026-11-13T00:00:40Z",
            "ingest_ts": "2026-11-13T00:00:43Z",
        },
    ]
    bars = [{"window_end": "2026-11-13T00:01:00Z"}]

    freshness = compute_silver_freshness(
        trades,
        bars,
        now=datetime(2026, 11, 13, 0, 1, 30, tzinfo=UTC),
    )

    assert freshness.latest_event_ts == datetime(2026, 11, 13, 0, 0, 40, tzinfo=UTC)
    assert freshness.latest_window_end == datetime(2026, 11, 13, 0, 1, tzinfo=UTC)
    assert freshness.ingest_lag_seconds == 3.0
    assert freshness.bar_age_seconds == 30.0
    assert freshness.to_dict()["ingest_lag_seconds"] == 3.0


def test_compute_silver_freshness_handles_empty_rows() -> None:
    freshness = compute_silver_freshness([], [], now=NOW)

    assert freshness.latest_event_ts is None
    assert freshness.latest_window_end is None
    assert freshness.ingest_lag_seconds is None
    assert freshness.bar_age_seconds is None


def test_market_sink_composes_writers() -> None:
    sink = object.__new__(MarketSink)
    sink.writer = _FakeWriter()
    sink.dlq = _FakeDlq()
    rejected = [{"reason": "malformed_json", "quarantine_id": "x"}]

    stats = sink.persist([_trade()], rejected)

    assert stats.accepted == 1
    assert stats.duplicates == 1
    assert stats.quarantined == 1
    assert stats.ohlcv_rows == 1
    assert sink.dlq.records == rejected
    assert sink.writer.quarantine == rejected
