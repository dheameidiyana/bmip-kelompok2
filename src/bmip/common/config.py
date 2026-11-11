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
    market_symbol: str
    market_feed: str
    market_ws_url: str
    market_replay_file: str
    social_feed: str
    social_query: str
    social_max_pages: int
    social_replay_file: str
    bluesky_base_url: str
    binance_vision_base_url: str

    @classmethod
    def from_env(cls) -> Settings:
        user = os.getenv("POSTGRES_USER", "bmip")
        password = _env("POSTGRES_PASSWORD")
        database = os.getenv("POSTGRES_DB", "bmip")
        dsn = os.getenv(
            "POSTGRES_CORE_DSN",
            f"postgresql://{quote(user)}:{quote(password)}@localhost:5433/{database}",
        )
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
            market_symbol=os.getenv("MARKET_SYMBOL", "BTCUSDT"),
            market_feed=os.getenv("MARKET_FEED", "binance_ws"),
            market_ws_url=os.getenv(
                "MARKET_WS_URL", "wss://stream.binance.com:9443/ws"
            ),
            market_replay_file=os.getenv(
                "MARKET_REPLAY_FILE", "tests/fixtures/binance_agg_trades.jsonl"
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
