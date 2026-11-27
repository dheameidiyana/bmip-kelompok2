"""Inject synthetic feature drift and prove the C3-B retrain trigger fires."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from c3b_drift import (
    DRIFT_THRESHOLD,
    FEATURES,
    MIN_REFERENCE_ROWS,
    MODEL_PATH,
    ROOT,
    _commit,
    _psi,
    _top_features,
    latest_metadata,
    snapshot_from_metadata,
)
from scipy.stats import ks_2samp

from bmip.ml.dataset import (
    LABEL_COLUMN,
    load_frozen_snapshot,
    prepare_frame,
    split_frame,
)

DEFAULT_FACTOR = 1.5
DEFAULT_STD_OFFSET = 3.0


def _now() -> datetime:
    return datetime.now(UTC)


def _split_reference_production(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str]:
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
    return reference, production, reference_kind


def _feature_rows(
    reference: pd.DataFrame,
    production: pd.DataFrame,
    features: tuple[str, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for feature in features:
        left = reference[feature]
        right = production[feature]
        psi = _psi(left, right)
        ks = ks_2samp(
            pd.to_numeric(left, errors="coerce").dropna(),
            pd.to_numeric(right, errors="coerce").dropna(),
        )
        rows.append(
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
    rows.sort(key=lambda item: item["psi"], reverse=True)
    return rows


def _mae(actual: pd.Series, predicted: np.ndarray) -> float:
    errors = np.asarray(actual, dtype=float) - predicted
    return float(np.mean(np.abs(errors)))


def _inject(
    reference: pd.DataFrame,
    production: pd.DataFrame,
    features: tuple[str, ...],
    factor: float,
    std_offset: float,
) -> tuple[pd.DataFrame, dict[str, dict[str, float]]]:
    injected = production.copy()
    parameters: dict[str, dict[str, float]] = {}
    for feature in features:
        base = pd.to_numeric(reference[feature], errors="coerce")
        mean = float(base.mean())
        std = float(base.std(ddof=0))
        if not np.isfinite(std) or std == 0.0:
            std = 1.0
        offset = mean + std_offset * std
        injected[feature] = pd.to_numeric(production[feature], errors="coerce") * factor + offset
        parameters[feature] = {
            "factor": factor,
            "offset": offset,
            "reference_mean": mean,
            "reference_std": std,
        }
    return injected, parameters


def build_report(
    snapshot_path: Path,
    metadata_path: Path,
    factor: float,
    std_offset: float,
) -> dict[str, object]:
    snapshot = load_frozen_snapshot(snapshot_path, metadata_path)
    prepared = split_frame(prepare_frame(snapshot.frame))
    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    features = tuple(bundle["features"])
    reference, production, reference_kind = _split_reference_production(prepared)
    top5 = _top_features(model, features)

    baseline_rows = _feature_rows(reference, production, FEATURES)
    baseline_top5_psi = {
        row["feature"]: row["psi"] for row in baseline_rows if row["feature"] in top5
    }
    baseline_mae = _mae(
        production[LABEL_COLUMN],
        np.asarray(model.predict(production[list(features)]), dtype=float),
    )

    injected, parameters = _inject(reference, production, tuple(top5), factor, std_offset)
    injected_rows = _feature_rows(reference, injected, FEATURES)
    injected_top5_psi = {
        row["feature"]: row["psi"] for row in injected_rows if row["feature"] in top5
    }
    trigger_required = any(value > DRIFT_THRESHOLD for value in injected_top5_psi.values())
    flagged = [row["feature"] for row in injected_rows if row["drift"]]
    injected_mae = _mae(
        injected[LABEL_COLUMN],
        np.asarray(model.predict(injected[list(features)]), dtype=float),
    )

    return {
        "id": "C3-B-drift-synthetic",
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
        "injection": {
            "kind": "synthetic-feature-shift",
            "factor": factor,
            "std_offset": std_offset,
            "features": parameters,
        },
        "threshold": DRIFT_THRESHOLD,
        "baseline_top5_psi": baseline_top5_psi,
        "injected_top5_psi": injected_top5_psi,
        "baseline_mae": baseline_mae,
        "injected_mae": injected_mae,
        "drift_detected": bool(flagged),
        "flagged_features": flagged,
        "top5_features": list(top5),
        "trigger_required": trigger_required,
        "features": injected_rows,
        "limitations": (
            "Controlled offline injection: the recent seven labelled holdout days are "
            "perturbed by a synthetic shift to prove the drift gate and retrain trigger. "
            "No live traffic or database rows are modified; the production drift report "
            "uses the unperturbed window."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=None)
    parser.add_argument("--metadata", type=Path, default=None)
    parser.add_argument("--factor", type=float, default=DEFAULT_FACTOR)
    parser.add_argument("--std-offset", type=float, default=DEFAULT_STD_OFFSET)
    args = parser.parse_args()
    metadata = args.metadata or latest_metadata()
    snapshot = args.snapshot or snapshot_from_metadata(metadata)
    report = build_report(snapshot, metadata, args.factor, args.std_offset)
    if not report["trigger_required"]:
        raise RuntimeError("synthetic drift did not trip the retrain trigger")
    stamp = _now().strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"drift-synthetic_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
