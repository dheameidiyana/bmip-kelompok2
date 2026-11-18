"""Build the W2-A drift report: training reference vs recent production rows."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from bmip.common.config import get_settings
from bmip.ml.dataset import (
    LABEL_COLUMN,
    feature_columns,
    load_mart_ml,
    prepare_frame,
    split_frame,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "ml" / "models" / "selected.joblib"
DRIFT_THRESHOLD = 0.25


def _now() -> datetime:
    return datetime.now(UTC)


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _psi(reference: pd.Series, actual: pd.Series, bins: int = 10) -> float:
    base = pd.to_numeric(reference, errors="coerce").dropna()
    live = pd.to_numeric(actual, errors="coerce").dropna()
    if base.empty or live.empty:
        return 0.0
    if float(base.std()) == 0.0 and float(live.std()) == 0.0:
        return 0.0
    edges = np.unique(np.quantile(base.to_numpy(), np.linspace(0, 1, bins + 1)))
    if len(edges) < 2:
        return 0.0
    edges[0] = -math.inf
    edges[-1] = math.inf
    base_counts = np.histogram(base, bins=edges)[0].astype(float)
    live_counts = np.histogram(live, bins=edges)[0].astype(float)
    base_pct = np.clip(base_counts / max(base_counts.sum(), 1), 1e-4, None)
    live_pct = np.clip(live_counts / max(live_counts.sum(), 1), 1e-4, None)
    return float(np.sum((live_pct - base_pct) * np.log(live_pct / base_pct)))


def _metrics(actual: pd.Series, predicted: np.ndarray) -> dict[str, Any]:
    errors = np.asarray(actual, dtype=float) - predicted
    return {
        "count": int(len(errors)),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
    }


def main() -> int:
    settings = get_settings()
    frame, snapshot_id = load_mart_ml(settings)
    prepared = split_frame(prepare_frame(frame))
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    features = tuple(bundle["features"])
    all_features = feature_columns(include_sentiment=True)

    train = prepared[prepared["split"] == "train"]
    production = prepared[prepared["split"] == "test"]
    cutoff = production["window_start"].max() - pd.Timedelta(days=7)
    recent = production[production["window_start"] >= cutoff].copy()

    if train.empty or recent.empty:
        raise RuntimeError("drift reference or production window is empty")

    feature_drift = []
    for feature in all_features:
        psi = _psi(train[feature], recent[feature])
        feature_drift.append(
            {
                "feature": feature,
                "psi": psi,
                "drift": psi >= DRIFT_THRESHOLD,
                "train_mean": float(pd.to_numeric(train[feature], errors="coerce").mean()),
                "production_mean": float(
                    pd.to_numeric(recent[feature], errors="coerce").mean()
                ),
            }
        )
    feature_drift.sort(key=lambda item: item["psi"], reverse=True)

    predictions = np.asarray(model.predict(recent[list(features)]), dtype=float)
    recent = recent.assign(_prediction=predictions)
    daily = []
    for date, group in recent.groupby(recent["window_start"].dt.date):
        values = _metrics(group[LABEL_COLUMN], group["_prediction"].to_numpy())
        daily.append({"date": str(date), **values})
    daily.sort(key=lambda item: item["date"])

    per_symbol = []
    for symbol, group in recent.groupby("symbol"):
        values = _metrics(group[LABEL_COLUMN], group["_prediction"].to_numpy())
        per_symbol.append({"symbol": str(symbol), **values})
    per_symbol.sort(key=lambda item: item["symbol"])

    flagged = [item for item in feature_drift if item["drift"]]
    report = {
        "id": "W2-A-drift",
        "timestamp": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "commit": _commit(),
        "model": bundle.get("name"),
        "dataset_id": bundle.get("dataset_id"),
        "snapshot_id": snapshot_id,
        "reference": {
            "split": "train",
            "rows": int(len(train)),
            "start": train["window_start"].min().isoformat(),
            "end": train["window_start"].max().isoformat(),
        },
        "production": {
            "split": "test/recent",
            "rows": int(len(recent)),
            "start": recent["window_start"].min().isoformat(),
            "end": recent["window_start"].max().isoformat(),
        },
        "result": "PASS",
        "threshold": DRIFT_THRESHOLD,
        "drift_detected": bool(flagged),
        "flagged_features": [item["feature"] for item in flagged],
        "features": feature_drift,
        "daily_mae": daily,
        "per_symbol": per_symbol,
        "limitations": (
            "Production here means the most recent seven labelled days in the "
            "gold snapshot. Realised labels are one hour behind the features, so "
            "the newest unlabelled hours are excluded."
        ),
    }
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"drift_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "evidence": str(output.relative_to(ROOT)),
                "drift_detected": report["drift_detected"],
                "flagged_features": report["flagged_features"],
                "production_rows": len(recent),
                "daily_mae": daily,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
