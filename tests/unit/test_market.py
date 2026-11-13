"""Tests for pure silver market transforms."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from bmip.transform.market import (
    MarketTrade,
    aggregate_ohlcv,
    classify_late,
    compute_watermark,
    dedupe_trades,
    parse_trade,
    quarantine_record,
)

BASE = datetime(2026, 11, 10, 14, 0, 1, tzinfo=UTC)


def _raw(
    trade_id: int,
    *,
    event_ts: str = "2026-11-10T14:00:01.100Z",
    price: float = 68000.5,
    qty: float = 0.01,
    symbol: str = "BTCUSDT",
    is_buyer_maker: bool = False,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_id": trade_id,
        "event_ts": event_ts,
        "price": price,
        "qty": qty,
        "is_buyer_maker": is_buyer_maker,
        "ingest_ts": event_ts,
        "source": "binance_vision",
        "payload_hash": "a" * 64,
    }


def _trade(
    trade_id: int,
    *,
    event_ts: datetime = BASE,
    price: str = "68000.50",
    qty: str = "0.01",
) -> MarketTrade:
    return MarketTrade(
        symbol="BTCUSDT",
        trade_id=trade_id,
        event_ts=event_ts,
        price=Decimal(price),
        qty=Decimal(qty),
        is_buyer_maker=False,
        ingest_ts=event_ts,
        source="test",
        payload_hash="a" * 64,
    )


def test_parse_trade_accepts_valid_event() -> None:
    trade, error = parse_trade(_raw(1), now=BASE)

    assert error is None
    assert trade is not None
    assert trade.symbol == "BTCUSDT"
    assert trade.price == Decimal("68000.5")
    assert trade.window_start == datetime(2026, 11, 10, 14, 0, tzinfo=UTC)


def test_parse_trade_rejects_bad_price_and_symbol() -> None:
    trade, error = parse_trade(_raw(1, price=-1), now=BASE)
    assert trade is None
    assert error == "invalid_price"

    trade, error = parse_trade(
        _raw(2, symbol="ETHUSDT"),
        allowed_symbols={"BTCUSDT"},
        now=BASE,
    )
    assert trade is None
    assert error == "unsupported_symbol:ETHUSDT"


def test_parse_trade_rejects_future_event() -> None:
    trade, error = parse_trade(
        _raw(1, event_ts="2026-11-10T14:10:00Z"),
        now=BASE,
    )

    assert trade is None
    assert error == "future_event"


def test_dedupe_trades_keeps_first_occurrence() -> None:
    first = _trade(1, price="100")
    second = _trade(1, price="200")
    other = _trade(2, price="300")

    unique, duplicates = dedupe_trades([first, second, other])

    assert duplicates == 1
    assert [trade.trade_id for trade in unique] == [1, 2]
    assert unique[0].price == Decimal("100")


def test_watermark_is_delayed_and_monotonic() -> None:
    trades = [_trade(1, event_ts=BASE), _trade(2, event_ts=BASE + timedelta(seconds=5))]

    watermark = compute_watermark(trades, timedelta(seconds=2))
    assert watermark == BASE + timedelta(seconds=3)

    kept = compute_watermark(
        [_trade(3, event_ts=BASE)],
        timedelta(seconds=2),
        previous=watermark,
    )
    assert kept == watermark


def test_classify_late_uses_correction_window() -> None:
    watermark = BASE + timedelta(minutes=10)

    recent = _trade(1, event_ts=BASE + timedelta(minutes=5))
    assert classify_late(recent, watermark, timedelta(minutes=30)) is None
    assert (
        classify_late(
            _trade(2, event_ts=BASE - timedelta(minutes=25)),
            watermark,
            timedelta(minutes=30),
        )
        == "late_beyond_window"
    )


def test_aggregate_ohlcv_matches_hand_calculation() -> None:
    trades = [
        _trade(1, event_ts=BASE, price="68000.50", qty="0.01"),
        _trade(2, event_ts=BASE + timedelta(seconds=1), price="68001.25", qty="0.02"),
        _trade(3, event_ts=BASE + timedelta(seconds=2), price="67999.75", qty="0.01"),
    ]

    bars = aggregate_ohlcv(trades, updated_at=BASE + timedelta(seconds=10))

    assert len(bars) == 1
    bar = bars[0]
    assert bar["open"] == Decimal("68000.50")
    assert bar["high"] == Decimal("68001.25")
    assert bar["low"] == Decimal("67999.75")
    assert bar["close"] == Decimal("67999.75")
    assert bar["volume"] == Decimal("0.04000000")
    assert bar["quote_volume"] == Decimal("2720.02750000")
    assert bar["vwap"] == Decimal("68000.68750000")
    assert bar["trade_count"] == 3
    assert bar["event_date"].isoformat() == "2026-11-10"


def test_quarantine_record_is_traceable() -> None:
    record = quarantine_record(
        "malformed_json",
        "{oops",
        topic="market.trades",
        partition=1,
        offset=42,
        details="invalid json",
    )

    assert record["reason"] == "malformed_json"
    assert record["topic"] == "market.trades"
    assert record["partition"] == 1
    assert record["offset"] == 42
    assert record["raw_payload"] == "{oops"
    assert len(record["quarantine_id"]) == 64
