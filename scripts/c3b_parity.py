"""Verify Feast point-in-time features match the frozen mart_ml snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bmip.common.config import get_settings
from bmip.ml.dataset import (
    MARKET_FEATURES,
    SENTIMENT_FEATURES,
    load_frozen_snapshot,
    prepare_frame,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)
FEATURES = (*MARKET_FEATURES, *SENTIMENT_FEATURES)


def latest_metadata() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return paths[-1]


def _configure_feast_env() -> None:
    settings = get_settings()
    password = settings.feast_postgres_password or os.getenv("PREFECT_DB_PASSWORD", "")
    os.environ.update(
        {
            "FEAST_REPO_PATH": settings.feast_repo_path,
            "FEAST_OFFLINE_PATH": settings.feast_offline_path,
            "FEAST_REGISTRY_PATH": str((ROOT / settings.feast_registry_path).resolve()),
            "FEAST_POSTGRES_HOST": settings.feast_postgres_host,
            "FEAST_POSTGRES_PORT": str(settings.feast_postgres_port),
            "FEAST_POSTGRES_DATABASE": settings.feast_postgres_database,
            "FEAST_POSTGRES_SCHEMA": settings.feast_postgres_schema,
            "FEAST_POSTGRES_USER": settings.feast_postgres_user,
            "FEAST_POSTGRES_PASSWORD": password,
        }
    )


def _hash(frame: pd.DataFrame) -> str:
    normalized = frame.sort_values(["symbol", "window_start"]).reset_index(drop=True)
    values = normalized[["symbol", "window_start", *FEATURES]].copy()
    for column in FEATURES:
        values[column] = pd.to_numeric(values[column], errors="coerce").astype("float64")
    values["window_start"] = values["window_start"].astype("datetime64[us, UTC]")
    hashed = pd.util.hash_pandas_object(values, index=False)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--metadata", type=Path, default=None)
    args = parser.parse_args()
    metadata = args.metadata or latest_metadata()
    snapshot = load_frozen_snapshot(args.snapshot, metadata)
    expected = prepare_frame(snapshot.frame).copy()
    expected["window_start"] = pd.to_datetime(expected["window_start"], utc=True)
    entity_df = expected[["symbol", "window_start"]].rename(
        columns={"window_start": "event_timestamp"}
    )
    _configure_feast_env()
    from feast import FeatureStore

    store = FeatureStore(repo_path=str(ROOT / "feature_repo"))
    actual = store.get_historical_features(
        entity_df=entity_df,
        features=[f"market_features_1m:{name}" for name in MARKET_FEATURES]
        + [f"sentiment_1h:{name}" for name in SENTIMENT_FEATURES],
    ).to_df()
    actual = actual.rename(columns={"event_timestamp": "window_start"})
    actual["window_start"] = pd.to_datetime(actual["window_start"], utc=True)
    actual = actual.sort_values(["symbol", "window_start"]).reset_index(drop=True)
    expected = expected.sort_values(["symbol", "window_start"]).reset_index(drop=True)

    max_abs_diff = {}
    for feature in FEATURES:
        left = pd.to_numeric(expected[feature], errors="coerce")
        right = pd.to_numeric(actual[feature], errors="coerce")
        max_abs_diff[feature] = float((left - right).abs().max()) if len(left) else None

    expected_hash = _hash(expected)
    actual_hash = _hash(actual)
    passed = len(expected) == len(actual) and expected_hash == actual_hash
    payload = {
        "id": "C3-B-pit-parity",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "snapshot_id": snapshot.snapshot_id,
        "expected_rows": len(expected),
        "actual_rows": len(actual),
        "expected_hash": expected_hash,
        "actual_hash": actual_hash,
        "pass": passed,
        "max_abs_diff": max_abs_diff,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"pit-parity_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
