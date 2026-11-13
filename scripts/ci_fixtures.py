#!/usr/bin/env python3
"""Build a synthetic silver lake for offline dbt and leakage tests.

The fixture is deliberately small and deterministic: four hours of one-minute
bars, three social posts across three hours (one hour is empty), and one trade
per minute. It never touches MinIO, Lakekeeper, or Redpanda, so T-09 and the
dbt tests can run on any machine.
"""

from __future__ import annotations

import math
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_START = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
ONE_MINUTE = timedelta(minutes=1)

MARKET_DDL = """
create table silver.market_ohlcv_1m (
    symbol varchar,
    window_start timestamptz,
    window_end timestamptz,
    open decimal(18, 8),
    high decimal(18, 8),
    low decimal(18, 8),
    close decimal(18, 8),
    volume decimal(18, 8),
    quote_volume decimal(18, 8),
    trade_count bigint,
    vwap decimal(18, 8),
    event_date date,
    ingest_ts timestamptz,
    updated_at timestamptz
)
"""

TRADES_DDL = """
create table silver.market_trades (
    symbol varchar,
    trade_id bigint,
    event_ts timestamptz,
    ingest_ts timestamptz,
    source varchar,
    payload_hash varchar,
    event_date date
)
"""

SOCIAL_POST_DDL = """
create table silver.social_post (
    post_key varchar,
    author_key varchar,
    event_ts timestamptz,
    ingest_ts timestamptz,
    lang varchar,
    text varchar,
    hashtags varchar[],
    like_count bigint,
    repost_count bigint,
    reply_count bigint,
    quote_count bigint,
    source varchar,
    payload_hash varchar,
    event_date date,
    updated_at timestamptz
)
"""

SOCIAL_SENTIMENT_DDL = """
create table silver.social_sentiment (
    post_key varchar,
    event_ts timestamptz,
    window_start timestamptz,
    ingest_ts timestamptz,
    sentiment_score double,
    sentiment_pos double,
    sentiment_neu double,
    sentiment_neg double,
    sentiment_label varchar,
    sentiment_model_version varchar,
    event_date date,
    updated_at timestamptz
)
"""

POSTS = (
    (
        "post-1",
        "author-1",
        0,
        "BTC looks strong today #bitcoin",
        0.62,
        0.5,
        0.5,
        0.0,
        "positive",
        10,
        2,
        1,
    ),
    (
        "post-2",
        "author-2",
        0,
        "Watching BTC volatility into the close",
        -0.40,
        0.0,
        0.7,
        0.3,
        "negative",
        4,
        1,
        0,
    ),
    (
        "post-3",
        "author-3",
        2,
        "Nothing to see here",
        0.00,
        0.0,
        1.0,
        0.0,
        "neutral",
        1,
        0,
        0,
    ),
)


def build_fixture_db(
    path: str | Path,
    *,
    start: datetime = DEFAULT_START,
    hours: int = 4,
    spike_from: datetime | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()

    connection = duckdb.connect(str(target))
    try:
        connection.execute("create schema if not exists silver")
        for ddl in (MARKET_DDL, TRADES_DDL, SOCIAL_POST_DDL, SOCIAL_SENTIMENT_DDL):
            connection.execute(ddl)

        bars = []
        trades = []
        previous_close = Decimal("100.00000000")
        for minute in range(hours * 60):
            window_start = start + minute * ONE_MINUTE
            price = 100.0 + 5.0 * math.sin(minute / 7.0)
            if spike_from is not None and window_start >= spike_from:
                price *= 3.0
            close = Decimal(f"{price:.8f}")
            open_ = previous_close
            high = max(open_, close) + Decimal("0.40000000")
            low = min(open_, close) - Decimal("0.40000000")
            volume = Decimal(f"{1.0 + (minute % 5) * 0.25:.8f}")
            quote_volume = (close * volume).quantize(Decimal("0.00000001"))
            bars.append(
                (
                    "BTCUSDT",
                    window_start,
                    window_start + ONE_MINUTE,
                    open_,
                    high,
                    low,
                    close,
                    volume,
                    quote_volume,
                    3,
                    close,
                    window_start.date(),
                    window_start + timedelta(seconds=5),
                    window_start + timedelta(seconds=10),
                )
            )
            trades.append(
                (
                    "BTCUSDT",
                    minute + 1,
                    window_start + timedelta(seconds=1),
                    window_start + timedelta(seconds=5),
                    "binance_vision",
                    f"{minute:064d}",
                    window_start.date(),
                )
            )
            previous_close = close

        connection.executemany(
            "insert into silver.market_ohlcv_1m values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            bars,
        )
        connection.executemany(
            "insert into silver.market_trades values (?, ?, ?, ?, ?, ?, ?)",
            trades,
        )

        posts = []
        sentiments = []
        for (
            post_key,
            author_key,
            hour_offset,
            text,
            score,
            pos,
            neu,
            neg,
            label,
            likes,
            reposts,
            replies,
        ) in POSTS:
            event_ts = start + timedelta(hours=hour_offset, minutes=5)
            window_start = event_ts.replace(minute=0, second=0, microsecond=0)
            ingest_ts = event_ts + timedelta(minutes=1)
            posts.append(
                (
                    post_key,
                    author_key,
                    event_ts,
                    ingest_ts,
                    "en",
                    text,
                    ["bitcoin"] if "bitcoin" in text else [],
                    likes,
                    reposts,
                    replies,
                    0,
                    "bluesky",
                    f"{post_key:0<64}"[:64],
                    event_ts.date(),
                    ingest_ts,
                )
            )
            sentiments.append(
                (
                    post_key,
                    event_ts,
                    window_start,
                    ingest_ts,
                    score,
                    pos,
                    neu,
                    neg,
                    label,
                    "vaderSentiment-3.3.2",
                    event_ts.date(),
                    ingest_ts,
                )
            )

        connection.executemany(
            "insert into silver.social_post values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            posts,
        )
        connection.executemany(
            "insert into silver.social_sentiment values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sentiments,
        )
    finally:
        connection.close()
    return target


def dbt_build(
    select: str,
    *,
    target: str = "ci",
    duckdb_path: str | Path | None = None,
    iceberg_path: str | Path | None = None,
    extra: list[str] | None = None,
) -> bool:
    """Run dbt in-process against the ci profile."""
    os.environ["DBT_CI_DUCKDB_PATH"] = str(
        duckdb_path or ROOT / "dbt" / "target" / "ci.duckdb"
    )
    os.environ["DBT_CI_ICEBERG_PATH"] = str(
        iceberg_path or ROOT / "dbt" / "target" / "ci_iceberg.duckdb"
    )
    from dbt.cli.main import dbtRunner

    command = [
        "build",
        "--project-dir",
        str(ROOT / "dbt"),
        "--profiles-dir",
        str(ROOT / "dbt"),
        "--target",
        target,
        "--select",
        select,
        *(extra or []),
    ]
    result = dbtRunner().invoke(command)
    return bool(result.success)


def read_mart(path: str | Path, table: str) -> list[dict]:
    # dbt keeps its DuckDB connection open in-process, so match its read-write mode.
    connection = duckdb.connect(str(path))
    try:
        return connection.execute(f'select * from gold."{table}"').to_arrow_table().to_pylist()
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else ROOT / "dbt" / "target" / "ci_iceberg.duckdb"
    build_fixture_db(path)
    print(f"fixture: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
