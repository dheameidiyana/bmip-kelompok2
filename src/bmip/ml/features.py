"""Feature lookup with a Feast online-store path and a gold fallback."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.ml.dataset import (
    MARKET_FEATURES,
    SENTIMENT_FEATURES,
    DatasetSnapshot,
    latest_feature_row,
    prepare_frame,
    split_frame,
)

log = get_logger(__name__)
ROOT = Path(__file__).resolve().parents[3]
MARKET_VIEW = "market_features_1m"
SENTIMENT_VIEW = "sentiment_1h"


def configure_feast_env(settings: Settings) -> None:
    password = settings.feast_postgres_password or os.getenv("PREFECT_DB_PASSWORD", "")
    registry = Path(settings.feast_registry_path)
    if not registry.is_absolute():
        registry = ROOT / registry
    os.environ.update(
        {
            "FEAST_REPO_PATH": settings.feast_repo_path,
            "FEAST_OFFLINE_PATH": str((ROOT / settings.feast_offline_path).resolve()),
            "FEAST_REGISTRY_PATH": str(registry.resolve()),
            "FEAST_POSTGRES_HOST": settings.feast_postgres_host,
            "FEAST_POSTGRES_PORT": str(settings.feast_postgres_port),
            "FEAST_POSTGRES_DATABASE": settings.feast_postgres_database,
            "FEAST_POSTGRES_SCHEMA": settings.feast_postgres_schema,
            "FEAST_POSTGRES_USER": settings.feast_postgres_user,
            "FEAST_POSTGRES_PASSWORD": password,
        }
    )


def _feature_store(settings: Settings):
    configure_feast_env(settings)
    from feast import FeatureStore

    return FeatureStore(repo_path=str(ROOT / settings.feast_repo_path))


def _online_features() -> list[str]:
    return [
        f"{MARKET_VIEW}:{name}" for name in MARKET_FEATURES
    ] + [f"{MARKET_VIEW}:feature_ts_epoch"] + [
        f"{SENTIMENT_VIEW}:{name}" for name in SENTIMENT_FEATURES
    ]


def feast_training_frame(
    settings: Settings,
    snapshot: DatasetSnapshot,
):
    import pandas as pd

    expected = split_frame(prepare_frame(snapshot.frame)).reset_index(drop=True)
    entity_df = expected[["symbol", "window_start"]].rename(
        columns={"window_start": "event_timestamp"}
    )
    store = _feature_store(settings)
    actual = store.get_historical_features(
        entity_df=entity_df,
        features=[f"{MARKET_VIEW}:{name}" for name in MARKET_FEATURES]
        + [f"{SENTIMENT_VIEW}:{name}" for name in SENTIMENT_FEATURES],
    ).to_df()
    actual = actual.rename(columns={"event_timestamp": "window_start"})
    actual["window_start"] = pd.to_datetime(actual["window_start"], utc=True)
    actual = actual.sort_values(["symbol", "window_start"]).reset_index(drop=True)
    expected = expected.sort_values(["symbol", "window_start"]).reset_index(drop=True)
    if len(actual) != len(expected):
        raise RuntimeError(
            f"Feast historical row mismatch: {len(actual)} != {len(expected)}"
        )
    for feature in (*MARKET_FEATURES, *SENTIMENT_FEATURES):
        expected[feature] = actual[feature].to_numpy()
    return expected


def latest_features(
    settings: Settings,
    symbol: str,
    *,
    at: datetime | None = None,
) -> dict[str, Any] | None:
    if settings.feature_source != "feast":
        return latest_feature_row(settings, symbol, at=at)
    try:
        store = _feature_store(settings)
        response = store.get_online_features(
            features=_online_features(),
            entity_rows=[{"symbol": symbol}],
        ).to_dict()
        row: dict[str, Any] = {}
        for name in (*MARKET_FEATURES, *SENTIMENT_FEATURES):
            values = response.get(name) or []
            row[name] = values[0] if values else None
        epochs = response.get("feature_ts_epoch") or []
        if not epochs or epochs[0] is None:
            return None
        row["window_start"] = datetime.fromtimestamp(
            float(epochs[0]), tz=UTC
        )
        if at is not None and row["window_start"] > at.astimezone(UTC):
            return None
        return row
    except Exception as exc:  # noqa: BLE001 - degrade to the gold path
        log.warning(
            "feast online lookup failed; falling back to gold",
            extra={"ctx_error": f"{type(exc).__name__}: {exc}"},
        )
        return latest_feature_row(settings, symbol, at=at)
