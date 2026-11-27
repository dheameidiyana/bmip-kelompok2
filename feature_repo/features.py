"""Feast entities and feature views for the BMIP ML loop (C3-B)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource, ValueType
from feast.types import Float64, Int64

ROOT = Path(__file__).resolve().parents[1]
OFFLINE_PATH = ROOT / "data" / "feast" / "offline.parquet"
MARKET_HOURLY_PATH = ROOT / "data" / "feast" / "market_hourly.parquet"

MARKET_FEATURES = (
    "ret_5m",
    "ret_15m",
    "ret_60m",
    "rv_5m",
    "rv_15m",
    "rv_60m",
    "volume_z_60m",
    "trade_count_60m",
    "hl_range_1m",
    "vwap_dev",
)
SENTIMENT_FEATURES = (
    "sent_mean_1h",
    "sent_pos_share",
    "sent_neg_share",
    "post_count_1h",
    "engagement_1h",
)
MARKET_HOURLY_FEATURES = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
    "vwap",
    "log_return_1h",
    "realized_vol_1h",
    "rv_ewma_24h",
)

symbol = Entity(
    name="symbol",
    join_keys=["symbol"],
    value_type=ValueType.STRING,
    description="Binance spot USDT trading pair.",
)

offline_source = FileSource(
    name="bmip_mart_ml_offline",
    path=str(OFFLINE_PATH),
    timestamp_field="window_start",
)

market_features_1m = FeatureView(
    name="market_features_1m",
    entities=[symbol],
    ttl=timedelta(hours=1),
    schema=[
        *[
            Field(
                name=name,
                dtype=Int64 if name == "trade_count_60m" else Float64,
            )
            for name in MARKET_FEATURES
        ],
        Field(name="feature_ts_epoch", dtype=Int64),
    ],
    source=offline_source,
    online=True,
)

sentiment_1h = FeatureView(
    name="sentiment_1h",
    entities=[symbol],
    ttl=timedelta(hours=2),
    schema=[
        Field(name="sent_mean_1h", dtype=Float64),
        Field(name="sent_pos_share", dtype=Float64),
        Field(name="sent_neg_share", dtype=Float64),
        Field(name="post_count_1h", dtype=Float64),
        Field(name="engagement_1h", dtype=Float64),
    ],
    source=offline_source,
    online=True,
)

market_hourly_source = FileSource(
    name="bmip_market_hourly_offline",
    path=str(MARKET_HOURLY_PATH),
    timestamp_field="window_start",
)

market_hourly = FeatureView(
    name="market_hourly",
    entities=[symbol],
    ttl=timedelta(hours=2),
    schema=[
        Field(name="open", dtype=Float64),
        Field(name="high", dtype=Float64),
        Field(name="low", dtype=Float64),
        Field(name="close", dtype=Float64),
        Field(name="volume", dtype=Float64),
        Field(name="quote_volume", dtype=Float64),
        Field(name="trade_count", dtype=Int64),
        Field(name="vwap", dtype=Float64),
        Field(name="log_return_1h", dtype=Float64),
        Field(name="realized_vol_1h", dtype=Float64),
        Field(name="rv_ewma_24h", dtype=Float64),
    ],
    source=market_hourly_source,
    online=True,
)
