"""Command line entry point for market and social ingestion."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from bmip.common.config import get_settings
from bmip.common.logging import configure_logging, get_logger
from bmip.ingestion.feeds import (
    collect_binance_ws,
    download_binance_vision_day,
    iter_binance_vision_csv,
    iter_bluesky_search,
    iter_static_market,
    iter_static_social,
    watermark_since,
)
from bmip.ingestion.ledger import get_watermark
from bmip.ingestion.pipeline import run_market_batch, run_social_batch

log = get_logger(__name__)


def _market_items(args: argparse.Namespace, settings: Any) -> list[dict[str, Any]]:
    if args.replay:
        return list(iter_static_market(Path(args.replay)))[: args.max_records]
    if args.vision:
        archive = download_binance_vision_day(
            args.vision,
            settings.market_symbol,
            Path("data/replay"),
            settings.binance_vision_base_url,
        )
        return list(
            iter_binance_vision_csv(
                archive,
                settings.market_symbol,
                max_records=args.max_records,
                speed=args.speed,
            )
        )
    if args.live:
        return collect_binance_ws(
            settings.market_ws_url,
            settings.market_symbol,
            max_records=args.max_records,
        )
    if settings.market_feed == "binance_vision":
        return list(iter_static_market(Path(settings.market_replay_file)))[: args.max_records]
    return collect_binance_ws(
        settings.market_ws_url,
        settings.market_symbol,
        max_records=args.max_records,
    )


def _social_items(args: argparse.Namespace, settings: Any) -> list[dict[str, Any]]:
    if args.replay:
        return list(iter_static_social(Path(args.replay)))
    if args.live:
        watermark = get_watermark(settings.postgres_dsn, "bluesky")
        return list(
            iter_bluesky_search(
                settings.social_query,
                limit=args.limit,
                max_pages=args.max_pages,
                since=watermark_since(watermark),
                base_url=settings.bluesky_base_url,
                cache_dir=Path("data/cache/bluesky"),
            )
        )
    if settings.social_feed == "replay":
        return list(iter_static_social(Path(settings.social_replay_file)))
    watermark = get_watermark(settings.postgres_dsn, "bluesky")
    return list(
        iter_bluesky_search(
            settings.social_query,
            limit=args.limit,
            max_pages=args.max_pages,
            since=watermark_since(watermark),
            base_url=settings.bluesky_base_url,
            cache_dir=Path("data/cache/bluesky"),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BMIP ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    market = subparsers.add_parser("market", help="ingest Binance aggregate trades")
    market.add_argument("--live", action="store_true", help="read the Binance WebSocket")
    market.add_argument("--vision", metavar="YYYY-MM-DD", help="download a Binance Vision day")
    market.add_argument("--replay", type=Path, help="read an aggTrade JSONL fixture")
    market.add_argument("--max-records", type=int, default=5)
    market.add_argument("--speed", type=float, default=0.0, help="replay rows per second")
    market.add_argument("--no-kafka", action="store_true", help="skip publishing to Redpanda")

    social = subparsers.add_parser("social", help="harvest Bluesky posts")
    social.add_argument("--live", action="store_true", help="call the Bluesky search API")
    social.add_argument("--replay", type=Path, help="read a Bluesky JSON fixture")
    social.add_argument("--max-pages", type=int, default=None)
    social.add_argument("--limit", type=int, default=100)
    social.add_argument(
        "--interval",
        type=int,
        default=0,
        help="repeat the harvest every N seconds (0 = run once)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    args = build_parser().parse_args(argv)
    settings = get_settings()

    try:
        if args.command == "market":
            items = _market_items(args, settings)
            result = run_market_batch(settings, items, publish=not args.no_kafka)
            print(json.dumps({"market": result.as_dict()}, indent=2))
        else:
            args.max_pages = args.max_pages or settings.social_max_pages
            while True:
                try:
                    items = _social_items(args, settings)
                    result = run_social_batch(settings, items)
                    print(json.dumps({"social": result.as_dict()}, indent=2))
                except Exception as exc:
                    log.exception("ingestion failed")
                    print(
                        json.dumps({"status": "failed", "error": str(exc)}),
                        file=sys.stderr,
                    )
                    if not args.interval:
                        return 1
                if not args.interval:
                    return 0
                try:
                    time.sleep(args.interval)
                except KeyboardInterrupt:
                    return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.exception("ingestion failed")
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
