"""Apply and materialize the BMIP Feast repository (C3-B)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from bmip.common.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_feast_env() -> None:
    settings = get_settings()
    password = settings.feast_postgres_password or os.getenv("PREFECT_DB_PASSWORD", "")
    defaults = {
        "FEAST_REPO_PATH": settings.feast_repo_path,
        "FEAST_OFFLINE_PATH": settings.feast_offline_path,
        "FEAST_REGISTRY_PATH": settings.feast_registry_path,
        "FEAST_POSTGRES_HOST": settings.feast_postgres_host,
        "FEAST_POSTGRES_PORT": str(settings.feast_postgres_port),
        "FEAST_POSTGRES_DATABASE": settings.feast_postgres_database,
        "FEAST_POSTGRES_SCHEMA": settings.feast_postgres_schema,
        "FEAST_POSTGRES_USER": settings.feast_postgres_user,
        "FEAST_POSTGRES_PASSWORD": password,
    }
    for key, value in defaults.items():
        os.environ[key] = value
    registry = Path(settings.feast_registry_path)
    if not registry.is_absolute():
        os.environ["FEAST_REGISTRY_PATH"] = str((ROOT / registry).resolve())


def ensure_database() -> None:
    settings = get_settings()
    password = settings.feast_postgres_password or os.getenv("PREFECT_DB_PASSWORD", "")
    dsn = (
        f"postgresql://{settings.feast_postgres_user}:{password}"
        f"@{settings.feast_postgres_host}:{settings.feast_postgres_port}/postgres"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (settings.feast_postgres_database,),
        ).fetchone()
        if not exists:
            connection.execute(
                f'CREATE DATABASE "{settings.feast_postgres_database}"'
            )


def _store():
    from feast import FeatureStore

    return FeatureStore(repo_path=str(ROOT / "feature_repo"))


def _apply(store) -> None:
    from feature_repo.features import (
        market_features_1m,
        market_hourly,
        sentiment_1h,
        symbol,
    )

    store.apply([symbol, market_features_1m, sentiment_1h, market_hourly])


def _materialize(store, start: datetime | None, end: datetime) -> None:
    if start is None:
        store.materialize_incremental(end_date=end)
    else:
        store.materialize(start_date=start, end_date=end)


def _online_probe(store, symbol: str) -> dict[str, object]:
    features = [
        "market_features_1m:rv_60m",
        "sentiment_1h:sent_mean_1h",
        "market_hourly:realized_vol_1h",
    ]
    store.get_online_features(
        features=features,
        entity_rows=[{"symbol": symbol}],
    )
    started = time.perf_counter()
    result = store.get_online_features(
        features=features,
        entity_rows=[{"symbol": symbol}],
    ).to_dict()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {"symbol": symbol, "latency_ms": elapsed_ms, "result": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--skip-db-create", action="store_true")
    args = parser.parse_args()
    _configure_feast_env()
    if not args.skip_db_create:
        ensure_database()
    store = _store()
    _apply(store)
    offline = ROOT / "data" / "feast" / "offline.parquet"
    default_start = None
    default_end = datetime.now(UTC)
    if offline.exists():
        import pandas as pd

        bounds = pd.read_parquet(offline, columns=["window_start"])["window_start"]
        default_start = bounds.min().to_pydatetime()
        default_end = (bounds.max() + pd.Timedelta(hours=1)).to_pydatetime()
    start = (
        datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        if args.start
        else default_start
    )
    end = (
        datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        if args.end
        else default_end
    )
    _materialize(store, start, end)
    probe = _online_probe(store, args.symbol)
    payload = {
        "id": "C3-B-feast",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "repository": str((ROOT / "feature_repo").relative_to(ROOT)),
        "materialized_start": None if start is None else start.isoformat(),
        "materialized_end": end.isoformat(),
        "online_probe": probe,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"feast-apply_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
