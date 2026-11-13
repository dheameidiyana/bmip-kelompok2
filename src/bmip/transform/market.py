"""Pure event-time market transforms used by the stream processor."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from bmip.ingestion.hashing import payload_hash

ONE_MINUTE = timedelta(minutes=1)
MAX_FUTURE_SKEW = timedelta(minutes=2)
QUANT = Decimal("0.00000001")
QUARANTINE_PAYLOAD_LIMIT = 64_000


@dataclass(frozen=True)
class MarketTrade:
    symbol: str
    trade_id: int
    event_ts: datetime
    price: Decimal
    qty: Decimal
    is_buyer_maker: bool
    ingest_ts: datetime
    source: str
    payload_hash: str

    @property
    def window_start(self) -> datetime:
        return self.event_ts.replace(second=0, microsecond=0)

    @property
    def event_date(self):
        return self.event_ts.date()


@dataclass(frozen=True)
class SinkStats:
    accepted: int = 0
    duplicates: int = 0
    quarantined: int = 0
    ohlcv_rows: int = 0


def utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp is not a datetime or string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_trade(
    raw: dict[str, Any],
    *,
    allowed_symbols: set[str] | None = None,
    now: datetime | None = None,
) -> tuple[MarketTrade | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not_an_object"
    for field in ("symbol", "trade_id", "event_ts", "price", "qty", "is_buyer_maker"):
        if raw.get(field) in (None, ""):
            return None, f"missing_field:{field}"

    symbol = str(raw["symbol"]).strip().upper()
    if allowed_symbols is not None and symbol not in allowed_symbols:
        return None, f"unsupported_symbol:{symbol}"

    try:
        trade_id = int(raw["trade_id"])
    except (TypeError, ValueError):
        return None, "invalid_trade_id"
    if trade_id <= 0:
        return None, "invalid_trade_id"

    try:
        event_ts = utc_datetime(raw["event_ts"])
    except (TypeError, ValueError):
        return None, "invalid_event_ts"
    current = now or datetime.now(UTC)
    if event_ts > current + MAX_FUTURE_SKEW:
        return None, "future_event"

    try:
        price = Decimal(str(raw["price"]))
        qty = Decimal(str(raw["qty"]))
    except (InvalidOperation, TypeError, ValueError):
        return None, "invalid_decimal"
    if not price.is_finite() or price <= 0:
        return None, "invalid_price"
    if not qty.is_finite() or qty <= 0:
        return None, "invalid_qty"

    is_buyer_maker = raw["is_buyer_maker"]
    if not isinstance(is_buyer_maker, bool):
        return None, "invalid_is_buyer_maker"

    try:
        ingest_ts = utc_datetime(raw.get("ingest_ts") or current)
    except (TypeError, ValueError):
        return None, "invalid_ingest_ts"

    source = str(raw.get("source") or "unknown")
    computed_hash = str(raw.get("payload_hash") or "")
    if len(computed_hash) != 64:
        computed_hash = payload_hash(raw)

    return (
        MarketTrade(
            symbol=symbol,
            trade_id=trade_id,
            event_ts=event_ts,
            price=price,
            qty=qty,
            is_buyer_maker=is_buyer_maker,
            ingest_ts=ingest_ts,
            source=source,
            payload_hash=computed_hash,
        ),
        None,
    )


def dedupe_trades(trades: list[MarketTrade]) -> tuple[list[MarketTrade], int]:
    seen: set[tuple[str, int]] = set()
    unique: list[MarketTrade] = []
    duplicates = 0
    for trade in trades:
        key = (trade.symbol, trade.trade_id)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        unique.append(trade)
    return unique, duplicates


def compute_watermark(
    trades: list[MarketTrade],
    delay: timedelta,
    previous: datetime | None = None,
) -> datetime | None:
    if not trades:
        return previous
    candidate = max(trade.event_ts for trade in trades) - delay
    return candidate if previous is None else max(previous, candidate)


def classify_late(
    trade: MarketTrade,
    watermark: datetime | None,
    correction_window: timedelta,
) -> str | None:
    if watermark is None:
        return None
    if trade.event_ts < watermark - correction_window:
        return "late_beyond_window"
    return None


def aggregate_ohlcv(
    trades: list[MarketTrade],
    updated_at: datetime | None = None,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, datetime], list[MarketTrade]] = {}
    for trade in trades:
        groups.setdefault((trade.symbol, trade.window_start), []).append(trade)

    stamp = updated_at or datetime.now(UTC)
    bars: list[dict[str, Any]] = []
    for (symbol, window_start), group in sorted(groups.items()):
        ordered = sorted(group, key=lambda trade: (trade.event_ts, trade.trade_id))
        volume = sum((trade.qty for trade in ordered), Decimal("0"))
        quote_volume = sum((trade.price * trade.qty for trade in ordered), Decimal("0"))
        vwap = (quote_volume / volume).quantize(QUANT) if volume else Decimal("0")
        bars.append(
            {
                "symbol": symbol,
                "window_start": window_start,
                "window_end": window_start + ONE_MINUTE,
                "open": ordered[0].price,
                "high": max(trade.price for trade in ordered),
                "low": min(trade.price for trade in ordered),
                "close": ordered[-1].price,
                "volume": volume.quantize(QUANT),
                "quote_volume": quote_volume.quantize(QUANT),
                "trade_count": len(ordered),
                "vwap": vwap,
                "event_date": window_start.date(),
                "ingest_ts": max(trade.ingest_ts for trade in ordered),
                "updated_at": stamp,
            }
        )
    return bars


def quarantine_record(
    reason: str,
    raw_payload: str,
    *,
    raw: dict[str, Any] | None = None,
    topic: str,
    partition: int | None = None,
    offset: int | None = None,
    source: str | None = None,
    details: str | None = None,
    detected_at: datetime | None = None,
) -> dict[str, Any]:
    detected = detected_at or datetime.now(UTC)
    event_ts = None
    ingest_ts = None
    if raw:
        if raw.get("event_ts") is not None:
            try:
                event_ts = utc_datetime(raw["event_ts"])
            except (TypeError, ValueError):
                event_ts = None
        if raw.get("ingest_ts") is not None:
            try:
                ingest_ts = utc_datetime(raw["ingest_ts"])
            except (TypeError, ValueError):
                ingest_ts = None
        source = source or raw.get("source")

    event_date = event_ts.date() if event_ts is not None else detected.date()
    identifier = hashlib.sha256(
        f"{topic}:{partition}:{offset}:{reason}".encode()
    ).hexdigest()
    trade_id = None
    if raw and raw.get("trade_id") is not None:
        try:
            trade_id = int(raw["trade_id"])
        except (TypeError, ValueError):
            trade_id = None
    return {
        "quarantine_id": identifier,
        "reason": reason,
        "source": str(source or "unknown"),
        "symbol": str(raw["symbol"]) if raw and raw.get("symbol") is not None else None,
        "trade_id": trade_id,
        "event_ts": event_ts,
        "ingest_ts": ingest_ts,
        "payload_hash": payload_hash(raw) if raw else None,
        "raw_payload": raw_payload[:QUARANTINE_PAYLOAD_LIMIT],
        "topic": topic,
        "partition": partition,
        "offset": offset,
        "detected_at": detected,
        "event_date": event_date,
        "details": details,
    }
