#!/usr/bin/env python3
"""Cut an event-time window out of a Binance Vision day into a replay file.

The replay file keeps the WebSocket aggTrade shape, so ``market --replay`` and
``market --live`` feed the identical parser. This is how a demo gets a real
hour of trades without inventing prices.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def build_window(
    *,
    day: str,
    start: datetime,
    end: datetime,
    output: Path,
    symbol: str = "BTCUSDT",
) -> dict:
    from bmip.ingestion.feeds import (
        download_binance_vision_day,
        iter_binance_vision_csv,
    )

    cache = ROOT / "data" / "cache" / "binance_vision"
    archive = download_binance_vision_day(day, symbol, cache)
    rows: list[str] = []
    for record in iter_binance_vision_csv(archive, symbol):
        event_ts = _parse(record["event_ts"])
        if event_ts >= end:
            break
        if event_ts < start:
            continue
        raw = record["_raw"]
        ws = {
            "e": "aggTrade",
            "E": int(raw["transact_time"]),
            "s": symbol,
            "a": int(raw["agg_trade_id"]),
            "p": str(raw["price"]),
            "q": str(raw["quantity"]),
            "f": int(raw["first_trade_id"]),
            "l": int(raw["last_trade_id"]),
            "T": int(raw["transact_time"]),
            "m": str(raw["is_buyer_maker"]).strip().lower() in {"true", "1", "t"},
        }
        rows.append(json.dumps(ws, separators=(",", ":")))

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return {
        "day": day,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": len(rows),
        "output": str(output.relative_to(ROOT)),
        "archive": str(archive.relative_to(ROOT)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Binance Vision replay window")
    parser.add_argument("--day", required=True, help="YYYY-MM-DD (UTC)")
    parser.add_argument("--start", required=True, help="ISO-8601 start, inclusive")
    parser.add_argument("--end", required=True, help="ISO-8601 end, exclusive")
    parser.add_argument("--output", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)

    result = build_window(
        day=args.day,
        start=_parse(args.start),
        end=_parse(args.end),
        output=ROOT / args.output,
        symbol=args.symbol,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
