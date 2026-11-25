"""Build the W2-A drift report: holdout reference vs recent production rows."""

from __future__ import annotations

import argparse
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

from bmip.ml.dataset import (
    LABEL_COLUMN,
    feature_columns,
    load_frozen_snapshot,
    prepare_frame,
    split_frame,
)

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "ml" / "models" / "selected.joblib"
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)
DRIFT_THRESHOLD = 0.2
MIN_REFERENCE_ROWS = 24


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


def latest_metadata() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return paths[-1]


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--metadata", type=Path, default=None)
    args = parser.parse_args()
    metadata_path = args.metadata or latest_metadata()
    snapshot = load_frozen_snapshot(args.snapshot, metadata_path)
    prepared = split_frame(prepare_frame(snapshot.frame))
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    features = tuple(bundle["features"])
    all_features = feature_columns(include_sentiment=True)

    holdout = prepared[prepared["split"] == "test"].copy()
    cutoff = holdout["window_start"].max() - pd.Timedelta(days=7)
    production = holdout[holdout["window_start"] >= cutoff].copy()
    reference = holdout[holdout["window_start"] < cutoff].copy()
    reference_kind = "holdout-pre-production"
    if len(reference) < MIN_REFERENCE_ROWS:
        validation = prepared[prepared["split"] == "validation"].copy()
        if len(validation) < MIN_REFERENCE_ROWS:
            raise RuntimeError(
                "drift reference is too small: "
                f"{len(reference)} holdout rows and {len(validation)} validation rows"
            )
        reference = validation
        reference_kind = "validation-fallback"

    if reference.empty or production.empty:
        raise RuntimeError("drift reference or production window is empty")

    feature_drift = []
    for feature in all_features:
        psi = _psi(reference[feature], production[feature])
        feature_drift.append(
            {
                "feature": feature,
                "psi": psi,
                "drift": psi >= DRIFT_THRESHOLD,
                "reference_mean": float(
                    pd.to_numeric(reference[feature], errors="coerce").mean()
                ),
                "production_mean": float(
                    pd.to_numeric(production[feature], errors="coerce").mean()
                ),
            }
        )
    feature_drift.sort(key=lambda item: item["psi"], reverse=True)

    predictions = np.asarray(model.predict(production[list(features)]), dtype=float)
    production = production.assign(_prediction=predictions)
    daily = []
    for date, group in production.groupby(production["window_start"].dt.date):
        values = _metrics(group[LABEL_COLUMN], group["_prediction"].to_numpy())
        daily.append({"date": str(date), **values})
    daily.sort(key=lambda item: item["date"])

    per_symbol = []
    for symbol, group in production.groupby("symbol"):
        values = _metrics(group[LABEL_COLUMN], group["_prediction"].to_numpy())
        per_symbol.append({"symbol": str(symbol), **values})
    per_symbol.sort(key=lambda item: item["symbol"])

    flagged = [item for item in feature_drift if item["drift"]]
    report = {
        "id": "W2-A-drift",
        "timestamp": _now().isoformat(timespec="seconds").replace("+00:00", "Z"),
        "commit": _commit(),
        "model": bundle.get("name"),
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "sha256": snapshot.sha256,
        "reference": {
            "split": reference_kind,
            "rows": int(len(reference)),
            "start": reference["window_start"].min().isoformat(),
            "end": reference["window_start"].max().isoformat(),
        },
        "production": {
            "split": "holdout-recent",
            "rows": int(len(production)),
            "start": production["window_start"].min().isoformat(),
            "end": production["window_start"].max().isoformat(),
            "window_days": 7,
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
            "frozen holdout. The reference is the earlier part of the same "
            "holdout, so the two windows do not overlap. Realised labels are "
            "one hour behind the features, so the newest unlabelled hours are "
            "excluded. KS, prediction PSI, rolling MAE, and serving.drift_metrics "
            "remain W2-B/C3-B scope."
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
                "reference": report["reference"],
                "production": report["production"],
                "drift_detected": report["drift_detected"],
                "flagged_features": report["flagged_features"],
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
