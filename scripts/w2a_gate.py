"""Prove reproducibility (T-20) and a rejected challenger (T-21)."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature
from mlflow.tracking import MlflowClient
from sklearn.dummy import DummyRegressor

from bmip.common.config import get_settings
from bmip.ml.dataset import load_mart_ml, save_snapshot, sentiment_coverage
from bmip.ml.metrics import regression_metrics
from bmip.ml.registry import record_decision, upsert_model_metric
from bmip.ml.training import build_candidate, select_candidate

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = "volatility"
MODEL_NAME = "volatility_model"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def select_market_best(snapshot):
    candidates = [
        build_candidate(snapshot.frame, experiment=experiment, algorithm=algorithm)
        for experiment in ("E1", "E2")
        for algorithm in ("ridge", "xgboost")
    ]
    best = select_candidate(candidates)
    coverage = sentiment_coverage(snapshot.frame)
    if best.experiment == "E2" and coverage < 0.05:
        best = select_candidate(
            [candidate for candidate in candidates if candidate.experiment == "E1"]
        )
    return best, coverage


def latest_train_result() -> dict[str, Any]:
    paths = sorted((ROOT / "evidence" / "ml").glob("train_*.json"))
    if not paths:
        raise FileNotFoundError("no train_*.json evidence")
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def t20(snapshot, best, reference: dict[str, Any]) -> bool:
    reference_best = reference.get("best")
    reference_candidate = next(
        item for item in reference["candidates"] if item["name"] == reference_best
    )
    reference_mae = float(reference_candidate["validation"]["mae"])
    current_mae = float(best.validation["mae"])
    delta = abs(current_mae - reference_mae) / reference_mae if reference_mae else 1.0
    passed = delta <= 0.01
    lines = [
        "T-20 model reproducibility",
        f"dataset_id       : {snapshot.dataset_id}",
        f"snapshot_id      : {snapshot.snapshot_id}",
        f"sha256           : {snapshot.sha256}",
        f"reference model  : {reference_best}",
        f"reference MAE    : {reference_mae:.12f}",
        f"retrained model  : {best.name}",
        f"retrained MAE    : {current_mae:.12f}",
        f"relative delta   : {delta:.8%}",
        "tolerance        : 1.00%",
        f"result           : {'PASS' if passed else 'FAIL'}",
    ]
    path = ROOT / "evidence" / "ml" / "T20.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return passed


def t21(settings, snapshot, best) -> bool:
    tracking = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    mlflow.set_tracking_uri(tracking)
    mlflow.set_experiment(EXPERIMENT)
    client = MlflowClient()
    champion_before = client.get_model_version_by_alias(MODEL_NAME, "champion")
    test = snapshot.frame[snapshot.frame["split"] == "test"].reset_index(drop=True)
    last_dates = sorted(test["window_start"].dt.date.unique())[-7:]
    gate = test[test["window_start"].dt.date.isin(last_dates)].reset_index(drop=True)
    features = list(best.features)
    bad = DummyRegressor(strategy="mean")
    train = snapshot.frame[snapshot.frame["split"] == "train"]
    bad.fit(train[features], train["label_rv_next_1h"])
    prediction = bad.predict(gate[features])
    metrics = regression_metrics(
        gate["label_rv_next_1h"],
        prediction,
        gate["rv_60m"],
    )
    gate_pass = metrics["mae_improvement"] >= 0.05 and metrics["rmse_change"] <= 0.05
    example = gate[features].head(2)
    signature = infer_signature(example, bad.predict(example))
    with mlflow.start_run(run_name="t21_bad_challenger"):
        info = mlflow.sklearn.log_model(
            bad,
            name="model",
            signature=signature,
            input_example=example,
            registered_model_name=MODEL_NAME,
        )
        version = str(info.registered_model_version)
        client.set_registered_model_alias(MODEL_NAME, "challenger", version)
    champion_after = client.get_model_version_by_alias(MODEL_NAME, "champion")
    payload = {
        "id": "T-21",
        "timestamp": datetime.now(UTC).isoformat(),
        "champion_before": champion_before.version,
        "champion_after": champion_after.version,
        "challenger_version": version,
        "gate_pass": gate_pass,
        "metrics": metrics,
        "pass": (not gate_pass) and champion_before.version == champion_after.version,
    }
    path = ROOT / "evidence" / "ml" / "T21.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not gate_pass:
        upsert_model_metric(
            settings,
            version=version,
            alias="challenger",
            metrics={"gate": metrics, "reason": "T-21 deliberately bad challenger"},
        )
        record_decision(
            settings,
            champion_version=champion_before.version,
            challenger_version=version,
            decision="rejected",
            reason="T-21 challenger failed the 5% MAE promotion gate.",
            metrics={"gate": metrics},
        )
    return payload["pass"]


def main() -> int:
    settings = get_settings()
    frame, snapshot_id = load_mart_ml(settings)
    snapshot = save_snapshot(settings, frame, snapshot_id)
    best, coverage = select_market_best(snapshot)
    reference = latest_train_result()
    t20_pass = t20(snapshot, best, reference)
    t21_pass = t21(settings, snapshot, best)
    result = {
        "T20": t20_pass,
        "T21": t21_pass,
        "best": best.name,
        "sentiment_coverage": coverage,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if t20_pass and t21_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
