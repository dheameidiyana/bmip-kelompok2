"""Pooled Ridge/XGBoost candidates for E1 and E2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from bmip.ml.dataset import LABEL_COLUMN, feature_columns
from bmip.ml.metrics import per_symbol_metrics, regression_metrics

SEED = 42
RIDGE_ALPHA = 1.0
XGB_PARAMS = {
    "max_depth": 3,
    "n_estimators": 200,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "n_jobs": 2,
    "random_state": SEED,
}


@dataclass
class Candidate:
    name: str
    experiment: str
    algorithm: str
    include_sentiment: bool
    features: tuple[str, ...]
    model: Any
    validation: dict[str, float]
    test: dict[str, float]
    gate: dict[str, float]
    per_symbol: dict[str, dict[str, float]]
    gate_pass: bool


def build_model(algorithm: str):
    if algorithm == "ridge":
        return Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=RIDGE_ALPHA)),
            ]
        )
    if algorithm == "xgboost":
        return XGBRegressor(**XGB_PARAMS)
    raise ValueError(f"unknown algorithm: {algorithm}")


def _predict(model, frame: pd.DataFrame, features: tuple[str, ...]) -> np.ndarray:
    return np.asarray(model.predict(frame[list(features)]), dtype=float)


def _fit(model, frame: pd.DataFrame, features: tuple[str, ...]):
    model.fit(frame[list(features)], frame[LABEL_COLUMN].to_numpy())
    return model


def build_candidate(
    frame: pd.DataFrame,
    *,
    experiment: str,
    algorithm: str,
) -> Candidate:
    include_sentiment = experiment == "E2"
    features = feature_columns(include_sentiment=include_sentiment)
    train = frame[frame["split"] == "train"].reset_index(drop=True)
    validation = frame[frame["split"] == "validation"].reset_index(drop=True)
    test = frame[frame["split"] == "test"].reset_index(drop=True)
    if train.empty or validation.empty or test.empty:
        raise ValueError("dataset split is empty")
    initial = build_model(algorithm)
    _fit(initial, train, features)
    validation_pred = _predict(initial, validation, features)
    validation_metrics = regression_metrics(
        validation[LABEL_COLUMN],
        validation_pred,
        validation["rv_60m"],
    )
    final = build_model(algorithm)
    history = pd.concat([train, validation]).sort_values(["window_start", "symbol"])
    _fit(final, history, features)
    test_pred = _predict(final, test, features)
    test_metrics = regression_metrics(
        test[LABEL_COLUMN],
        test_pred,
        test["rv_60m"],
    )
    last_dates = sorted(test["window_start"].dt.date.unique())[-7:]
    gate_frame = test[test["window_start"].dt.date.isin(last_dates)]
    gate_pred = _predict(final, gate_frame, features)
    gate_metrics = regression_metrics(
        gate_frame[LABEL_COLUMN],
        gate_pred,
        gate_frame["rv_60m"],
    )
    gate_pass = (
        gate_metrics["mae_improvement"] >= 0.05
        and gate_metrics["rmse_change"] <= 0.05
    )
    return Candidate(
        name=f"{experiment.lower()}_{algorithm}",
        experiment=experiment,
        algorithm=algorithm,
        include_sentiment=include_sentiment,
        features=features,
        model=final,
        validation=validation_metrics,
        test=test_metrics,
        gate=gate_metrics,
        per_symbol=per_symbol_metrics(test, test_pred),
        gate_pass=gate_pass,
    )


def select_candidate(candidates: list[Candidate]) -> Candidate:
    if not candidates:
        raise ValueError("no candidates")
    return min(
        candidates,
        key=lambda item: (
            item.validation["mae"],
            item.validation["rmse"],
            item.name,
        ),
    )
