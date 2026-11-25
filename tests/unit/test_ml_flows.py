from __future__ import annotations

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


def test_prefect_config_has_hourly_inference_and_inactive_retraining():
    config = yaml.safe_load((ROOT / "prefect.yaml").read_text(encoding="utf-8"))
    deployments = {item["name"]: item for item in config["deployments"]}

    inference = deployments["infer-volatility"]
    retraining = deployments["train-volatility"]
    assert inference["schedules"][0]["cron"] == "5 * * * *"
    assert inference["schedules"][0]["active"] is True
    assert retraining["schedules"][0]["cron"] == "0 2 * * 0"
    assert retraining["schedules"][0]["active"] is False


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
