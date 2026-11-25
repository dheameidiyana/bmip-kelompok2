"""Binance Vision 1-minute kline backfill into silver.market_ohlcv_1m."""

from __future__ import annotations

import csv
import io
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.ingestion.feeds import epoch_to_datetime
from bmip.transform.silver import SilverWriter

log = get_logger(__name__)

QUANT = Decimal("0.00000001")


def download_kline_day(
    day: date,
    symbol: str,
    cache_dir: Path,
    base_url: str,
) -> Path:
    filename = f"{symbol}-1m-{day.isoformat()}.zip"
    target = cache_dir / symbol / filename
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = (
        f"{base_url.rstrip('/')}/data/spot/daily/klines/"
        f"{symbol}/1m/{filename}"
    )
    log.info("downloading Binance kline day", extra={"ctx_url": url})
    with urllib.request.urlopen(url, timeout=60) as response:
        target.write_bytes(response.read())
    return target


def iter_kline_zip(path: Path, symbol: str) -> Iterator[dict[str, Any]]:
    stamp = datetime.now(UTC)
    with zipfile.ZipFile(path) as archive:
        name = next(
            (item for item in archive.namelist() if item.endswith(".csv")),
            None,
        )
        if name is None:
            raise ValueError(f"{path} contains no CSV file")
        with archive.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8")
            for values in csv.reader(text):
                if not values or values[0].strip().lower() == "open_time":
                    continue
                if len(values) < 9:
                    continue
                window_start = epoch_to_datetime(int(values[0]))
                volume = Decimal(values[5]).quantize(QUANT)
                trade_count = int(values[8])
                if volume <= 0 or trade_count <= 0:
                    continue
                quote_volume = Decimal(values[7]).quantize(QUANT)
                vwap = (quote_volume / volume).quantize(QUANT)
                yield {
                    "symbol": symbol,
                    "window_start": window_start,
                    "window_end": window_start + timedelta(minutes=1),
                    "open": Decimal(values[1]).quantize(QUANT),
                    "high": Decimal(values[2]).quantize(QUANT),
                    "low": Decimal(values[3]).quantize(QUANT),
                    "close": Decimal(values[4]).quantize(QUANT),
                    "volume": volume,
                    "quote_volume": quote_volume,
                    "trade_count": trade_count,
                    "vwap": vwap,
                    "event_date": window_start.date(),
                    "ingest_ts": stamp,
                    "updated_at": stamp,
                }


def date_range(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def backfill_klines(
    settings: Settings,
    *,
    start: date,
    end: date,
    symbols: tuple[str, ...] | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    selected = tuple(symbols or settings.market_symbols)
    cache = cache_dir or Path("data/replay/klines")
    writer = SilverWriter(settings)
    writer.ensure_tables()
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for day in date_range(start, end):
        bars: list[dict[str, Any]] = []
        for symbol in selected:
            archive = download_kline_day(
                day,
                symbol,
                cache,
                settings.binance_vision_base_url,
            )
            day_bars = list(iter_kline_zip(archive, symbol))
            counts[symbol] += len(day_bars)
            bars.extend(day_bars)
        if bars:
            total += writer.upsert_ohlcv(bars)
        log.info(
            "backfilled kline day",
            extra={"ctx_date": day.isoformat(), "ctx_rows": len(bars)},
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols": list(selected),
        "rows": total,
        "counts": dict(counts),
        "cache_dir": str(cache),
    }
