#!/usr/bin/env python3
"""Build the gold marts, enforce the quality gates, then publish to Iceberg.

W2-B wraps the run in a metrics batch: duration, rows per mart, and the gold
lag are pushed to the Pushgateway when ``PUSHGATEWAY_URL`` is set. The push is
best-effort; a missing gateway never fails a build.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _gold_lag_seconds(report: Any) -> float | None:
    """Read the lag the gold gate already measured, so there is one number."""
    for suite in report.suites:
        for rule in suite.rules:
            if rule.id == "gold-market-lag" and isinstance(rule.observed, dict):
                minutes = rule.observed.get("lag_minutes")
                if minutes is not None:
                    return float(minutes) * 60.0
    return None


def _build(start: datetime | None, end: datetime | None, registry) -> None:
    from bmip.common.config import get_settings
    from bmip.quality.checkpoint import run_scope
    from bmip.transform.gold import GoldWriter
    from bmip.transform.social_pipeline import build_silver_social

    settings = get_settings()
    social = build_silver_social(settings)
    print(f"silver social: {social['accepted']} posts, {social['duplicates']} duplicates")

    if _dbt("staging intermediate silver") != 0:
        raise RuntimeError("silver build failed")

    silver = run_scope(settings, scope="silver", warning_only=False)
    print(f"silver quality: {silver.status}")

    if _dbt("marts") != 0:
        raise RuntimeError("gold build failed")

    duckdb_path = ROOT / "dbt" / "target" / "bmip.duckdb"
    gold = run_scope(
        settings,
        scope="gold",
        warning_only=False,
        duckdb_path=duckdb_path,
    )
    print(f"gold quality: {gold.status}")

    lag = _gold_lag_seconds(gold)
    if lag is not None:
        registry.set(
            "bmip_freshness_seconds",
            lag,
            {"layer": "gold", "dataset": "market"},
            help="Seconds gold trails silver.market_ohlcv_1m.",
        )

    writer = GoldWriter(settings)
    writer.ensure_tables()
    for result in writer.publish_from_duckdb(duckdb_path, start=start, end=end):
        print(f"published {result.table}: rows={result.rows} partitions={result.partitions}")
        registry.set(
            "bmip_gold_rows",
            result.rows,
            {"table": result.table},
            help="Rows written to the mart by the last publish.",
        )

    from bmip.serving.loader import load_serving

    serving = load_serving(settings, start=start, end=end)
    print(
        "serving: "
        f"market={serving.market_rows} sentiment={serving.sentiment_rows} "
        f"registry={serving.registry_rows} hash={serving.logical_hash[:12]}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and publish the gold marts")
    parser.add_argument("--start", help="ISO-8601 window_start lower bound (backfill)")
    parser.add_argument("--end", help="ISO-8601 window_start upper bound (backfill)")
    args = parser.parse_args(argv)
    start = _parse_ts(args.start)
    end = _parse_ts(args.end)

    from bmip.observability import batch_run

    try:
        with batch_run("gold") as registry:
            _build(start, end, registry)
    except Exception as exc:  # noqa: BLE001 - the CLI turns every failure into exit 1
        print(f"gold build failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
