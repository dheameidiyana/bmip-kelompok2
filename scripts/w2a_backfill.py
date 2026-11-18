"""Backfill Binance Vision 1-minute klines for the W2-A multi-symbol dataset."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from bmip.common.config import get_settings
from bmip.ml.backfill import backfill_klines

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START = date(2026, 9, 18)
DEFAULT_END = date(2026, 11, 16)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=parse_date, default=DEFAULT_START)
    parser.add_argument("--end", type=parse_date, default=DEFAULT_END)
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols; defaults to MARKET_SYMBOLS",
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("data/replay/klines"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    symbols = tuple(
        part.strip().upper() for part in args.symbols.split(",") if part.strip()
    ) or settings.market_symbols
    result = backfill_klines(
        settings,
        start=args.start,
        end=args.end,
        symbols=symbols,
        cache_dir=args.cache_dir,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or ROOT / "evidence" / "ml" / f"backfill_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
