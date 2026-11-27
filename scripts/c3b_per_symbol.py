"""Train E3 per-symbol models and compare them with the pooled champion."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import pandas as pd

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from bmip.ml.dataset import (
    LABEL_COLUMN,
    load_frozen_snapshot,
    prepare_frame,
    split_frame,
)
from bmip.ml.metrics import regression_metrics
from bmip.ml.per_symbol import (
    aggregate_metrics,
    build_all_symbols,
    inference_comparison,
    symbol_predictions,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = (
    ROOT / "data" / "ml" / "snapshots" / "mart_ml_3627445140691597595.parquet"
)
POOLED_MODEL = ROOT / "data" / "ml" / "models" / "selected.joblib"


def latest_metadata() -> Path:
    paths = sorted((ROOT / "evidence" / "ml").glob("dataset_*.json"))
    if not paths:
        raise FileNotFoundError("no dataset_*.json evidence")
    return paths[-1]


def _pooled_baseline(frame: pd.DataFrame) -> dict[str, Any] | None:
    if not POOLED_MODEL.exists():
        return None
    bundle = joblib.load(POOLED_MODEL)
    model = bundle["model"]
    features = tuple(bundle["features"])
    test = frame[frame["split"] == "test"].copy()
    for name in features:
        if name.startswith("symbol_"):
            test[name] = int(name == f"symbol_{test['symbol'].iloc[0]}")
    predictions = []
    for _, row in test.iterrows():
        values = {feature: row.get(feature, 0.0) for feature in features}
        for name in features:
            if name.startswith("symbol_"):
                values[name] = int(name == f"symbol_{row['symbol']}")
        predictions.append(values)
    test["prediction"] = model.predict(pd.DataFrame(predictions)[list(features)])
    return {
        "model": bundle.get("name"),
        "test": regression_metrics(
            test[LABEL_COLUMN],
            test["prediction"].to_numpy(),
            test["rv_60m"],
        ),
        "per_symbol": {
            symbol: regression_metrics(
                group[LABEL_COLUMN],
                group["prediction"].to_numpy(),
                group["rv_60m"],
            )
            for symbol, group in test.groupby("symbol", sort=True)
        },
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# E3: Pooled vs Per-Symbol",
        "",
        "| Scope | MAE | RMSE | Direction |",
        "|---|---:|---:|---:|",
    ]
    if payload.get("pooled"):
        score = payload["pooled"]["test"]
        lines.append(
            f"| pooled | {score['mae']:.10f} | {score['rmse']:.10f} | "
            f"{score['directional_accuracy']:.4f} |"
        )
    score = payload["per_symbol_aggregate"]
    lines.append(
        f"| per-symbol | {score['mae']:.10f} | {score['rmse']:.10f} | "
        f"{score['directional_accuracy']:.4f} |"
    )
    lines.extend(
        [
            "",
            "## Per-symbol test MAE",
            "",
            "| Symbol | Pooled | Per-symbol | Delta |",
            "|---|---:|---:|---:|",
        ]
    )
    pooled = payload.get("pooled") or {}
    for symbol in sorted(payload["per_symbol"]):
        current = payload["per_symbol"][symbol]["test"]["mae"]
        baseline = (pooled.get("per_symbol") or {}).get(symbol, {}).get("mae")
        delta = None if baseline is None else current - baseline
        lines.append(
            f"| {symbol} | {baseline:.10f} | {current:.10f} | "
            f"{delta:+.10f} |"
            if delta is not None
            else f"| {symbol} | - | {current:.10f} | - |"
        )
    lines.extend(
        [
            "",
            "## Latest inference comparison",
            "",
            "| Symbol | Pooled | Per-symbol | Difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in payload["inference"]:
        pooled_value = row["pooled_predicted_rv_next_1h"]
        lines.append(
            f"| {row['symbol']} | "
            f"{pooled_value if pooled_value is not None else 'n/a'} | "
            f"{row['per_symbol_predicted_rv_next_1h']:.10f} | "
            f"{row['difference'] if row['difference'] is not None else 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "The per-symbol models use the same snapshot, chronological split, "
            "seed, and hyperparameters as the pooled model, but do not receive "
            "`symbol_*` one-hot features. The pooled model remains the champion; "
            "this is a comparison-only experiment.",
            "",
        ]
    )
    return "\n".join(lines)


def _plot(payload: dict[str, Any], path: Path) -> None:
    rows = [row for row in payload["inference"] if row["difference"] is not None]
    if not rows:
        return
    symbols = [row["symbol"] for row in rows]
    pooled = [float(row["pooled_predicted_rv_next_1h"]) * 1e6 for row in rows]
    per_symbol = [
        float(row["per_symbol_predicted_rv_next_1h"]) * 1e6 for row in rows
    ]
    x = range(len(symbols))
    width = 0.38
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([value - width / 2 for value in x], pooled, width, label="pooled")
    ax.bar([value + width / 2 for value in x], per_symbol, width, label="per-symbol")
    ax.set_ylabel("Predicted RV next 1h (x1e-6)")
    ax.set_title("Latest inference: pooled vs per-symbol")
    ax.set_xticks(list(x), symbols)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--metadata", type=Path, default=None)
    args = parser.parse_args()
    metadata = args.metadata or latest_metadata()
    snapshot = load_frozen_snapshot(args.snapshot, metadata)
    frame = split_frame(prepare_frame(snapshot.frame))
    candidates = build_all_symbols(frame)
    predictions = symbol_predictions(frame[frame["split"] == "test"], candidates)
    aggregate = aggregate_metrics(predictions)
    pooled = _pooled_baseline(frame)
    inference = inference_comparison(frame, candidates, None)
    if POOLED_MODEL.exists():
        bundle = joblib.load(POOLED_MODEL)
        inference = inference_comparison(
            frame, candidates, (bundle["model"], tuple(bundle["features"]))
        )
    payload: dict[str, Any] = {
        "id": "C3-B-E3-per-symbol",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "sha256": snapshot.sha256,
        "per_symbol_aggregate": aggregate,
        "per_symbol": {
            symbol: {
                "algorithm": candidate.algorithm,
                "validation": candidate.validation,
                "test": candidate.test,
                "gate": candidate.gate,
                "gate_pass": candidate.gate_pass,
                "importance": candidate.importance,
            }
            for symbol, candidate in candidates.items()
        },
        "pooled": pooled,
        "inference": inference,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = ROOT / "evidence" / "ml" / f"per-symbol_{stamp}.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    csv_path = ROOT / "evidence" / "ml" / f"inference-compare_{stamp}.csv"
    pd.DataFrame(inference).to_csv(csv_path, index=False)
    png_path = ROOT / "evidence" / "ml" / f"inference-compare_{stamp}.png"
    _plot(payload, png_path)
    md_path = ROOT / "evidence" / "experiments" / "E3_vs_pooled.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_markdown(payload), encoding="utf-8")
    model_path = ROOT / "data" / "ml" / "models" / "per_symbol.joblib"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "models": {symbol: candidate.model for symbol, candidate in candidates.items()},
            "features": next(iter(candidates.values())).features,
            "dataset_id": snapshot.dataset_id,
        },
        model_path,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
