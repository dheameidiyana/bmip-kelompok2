#!/usr/bin/env python3
"""Build the gold marts, enforce the quality gates, then publish to Iceberg."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _dbt(select: str) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_dbt import main as run_dbt  # noqa: PLC0415

    return run_dbt(["--select", select])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and publish the gold marts")
    parser.add_argument("--start", help="ISO-8601 window_start lower bound (backfill)")
    parser.add_argument("--end", help="ISO-8601 window_start upper bound (backfill)")
    args = parser.parse_args(argv)
    start = _parse_ts(args.start)
    end = _parse_ts(args.end)

    from bmip.common.config import get_settings
    from bmip.quality.checkpoint import run_scope
    from bmip.transform.gold import GoldWriter
    from bmip.transform.social_pipeline import build_silver_social

    social = build_silver_social(get_settings())
    print(f"silver social: {social['accepted']} posts, {social['duplicates']} duplicates")

    if _dbt("staging intermediate silver") != 0:
        print("silver build failed", file=sys.stderr)
        return 1

    silver = run_scope(get_settings(), scope="silver", warning_only=False)
    print(f"silver quality: {silver.status}")

    if _dbt("marts") != 0:
        print("gold build failed", file=sys.stderr)
        return 1

    duckdb_path = ROOT / "dbt" / "target" / "bmip.duckdb"
    gold = run_scope(
        get_settings(),
        scope="gold",
        warning_only=False,
        duckdb_path=duckdb_path,
    )
    print(f"gold quality: {gold.status}")

    writer = GoldWriter(get_settings())
    writer.ensure_tables()
    for result in writer.publish_from_duckdb(duckdb_path, start=start, end=end):
        print(f"published {result.table}: rows={result.rows} partitions={result.partitions}")

    from bmip.serving.loader import load_serving

    serving = load_serving(get_settings(), start=start, end=end)
    print(
        "serving: "
        f"market={serving.market_rows} sentiment={serving.sentiment_rows} "
        f"registry={serving.registry_rows} hash={serving.logical_hash[:12]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
