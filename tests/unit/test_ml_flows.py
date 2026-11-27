from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from bmip.flows import ml
from bmip.ml import training

ROOT = Path(__file__).resolve().parents[2]


def test_feature_importance_ranks_tree_features():
    candidate = SimpleNamespace(
        features=("rv_5m", "rv_60m", "sentiment"),
        model=SimpleNamespace(feature_importances_=np.array([0.2, 0.7, 0.1])),
    )

    rows = training.feature_importance(candidate, limit=2)

    assert [row["feature"] for row in rows] == ["rv_60m", "rv_5m"]
    assert rows[0]["importance"] == pytest.approx(0.7)
    assert rows[0]["share"] == pytest.approx(0.7)


def test_feature_importance_falls_back_to_pipeline_coefficients():
    model = SimpleNamespace(named_steps={"model": SimpleNamespace(coef_=np.array([-2.0, 1.0]))})
    candidate = SimpleNamespace(features=("a", "b"), model=model)

    rows = training.feature_importance(candidate)

    assert [row["feature"] for row in rows] == ["a", "b"]
    assert rows[0]["share"] == pytest.approx(2.0 / 3.0)


def test_prefect_config_has_hourly_inference_and_active_retraining():
    config = yaml.safe_load((ROOT / "prefect.yaml").read_text(encoding="utf-8"))
    deployments = {item["name"]: item for item in config["deployments"]}

    inference = deployments["infer-volatility"]
    retraining = deployments["train-volatility"]
    refresh = deployments["refresh-feast"]
    drift = deployments["drift-report"]
    assert inference["schedules"][0]["cron"] == "5 * * * *"
    assert inference["schedules"][0]["active"] is True
    assert retraining["schedules"][0]["cron"] == "0 2 * * 0"
    assert retraining["schedules"][0]["active"] is True
    assert refresh["schedules"][0]["cron"] == "55 * * * *"
    assert drift["schedules"][0]["cron"] == "30 3 * * *"


def test_infer_once_fails_when_any_symbol_is_stale(monkeypatch):
    monkeypatch.setattr(
        ml,
        "run_batch",
        lambda _settings: {
            "failed": True,
            "stale_symbols": ["BTCUSDT"],
        },
    )

    with pytest.raises(RuntimeError, match="BTCUSDT"):
        ml._infer_once()


def test_drift_report_triggers_the_train_deployment(monkeypatch):
    import prefect.deployments as deployments

    monkeypatch.setenv("C3B_TRIGGER_RETRAIN", "true")
    monkeypatch.setattr(ml, "_run_script", lambda _script: {"trigger_required": True})
    calls = {}

    def fake_run_deployment(*, name, timeout):
        calls["name"] = name
        calls["timeout"] = timeout
        return SimpleNamespace(id="child-flow-run")

    monkeypatch.setattr(deployments, "run_deployment", fake_run_deployment)

    result = ml.drift_report_task.fn()

    assert calls == {"name": "train-volatility/train-volatility", "timeout": 0}
    assert result["training_triggered"] is True
    assert result["training_flow_run_id"] == "child-flow-run"


def test_drift_snapshot_follows_the_latest_metadata_path(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "c3b_drift", ROOT / "scripts" / "c3b_drift.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = tmp_path / "mart_ml_new.parquet"
    snapshot.write_bytes(b"snapshot")
    metadata = tmp_path / "dataset_new.json"
    metadata.write_text(json.dumps({"path": str(snapshot)}), encoding="utf-8")

    assert module.snapshot_from_metadata(metadata) == snapshot
