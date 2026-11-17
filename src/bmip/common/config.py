"""Environment-backed configuration for BMIP services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

SERVICE_CREDENTIAL_KEYS = {
    "ingest": ("MINIO_SVC_INGEST_ACCESS_KEY", "MINIO_SVC_INGEST_SECRET_KEY"),
    "process": ("MINIO_SVC_PROCESS_ACCESS_KEY", "MINIO_SVC_PROCESS_SECRET_KEY"),
    "dbt": ("MINIO_SVC_DBT_ACCESS_KEY", "MINIO_SVC_DBT_SECRET_KEY"),
    "ml": ("MINIO_SVC_ML_ACCESS_KEY", "MINIO_SVC_ML_SECRET_KEY"),
    "api": ("MINIO_SVC_API_ACCESS_KEY", "MINIO_SVC_API_SECRET_KEY"),
    "backup": ("MINIO_SVC_BACKUP_ACCESS_KEY", "MINIO_SVC_BACKUP_SECRET_KEY"),
    "docs": ("MINIO_SVC_DOCS_ACCESS_KEY", "MINIO_SVC_DOCS_SECRET_KEY"),
}


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _symbols() -> tuple[str, ...]:
    """Allowlist of symbols; MARKET_SYMBOLS wins, then MARKET_SYMBOL."""
    raw = os.getenv("MARKET_SYMBOLS") or os.getenv("MARKET_SYMBOL") or "BTCUSDT"
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return symbols or ("BTCUSDT",)


@dataclass(frozen=True)
class Settings:
    env: str
    node: str
    log_level: str
    minio_endpoint: str
    minio_internal_endpoint: str
    minio_region: str
    lakekeeper_url: str
    lakekeeper_internal_url: str
    lakekeeper_warehouse: str
    postgres_dsn: str
    redpanda_brokers: str
    redpanda_internal_brokers: str
    market_topic: str
    market_dlq_topic: str
    market_symbol: str
    market_feed: str
    market_ws_url: str
    market_replay_file: str
    stream_consumer_group: str
    stream_replay_group: str
    stream_poll_max_records: int
    stream_poll_timeout_ms: int
    stream_watermark_delay_seconds: int
    stream_correction_window_minutes: int
    stream_metrics_host: str
    stream_metrics_port: int
    stream_idle_exit_seconds: float
    stream_startup_delay_seconds: float
    social_feed: str
    social_query: str
    social_max_pages: int
    social_replay_file: str
    bluesky_base_url: str
    binance_vision_base_url: str
    pii_hash_salt: str
    sentiment_model_version: str
    gold_max_gap_hours: int
    gold_freshness_threshold_minutes: int

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = ""
    api_auth_required: bool = True
    api_cache_seconds: int = 30
    serving_max_range_days: int = 31
    serving_max_rows: int = 50000
    serving_page_size_default: int = 100
    serving_page_size_max: int = 1000
    lake_reader: str = "duckdb"
    lake_query_timeout_seconds: float = 5.0
    duckdb_extension_dir: str = ""
    market_symbols: tuple[str, ...] = ("BTCUSDT",)
    freshness_market_slo_seconds: int = 5400
    freshness_sentiment_slo_seconds: int = 5400
    freshness_predictions_slo_seconds: int = 7200
    freshness_quality_slo_seconds: int = 86400
    bmip_as_of: str = ""
    dq_report_path: str = "evidence/dq/dq_report.json"
    dataset_registry_path: str = "catalog/datasets.yml"

    @classmethod
    def from_env(cls) -> Settings:
        user = os.getenv("POSTGRES_USER", "bmip")
        database = os.getenv("POSTGRES_DB", "bmip")
        dsn = os.getenv("POSTGRES_CORE_DSN")
        if not dsn:
            password = _env("POSTGRES_PASSWORD")
            dsn = f"postgresql://{quote(user)}:{quote(password)}@localhost:5433/{database}"
        return cls(
            env=os.getenv("BMIP_ENV", "dev"),
            node=os.getenv("BMIP_NODE", "n1"),
            log_level=os.getenv("BMIP_LOG_LEVEL", "INFO"),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
            minio_internal_endpoint=os.getenv(
                "MINIO_ENDPOINT_INTERNAL", "http://minio:9000"
            ),
            minio_region=os.getenv("MINIO_S3_REGION", "local"),
            lakekeeper_url=os.getenv("LAKEKEEPER_URL", "http://localhost:8181"),
            lakekeeper_internal_url=os.getenv(
                "LAKEKEEPER_URL_INTERNAL", "http://lakekeeper:8181"
            ),
            lakekeeper_warehouse=os.getenv("LAKEKEEPER_WAREHOUSE", "lakehouse"),
            postgres_dsn=dsn,
            redpanda_brokers=os.getenv("REDPANDA_BROKERS", "localhost:19092"),
            redpanda_internal_brokers=os.getenv(
                "REDPANDA_BROKERS_INTERNAL", "redpanda:9092"
            ),
            market_topic=os.getenv("MARKET_TOPIC", "market.trades"),
            market_dlq_topic=os.getenv("MARKET_DLQ_TOPIC", "market.trades.dlq"),
            market_symbol=os.getenv("MARKET_SYMBOL", "BTCUSDT"),
            market_feed=os.getenv("MARKET_FEED", "binance_ws"),
            market_ws_url=os.getenv(
                "MARKET_WS_URL", "wss://stream.binance.com:9443/ws"
            ),
            market_replay_file=os.getenv(
                "MARKET_REPLAY_FILE", "tests/fixtures/binance_agg_trades.jsonl"
            ),
            stream_consumer_group=os.getenv("STREAM_CONSUMER_GROUP", "ohlcv-builder"),
            stream_replay_group=os.getenv("STREAM_REPLAY_GROUP", "ohlcv-builder-replay"),
            stream_poll_max_records=int(os.getenv("STREAM_POLL_MAX_RECORDS", "1000")),
            stream_poll_timeout_ms=int(os.getenv("STREAM_POLL_TIMEOUT_MS", "500")),
            stream_watermark_delay_seconds=int(
                os.getenv("STREAM_WATERMARK_DELAY_SECONDS", "120")
            ),
            stream_correction_window_minutes=int(
                os.getenv("STREAM_CORRECTION_WINDOW_MINUTES", "30")
            ),
            stream_metrics_host=os.getenv("STREAM_METRICS_HOST", "0.0.0.0"),
            stream_metrics_port=int(os.getenv("STREAM_METRICS_PORT", "9101")),
            stream_idle_exit_seconds=float(os.getenv("STREAM_IDLE_EXIT_SECONDS", "5")),
            stream_startup_delay_seconds=float(
                os.getenv("STREAM_STARTUP_DELAY_SECONDS", "0")
            ),
            social_feed=os.getenv("SOCIAL_FEED", "bluesky"),
            social_query=os.getenv("SOCIAL_QUERY", "bitcoin OR btc OR crypto"),
            social_max_pages=int(os.getenv("SOCIAL_MAX_PAGES", "50")),
            social_replay_file=os.getenv(
                "SOCIAL_REPLAY_FILE", "tests/fixtures/bluesky_posts.json"
            ),
            bluesky_base_url=os.getenv(
                "BLUESKY_BASE_URL", "https://api.bsky.app"
            ),
            binance_vision_base_url=os.getenv(
                "BINANCE_VISION_BASE_URL", "https://data.binance.vision"
            ),
            pii_hash_salt=os.getenv("PII_HASH_SALT", ""),
            sentiment_model_version=os.getenv(
                "SENTIMENT_MODEL_VERSION", "vaderSentiment-3.3.2"
            ),
            gold_max_gap_hours=int(os.getenv("GOLD_MAX_GAP_HOURS", "24")),
            gold_freshness_threshold_minutes=int(
                os.getenv("GOLD_FRESHNESS_THRESHOLD_MINUTES", "90")
            ),
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=int(os.getenv("API_PORT", "8000")),
            api_key=os.getenv("BMIP_API_KEY", ""),
            api_auth_required=_flag("API_AUTH_REQUIRED", True),
            api_cache_seconds=int(os.getenv("API_CACHE_SECONDS", "30")),
            serving_max_range_days=int(os.getenv("SERVING_MAX_RANGE_DAYS", "31")),
            serving_max_rows=int(os.getenv("SERVING_MAX_ROWS", "50000")),
            serving_page_size_default=int(os.getenv("SERVING_PAGE_SIZE", "100")),
            serving_page_size_max=int(os.getenv("SERVING_PAGE_SIZE_MAX", "1000")),
            lake_reader=os.getenv("LAKE_READER", "duckdb"),
            lake_query_timeout_seconds=float(
                os.getenv("LAKE_QUERY_TIMEOUT_SECONDS", "5")
            ),
            duckdb_extension_dir=os.getenv("DUCKDB_EXTENSION_DIR", ""),
            market_symbols=_symbols(),
            freshness_market_slo_seconds=int(
                os.getenv("FRESHNESS_MARKET_SLO_SECONDS", "5400")
            ),
            freshness_sentiment_slo_seconds=int(
                os.getenv("FRESHNESS_SENTIMENT_SLO_SECONDS", "5400")
            ),
            freshness_predictions_slo_seconds=int(
                os.getenv("FRESHNESS_PREDICTIONS_SLO_SECONDS", "7200")
            ),
            freshness_quality_slo_seconds=int(
                os.getenv("FRESHNESS_QUALITY_SLO_SECONDS", "86400")
            ),
            bmip_as_of=os.getenv("BMIP_AS_OF", ""),
            dq_report_path=os.getenv(
                "DQ_REPORT_PATH", "evidence/dq/dq_report.json"
            ),
            dataset_registry_path=os.getenv(
                "DATASET_REGISTRY_PATH", "catalog/datasets.yml"
            ),
        )

    def minio_credentials(self, service: str) -> tuple[str, str]:
        try:
            access_key, secret_key = SERVICE_CREDENTIAL_KEYS[service]
        except KeyError as exc:
            raise KeyError(f"unknown MinIO service: {service}") from exc
        return _env(access_key), _env(secret_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
