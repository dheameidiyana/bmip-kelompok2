"""Build the Feast offline sources from the frozen ML snapshot and serving rows."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import psycopg

from bmip.common.config import get_settings
from bmip.ml.dataset import (
    MARKET_FEATURES,
    SENTIMENT_FEATURES,
    load_frozen_snapshot,
    prepare_frame,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)


def latest_metadata() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return paths[-1]


def snapshot_from_metadata(metadata_path: Path) -> Path:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    recorded = metadata.get("path")
    if not recorded:
        return DEFAULT_SNAPSHOT
    candidate = Path(str(recorded))
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate if candidate.exists() else DEFAULT_SNAPSHOT


def build_offline(snapshot_path: Path, metadata_path: Path) -> dict[str, object]:
    snapshot = load_frozen_snapshot(snapshot_path, metadata_path)
    prepared = prepare_frame(snapshot.frame)
    columns = ["symbol", "window_start", *MARKET_FEATURES, *SENTIMENT_FEATURES]
    offline = prepared[columns].sort_values(["window_start", "symbol"]).reset_index(drop=True)
    offline["feature_ts_epoch"] = (
        offline["window_start"].astype("int64") // 1_000_000
    ).astype("int64")
    output = ROOT / "data" / "feast" / "offline.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    offline.to_parquet(output, index=False)
    return {
        "path": str(output.relative_to(ROOT)),
        "rows": len(offline),
        "start": offline["window_start"].min().isoformat(),
        "end": offline["window_start"].max().isoformat(),
        "columns": columns,
    }


def build_market_hourly() -> dict[str, object]:
    settings = get_settings()
    output = ROOT / "data" / "feast" / "market_hourly.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "symbol",
        "window_start",
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
    ]
    fallback = None
    try:
        with psycopg.connect(settings.postgres_dsn) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(columns)} FROM serving.market_hourly "
                "ORDER BY window_start"
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - offline source can be empty
        rows = []
        fallback = f"{type(exc).__name__}: {exc}"
    frame = pd.DataFrame(rows, columns=columns)
    if not frame.empty:
        frame["window_start"] = pd.to_datetime(frame["window_start"], utc=True)
    frame.to_parquet(output, index=False)
    return {
        "path": str(output.relative_to(ROOT)),
        "rows": len(frame),
        "start": None
        if frame.empty
        else frame["window_start"].min().isoformat(),
        "end": None
        if frame.empty
        else frame["window_start"].max().isoformat(),
        "fallback": fallback,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--skip-market-hourly", action="store_true")
    args = parser.parse_args()
    metadata = args.metadata or latest_metadata()
    snapshot_path = args.snapshot or snapshot_from_metadata(metadata)
    result = {"offline": build_offline(snapshot_path, metadata)}
    if not args.skip_market_hourly:
        result["market_hourly"] = build_market_hourly()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
