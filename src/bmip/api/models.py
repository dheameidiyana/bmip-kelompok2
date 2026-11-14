"""Pydantic contracts for the Query API (W1-D).

Naming rule: workplan routes are canonical, ARCHITECTURE route names are kept
as aliases. ``symbol`` defaults to BTCUSDT but is always validated against the
allowlist in ``Settings.market_symbols``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SYMBOL = "BTCUSDT"


class Meta(BaseModel):
    request_id: str
    instance: str
    source: Literal["serving", "lake", "memory"] = "serving"
    stale: bool = False
    clock: Literal["live", "replay"] = "live"
    as_of: datetime
    count: int | None = None
    next_cursor: str | None = None
    freshness: FreshnessOut | None = None


class FreshnessOut(BaseModel):
    metric: str
    data_ts: datetime | None = None
    age_seconds: float | None = None
    slo_seconds: int
    status: Literal["ok", "warn", "stale", "unknown"]
    as_of: datetime
    clock: Literal["live", "replay"] = "live"


class MarketBar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    window_start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int
    vwap: float
    log_return_1h: float | None = None
    realized_vol_1h: float | None = None
    rv_ewma_24h: float | None = None
    source: str
    event_date: date | None = None
    updated_at: datetime | None = None


class MarketLatestOut(BaseModel):
    data: MarketBar | None
    meta: Meta


class MarketBarPage(BaseModel):
    data: list[MarketBar]
    meta: Meta


class VolatilityPoint(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    window_start: datetime
    log_return_1h: float | None = None
    realized_vol_1h: float | None = None
    rv_ewma_24h: float | None = None


class VolatilityLatestOut(BaseModel):
    data: VolatilityPoint | None
    meta: Meta


class VolatilityPage(BaseModel):
    data: list[VolatilityPoint]
    meta: Meta


class SentimentHour(BaseModel):
    model_config = ConfigDict(extra="ignore")

    window_start: datetime
    post_count: int
    unique_authors: int
    mean_sentiment: float | None = None
    positive_share: float | None = None
    negative_share: float | None = None
    neutral_share: float | None = None
    total_likes: int = 0
    total_reposts: int = 0
    total_replies: int = 0
    engagement_per_post: float | None = None
    top_hashtags: list[str] = Field(default_factory=list)
    sentiment_model_version: str


class SentimentLatestOut(BaseModel):
    data: SentimentHour | None
    meta: Meta


class SentimentPage(BaseModel):
    data: list[SentimentHour]
    meta: Meta


class FreshnessListOut(BaseModel):
    data: list[FreshnessOut]
    meta: Meta


class DatasetOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    layer: str
    domain: str
    kind: str
    location: str
    description: str
    owner: str
    classification: str
    retention_days: int
    refresh_schedule: str | None = None
    sla: str | None = None
    license: str | None = None
    contains_pii: bool = False
    tags: list[str] = Field(default_factory=list)


class DatasetPage(BaseModel):
    data: list[DatasetOut]
    meta: Meta


class ColumnOut(BaseModel):
    name: str
    type: str
    required: bool
    doc: str | None = None


class DatasetSchemaOut(BaseModel):
    dataset: DatasetOut
    columns: list[ColumnOut]
    schema_source: Literal["iceberg", "postgres", "registry", "unavailable"]
    meta: Meta


class QualityFailure(BaseModel):
    suite: str
    rule_id: str
    severity: str
    status: str
    detail: str | None = None
    observed: Any = None
    expected: str | None = None


class QualityOut(BaseModel):
    data: dict[str, Any]
    meta: Meta


class ModelOut(BaseModel):
    status: Literal["available", "not_available"]
    model_name: str
    version: str | None = None
    alias: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    detail: str | None = None
    meta: Meta


class PredictRequest(BaseModel):
    symbol: str = Field(default=DEFAULT_SYMBOL)
    window_start: datetime | None = None
    features: dict[str, float] | None = None


class PredictOut(BaseModel):
    status: Literal["ok", "error", "not_available"]
    symbol: str
    window_start: datetime | None = None
    predicted_rv_next_1h: float | None = None
    model_name: str | None = None
    model_version: str | None = None
    detail: str | None = None
    meta: Meta


Meta.model_rebuild()
