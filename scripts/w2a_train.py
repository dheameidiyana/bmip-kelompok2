"""Train E1/E2 candidates, log them to MLflow, and register the winner."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import mlflow
import mlflow.pyfunc
import mlflow.sklearn
import mlflow.xgboost
import pandas as pd
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient

from bmip.common.config import get_settings
from bmip.ml.dataset import (
    load_mart_ml,
    save_snapshot,
    sentiment_coverage,
    write_metadata,
)
from bmip.ml.metrics import baseline_metrics
from bmip.ml.registry import record_decision, upsert_model_metric
from bmip.ml.training import (
    SEED,
    XGB_PARAMS,
    Candidate,
    build_candidate,
    select_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "volatility"
REGISTERED_MODEL = "volatility_model"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_champion() -> tuple[Any, tuple[str, ...]] | None:
    tracking = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
    mlflow.set_tracking_uri(tracking)
    try:
        model = mlflow.pyfunc.load_model(
            f"models:/{REGISTERED_MODEL}@champion"
        )
        signature = model.metadata.signature
        if signature is None or signature.inputs is None:
            return None
        return model, tuple(field.name for field in signature.inputs)
    except Exception:
        return None


def candidate_metrics(prefix: str, values: dict[str, float]) -> dict[str, float]:
    return {f"{prefix}_{key}": float(value) for key, value in values.items()}


def run_candidate(candidate: Candidate, snapshot, frame: pd.DataFrame) -> dict[str, Any]:
    with mlflow.start_run(run_name=candidate.name):
        mlflow.set_tags(
            {
                "experiment": candidate.experiment,
                "algorithm": candidate.algorithm,
                "dataset_id": snapshot.dataset_id,
                "dataset_snapshot_id": snapshot.snapshot_id,
                "data_snapshot_id": snapshot.snapshot_id,
                "feature_snapshot_id": "dev",
                "feature_version": "features/v1",
                "trigger": "manual",
                "git_sha": git_sha(),
                "seed": str(SEED),
            }
        )
        mlflow.log_params(
            {
                "algorithm": candidate.algorithm,
                "include_sentiment": candidate.include_sentiment,
                "seed": SEED,
                "feature_count": len(candidate.features),
                "ridge_alpha": 1.0,
                **{f"xgb_{key}": value for key, value in XGB_PARAMS.items()},
            }
        )
        mlflow.log_metrics(candidate_metrics("validation", candidate.validation))
        mlflow.log_metrics(candidate_metrics("test", candidate.test))
        mlflow.log_metrics(candidate_metrics("gate", candidate.gate))
        for symbol, metrics in candidate.per_symbol.items():
            mlflow.log_metrics(
                {f"test_{symbol}_{key}": float(value) for key, value in metrics.items()}
            )
        mlflow.log_dict(
            {
                "feature_columns": list(candidate.features),
                "per_symbol": candidate.per_symbol,
                "gate_pass": candidate.gate_pass,
                "dataset": {
                    "dataset_id": snapshot.dataset_id,
                    "sha256": snapshot.sha256,
                    "counts": snapshot.counts,
                },
            },
            "candidate.json",
        )
        return {"run_id": mlflow.active_run().info.run_id}


def log_best(candidate: Candidate, snapshot, frame: pd.DataFrame) -> dict[str, Any]:
    features = candidate.features
    validation = frame[frame["split"] == "validation"]
    example = validation[list(features)].head(2)
    predicted = candidate.model.predict(example)
    signature = infer_signature(example, predicted)
    with mlflow.start_run(run_name=f"registered_{candidate.name}") as run:
        mlflow.set_tags(
            {
                "experiment": candidate.experiment,
                "algorithm": candidate.algorithm,
                "selected": "true",
                "dataset_id": snapshot.dataset_id,
                "dataset_snapshot_id": snapshot.snapshot_id,
                "data_snapshot_id": snapshot.snapshot_id,
                "feature_snapshot_id": "dev",
                "feature_version": "features/v1",
                "trigger": "manual",
                "git_sha": git_sha(),
            }
        )
        if candidate.algorithm == "xgboost":
            info = mlflow.xgboost.log_model(
                candidate.model,
                name="model",
                signature=signature,
                input_example=example,
                registered_model_name=REGISTERED_MODEL,
            )
        else:
            info = mlflow.sklearn.log_model(
                candidate.model,
                name="model",
                signature=signature,
                input_example=example,
                registered_model_name=REGISTERED_MODEL,
            )
        mlflow.log_metrics(candidate_metrics("validation", candidate.validation))
        mlflow.log_metrics(candidate_metrics("test", candidate.test))
        mlflow.log_metrics(candidate_metrics("gate", candidate.gate))
        version = str(info.registered_model_version)
        client = MlflowClient()
        client.set_registered_model_alias(REGISTERED_MODEL, "challenger", version)
        if candidate.gate_pass:
            client.set_registered_model_alias(REGISTERED_MODEL, "champion", version)
        return {
            "run_id": run.info.run_id,
            "version": version,
            "gate_pass": candidate.gate_pass,
            "champion": candidate.gate_pass,
        }


def model_card(candidate: Candidate, snapshot, selection_note: str) -> str:
    rows = [
        "# Volatility Model Card",
        "",
        "## Intended use",
        "One-hour realized-volatility prediction for five Binance spot USDT pairs.",
        "",
        "## Data",
        f"- Dataset: `{snapshot.dataset_id}`",
        f"- Snapshot SHA-256: `{snapshot.sha256}`",
        f"- Rows: {snapshot.row_count}",
        f"- Symbols: {', '.join(sorted(snapshot.counts))}",
        f"- Range: {snapshot.start.isoformat()} to {snapshot.end.isoformat()}",
        f"- Sentiment coverage: {sentiment_coverage(snapshot.frame):.2%}",
        f"- Selection note: {selection_note or 'E2 selected on validation MAE.'}",
        "",
        "## Features",
        ", ".join(f"`{feature}`" for feature in candidate.features),
        "",
        "## Split and label",
        "Chronological 70/15/15 by event date, seed 42, no shuffle. Label is",
        "`label_rv_next_1h`; features end before the label window.",
        "",
        "## Metrics",
        f"- Validation MAE: {candidate.validation['mae']:.10f}",
        f"- Validation RMSE: {candidate.validation['rmse']:.10f}",
        f"- Validation directional accuracy: {candidate.validation['directional_accuracy']:.4f}",
        f"- Test MAE: {candidate.test['mae']:.10f}",
        f"- Test RMSE: {candidate.test['rmse']:.10f}",
        f"- Test directional accuracy: {candidate.test['directional_accuracy']:.4f}",
        f"- Gate MAE improvement: {candidate.gate['mae_improvement']:.4%}",
        f"- Gate passed: {candidate.gate_pass}",
        f"- Gate comparison: {candidate.gate.get('comparison', 'persistence-baseline')}",
        "",
        "## Baselines",
        "",
        "| Split | Baseline | Count | MAE | RMSE | R2 | Spearman |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    baselines = baseline_metrics(snapshot.frame)
    for split in ("validation", "test"):
        for name in ("persistence", "ewma"):
            score = baselines[split][name]
            rows.append(
                f"| {split} | {name} | {score['count']} | {score['mae']:.10f} | "
                f"{score['rmse']:.10f} | {score['r2']:.4f} | {score['spearman']:.4f} |"
            )
    rows.extend(
        [
            "",
            "## Per-symbol test MAE",
        ]
    )
    for symbol, metrics in sorted(candidate.per_symbol.items()):
        rows.append(f"- {symbol}: {metrics['mae']:.10f}")
    rows.extend(
        [
            "",
            "## Out-of-scope use",
            "- Do not use this model as financial advice, a trading signal, "
            "or a risk-management system.",
            "- Do not apply it to symbols outside the five trained Binance spot USDT pairs.",
            "",
            "## Limitations",
            "- The model is pooled across five symbols and is not a general market model.",
            "- Sentiment features are market-wide, not symbol-specific.",
            "- The historical backfill uses 1-minute klines, not raw trade ticks.",
            "- Source lineage for kline-only hours falls back to `binance_ws`.",
            "",
            "## Ethical note",
            "This output is a volatility estimate, not financial advice. Do not use it",
            "as an investment recommendation or as the sole basis for trading decisions.",
            "",
        ]
    )
    return "\n".join(rows)


def comparison(candidates: list[Candidate]) -> str:
    lines = [
        "# E1 vs E2",
        "",
        "| Candidate | Validation MAE | Validation RMSE | Validation Direction | "
        "Test MAE | Test RMSE | Test Direction | Gate MAE improvement | Gate pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for candidate in candidates:
        lines.append(
            "| {name} | {vmae:.10f} | {vrmse:.10f} | {vd:.4f} | "
            "{tmae:.10f} | {trmse:.10f} | {td:.4f} | {g:.4%} | {p} |".format(
                name=candidate.name,
                vmae=candidate.validation["mae"],
                vrmse=candidate.validation["rmse"],
                vd=candidate.validation["directional_accuracy"],
                tmae=candidate.test["mae"],
                trmse=candidate.test["rmse"],
                td=candidate.test["directional_accuracy"],
                g=candidate.gate["mae_improvement"],
                p=candidate.gate_pass,
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--snapshot", type=Path, default=None)
    args = parser.parse_args()

    settings = get_settings()
    frame, snapshot_id = load_mart_ml(settings)
    snapshot = save_snapshot(settings, frame, snapshot_id)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    metadata_path = ROOT / "evidence" / "ml" / f"dataset_{stamp}.json"
    write_metadata(snapshot, metadata_path)
    champion = load_champion()
    candidates = [
        build_candidate(
            snapshot.frame,
            experiment=experiment,
            algorithm=algorithm,
            champion=champion,
        )
        for experiment in ("E1", "E2")
        for algorithm in ("ridge", "xgboost")
    ]
    best = select_candidate(candidates)
    coverage = sentiment_coverage(snapshot.frame)
    selection_note = ""
    if best.experiment == "E2" and coverage < 0.05:
        best = select_candidate(
            [candidate for candidate in candidates if candidate.experiment == "E1"]
        )
        selection_note = (
            f"E2 did not add signal because sentiment coverage is {coverage:.2%}; "
            "the market-only E1 candidate is promoted per the H0 policy."
        )
    elif best.experiment == "E2":
        selection_note = "E2 won on validation MAE with usable sentiment coverage."
    else:
        selection_note = "E1 won on validation MAE."
    card = model_card(best, snapshot, selection_note)
    card_path = ROOT / "evidence" / "ml" / "model-card.md"
    card_path.write_text(card, encoding="utf-8")
    comparison_path = ROOT / "evidence" / "experiments" / "E1_vs_E2.md"
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison_path.write_text(comparison(candidates), encoding="utf-8")
    model_dir = ROOT / "data" / "ml" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": best.model,
            "features": list(best.features),
            "name": best.name,
            "dataset_id": snapshot.dataset_id,
            "snapshot_id": snapshot.snapshot_id,
        },
        model_dir / "selected.joblib",
    )
    registry = None
    if not args.no_mlflow:
        tracking = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
        mlflow.set_tracking_uri(tracking)
        mlflow.set_experiment(EXPERIMENT)
        for candidate in candidates:
            run_candidate(candidate, snapshot, snapshot.frame)
        registry = log_best(best, snapshot, snapshot.frame)
        MlflowClient().log_artifact(
            registry["run_id"],
            str(card_path),
            artifact_path="model_card",
        )
        serving_metrics = {
            "dataset_id": snapshot.dataset_id,
            "snapshot_id": snapshot.snapshot_id,
            "sha256": snapshot.sha256,
            "validation": best.validation,
            "test": best.test,
            "gate": best.gate,
            "per_symbol": best.per_symbol,
            "sentiment_coverage": coverage,
            "selection_note": selection_note,
        }
        upsert_model_metric(
            settings,
            version=registry["version"],
            alias="champion" if registry["champion"] else "challenger",
            metrics=serving_metrics,
        )
        record_decision(
            settings,
            champion_version=registry["version"] if registry["champion"] else None,
            challenger_version=registry["version"],
            decision="promoted" if registry["champion"] else "rejected",
            reason=selection_note,
            metrics=serving_metrics,
        )
    result = {
        "timestamp": stamp,
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "sha256": snapshot.sha256,
        "best": best.name,
        "gate_pass": best.gate_pass,
        "gate_comparison": best.gate.get("comparison"),
        "sentiment_coverage": coverage,
        "selection_note": selection_note,
        "registry": registry,
        "candidates": [
            {
                "name": candidate.name,
                "validation": candidate.validation,
                "test": candidate.test,
                "gate": candidate.gate,
                "gate_pass": candidate.gate_pass,
                "per_symbol": candidate.per_symbol,
            }
            for candidate in candidates
        ],
    }
    output = ROOT / "evidence" / "ml" / f"train_{stamp}.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
