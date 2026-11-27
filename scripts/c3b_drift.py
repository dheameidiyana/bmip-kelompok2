"""Build, persist, and gate the C3-B drift report."""

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
from scipy.stats import ks_2samp

from bmip.common.config import get_settings
from bmip.ml.dataset import (
    LABEL_COLUMN,
    MARKET_FEATURES,
    SENTIMENT_FEATURES,
    load_frozen_snapshot,
    prepare_frame,
    split_frame,
)
from bmip.serving.repository import ServingRepository, ensure_schema

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data" / "ml" / "models" / "selected.joblib"
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)
FEATURES = (*MARKET_FEATURES, *SENTIMENT_FEATURES)
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


def snapshot_from_metadata(metadata_path: Path) -> Path:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    recorded = metadata.get("path")
    if not recorded:
        return DEFAULT_SNAPSHOT
    candidate = Path(str(recorded))
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate if candidate.exists() else DEFAULT_SNAPSHOT


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


def _metrics(actual: pd.Series, predicted: np.ndarray) -> dict[str, float]:
    errors = np.asarray(actual, dtype=float) - predicted
    return {
        "count": int(len(errors)),
        "mae": float(np.mean(np.abs(errors))),
        "rmse": float(np.sqrt(np.mean(errors**2))),
    }


def _top_features(model: Any, features: tuple[str, ...]) -> list[str]:
    values = getattr(model, "feature_importances_", None)
    if values is None or len(values) != len(features):
        return list(features[:5])
    ranked = sorted(
        zip(features, (float(value) for value in values), strict=True),
        key=lambda item: item[1],
        reverse=True,
    )
    return [feature for feature, _ in ranked[:5]]


def build_report(snapshot_path: Path, metadata_path: Path) -> dict[str, Any]:
    snapshot = load_frozen_snapshot(snapshot_path, metadata_path)
    prepared = split_frame(prepare_frame(snapshot.frame))
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    features = tuple(bundle["features"])
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

    feature_rows = []
    for feature in FEATURES:
        left = reference[feature]
        right = production[feature]
        psi = _psi(left, right)
        ks = ks_2samp(
            pd.to_numeric(left, errors="coerce").dropna(),
            pd.to_numeric(right, errors="coerce").dropna(),
        )
        feature_rows.append(
            {
                "feature": feature,
                "psi": psi,
                "ks_statistic": float(ks.statistic),
                "ks_pvalue": float(ks.pvalue),
                "drift": bool(psi >= DRIFT_THRESHOLD),
                "reference_mean": float(pd.to_numeric(left, errors="coerce").mean()),
                "production_mean": float(pd.to_numeric(right, errors="coerce").mean()),
            }
        )
    feature_rows.sort(key=lambda item: item["psi"], reverse=True)

    predictions = np.asarray(model.predict(production[list(features)]), dtype=float)
    production = production.assign(_prediction=predictions)
    daily = []
    for date, group in production.groupby(production["window_start"].dt.date):
        daily.append(
            {
                "date": str(date),
                **_metrics(group[LABEL_COLUMN], group["_prediction"].to_numpy()),
            }
        )
    daily.sort(key=lambda item: item["date"])
    rolling_mae = float(np.mean([item["mae"] for item in daily])) if daily else 0.0
    top5 = _top_features(model, features)
    top5_psi = {
        row["feature"]: row["psi"] for row in feature_rows if row["feature"] in top5
    }
    trigger_required = any(value > DRIFT_THRESHOLD for value in top5_psi.values())
    flagged = [item for item in feature_rows if item["drift"]]
    return {
        "id": "C3-B-drift",
        "timestamp": _now().isoformat(timespec="seconds"),
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
        "threshold": DRIFT_THRESHOLD,
        "drift_detected": bool(flagged),
        "flagged_features": [item["feature"] for item in flagged],
        "top5_features": top5,
        "top5_psi": top5_psi,
        "trigger_required": trigger_required,
        "rolling_mae_7d": rolling_mae,
        "features": feature_rows,
        "daily_mae": daily,
        "limitations": (
            "Production is the most recent seven labelled days in the frozen holdout; "
            "the reference is the earlier holdout or validation fallback. Labels are "
            "one hour behind the features, so unlabelled recent hours are excluded."
        ),
    }


def persist(report: dict[str, Any]) -> int:
    settings = get_settings()
    rows = []
    run_ts = datetime.fromisoformat(report["timestamp"]).replace(tzinfo=UTC)
    for item in report["features"]:
        rows.append(
            {
                "run_ts": run_ts,
                "model_name": "volatility_model",
                "feature": item["feature"],
                "psi": item["psi"],
                "ks_statistic": item["ks_statistic"],
                "ks_pvalue": item["ks_pvalue"],
                "drift": item["drift"],
                "reference_rows": report["reference"]["rows"],
                "production_rows": report["production"]["rows"],
                "rolling_mae_7d": report["rolling_mae_7d"],
                "window_start": report["production"]["start"],
                "window_end": report["production"]["end"],
                "detail": {
                    "threshold": report["threshold"],
                    "reference_split": report["reference"]["split"],
                    "trigger_required": report["trigger_required"],
                },
            }
        )
    with ServingRepository(settings) as repository:
        ensure_schema(repository.connection)
        return repository.upsert_drift_metrics(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--no-db", action="store_true")
    args = parser.parse_args()
    metadata = args.metadata or latest_metadata()
    snapshot = args.snapshot or snapshot_from_metadata(metadata)
    report = build_report(snapshot, metadata)
    if not args.no_db:
        report["persisted_rows"] = persist(report)
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"drift_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
