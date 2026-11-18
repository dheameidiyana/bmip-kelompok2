"""Dataset snapshots and feature contracts for the W2-A volatility model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pyiceberg.catalog import load_catalog
from pyiceberg.expressions import EqualTo
from pyiceberg.io import load_file_io

from bmip.common.config import Settings
from bmip.common.symbols import MARKET_SYMBOLS
from bmip.transform.silver import _s3_properties

MART_ML = "gold.mart_ml"
LABEL_COLUMN = "label_rv_next_1h"
FEATURE_SNAPSHOT_COLUMN = "feature_snapshot_id"

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
SYMBOL_FEATURES = tuple(f"symbol_{symbol}" for symbol in MARKET_SYMBOLS)
REQUIRED_COLUMNS = (
    "symbol",
    "window_start",
    "label_start",
    "label_end",
    "dq_status",
    LABEL_COLUMN,
    *MARKET_FEATURES,
)


@dataclass(frozen=True)
class DatasetSnapshot:
    frame: pd.DataFrame
    snapshot_id: str
    dataset_id: str
    path: Path
    sha256: str
    row_count: int
    counts: dict[str, int]
    start: datetime
    end: datetime


def _catalog(settings: Settings):
    return load_catalog(
        "lakekeeper",
        type="rest",
        uri=f"{settings.lakekeeper_url.rstrip('/')}/catalog",
        warehouse=settings.lakekeeper_warehouse,
        **_s3_properties(settings, role="api"),
    )


def _table(settings: Settings):
    catalog = _catalog(settings)
    table = catalog.load_table(MART_ML)
    table.io = load_file_io(_s3_properties(settings, role="api"), table.location())
    return table


def load_mart_ml(settings: Settings) -> tuple[pd.DataFrame, str]:
    table = _table(settings)
    snapshot = table.current_snapshot()
    if snapshot is None:
        raise RuntimeError("gold.mart_ml has no snapshot")
    frame = table.scan().to_arrow().to_pandas()
    frame["window_start"] = pd.to_datetime(frame["window_start"], utc=True)
    frame["label_start"] = pd.to_datetime(frame["label_start"], utc=True)
    frame["label_end"] = pd.to_datetime(frame["label_end"], utc=True)
    return frame, str(snapshot.snapshot_id)


def sentiment_coverage(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    return float(
        (frame[list(SENTIMENT_FEATURES)].abs().sum(axis=1) > 0).mean()
    )


def feature_columns(*, include_sentiment: bool) -> tuple[str, ...]:
    columns = (*MARKET_FEATURES, *SYMBOL_FEATURES)
    if include_sentiment:
        columns = (*columns, *SENTIMENT_FEATURES)
    return columns


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    prepared = prepared[prepared["dq_status"] == "pass"]
    prepared = prepared[prepared[LABEL_COLUMN].notna()]
    prepared = prepared.dropna(subset=list(MARKET_FEATURES))
    for column in SENTIMENT_FEATURES:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce").fillna(0.0)
    for symbol in MARKET_SYMBOLS:
        prepared[f"symbol_{symbol}"] = (prepared["symbol"] == symbol).astype("int8")
    prepared = prepared.sort_values(["window_start", "symbol"]).reset_index(drop=True)
    return prepared


def split_frame(frame: pd.DataFrame) -> pd.DataFrame:
    split = frame.copy()
    dates = sorted(split["window_start"].dt.date.unique())
    if len(dates) < 3:
        raise ValueError("dataset needs at least three event dates")
    train_end = max(1, int(len(dates) * 0.70))
    validation_end = max(train_end + 1, int(len(dates) * 0.85))
    train_dates = set(dates[:train_end])
    validation_dates = set(dates[train_end:validation_end])
    split["split"] = "test"
    split.loc[split["window_start"].dt.date.isin(train_dates), "split"] = "train"
    split.loc[split["window_start"].dt.date.isin(validation_dates), "split"] = "validation"
    split["split_date"] = split["window_start"].dt.date
    return split


def frame_sha256(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    hashed = pd.util.hash_pandas_object(frame[list(columns)], index=False)
    return hashlib.sha256(hashed.to_numpy().tobytes()).hexdigest()


def save_snapshot(
    settings: Settings,
    frame: pd.DataFrame,
    snapshot_id: str,
    *,
    output_dir: Path | None = None,
) -> DatasetSnapshot:
    prepared = prepare_frame(frame)
    split = split_frame(prepared)
    target_dir = output_dir or Path("data/ml/snapshots")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"mart_ml_{snapshot_id}.parquet"
    split.to_parquet(path, index=False)
    columns = feature_columns(include_sentiment=True)
    sha = frame_sha256(split, columns)
    counts = {
        str(symbol): int(count)
        for symbol, count in split["symbol"].value_counts().sort_index().items()
    }
    start = split["window_start"].min().to_pydatetime()
    end = split["window_start"].max().to_pydatetime()
    return DatasetSnapshot(
        frame=split,
        snapshot_id=snapshot_id,
        dataset_id=f"mart_ml@{snapshot_id}",
        path=path,
        sha256=sha,
        row_count=len(split),
        counts=counts,
        start=start,
        end=end,
    )


def snapshot_metadata(snapshot: DatasetSnapshot) -> dict[str, Any]:
    frame = snapshot.frame
    return {
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "path": str(snapshot.path),
        "sha256": snapshot.sha256,
        "row_count": snapshot.row_count,
        "counts": snapshot.counts,
        "start": snapshot.start.isoformat(),
        "end": snapshot.end.isoformat(),
        "feature_columns": list(feature_columns(include_sentiment=True)),
        "splits": {
            str(name): int(count)
            for name, count in frame["split"].value_counts().sort_index().items()
        },
        "feature_snapshot_ids": sorted(
            str(value) for value in frame[FEATURE_SNAPSHOT_COLUMN].unique()
        ),
    }


def write_metadata(snapshot: DatasetSnapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot_metadata(snapshot), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def latest_feature_row(
    settings: Settings,
    symbol: str,
    *,
    at: datetime | None = None,
) -> dict[str, Any] | None:
    table = _table(settings)
    rows = (
        table.scan(row_filter=EqualTo("symbol", symbol))
        .to_arrow()
        .to_pylist()
    )
    if at is not None:
        rows = [
            row
            for row in rows
            if row["window_start"].astimezone(UTC) <= at.astimezone(UTC)
        ]
    if not rows:
        return None
    return max(rows, key=lambda row: row["window_start"])
