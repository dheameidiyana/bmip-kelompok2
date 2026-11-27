"""Per-symbol volatility models and pooled-vs-per-symbol comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from bmip.ml.dataset import LABEL_COLUMN, MARKET_FEATURES
from bmip.ml.metrics import regression_metrics
from bmip.ml.training import build_model, feature_importance


@dataclass
class SymbolCandidate:
    symbol: str
    algorithm: str
    features: tuple[str, ...]
    model: Any
    validation: dict[str, float]
    test: dict[str, float]
    gate: dict[str, float]
    gate_pass: bool
    importance: list[dict[str, float | str]]


def _fit(model, frame: pd.DataFrame, features: tuple[str, ...]):
    model.fit(frame[list(features)], frame[LABEL_COLUMN].to_numpy())
    return model


def _predict(model, frame: pd.DataFrame, features: tuple[str, ...]) -> np.ndarray:
    return np.asarray(model.predict(frame[list(features)]), dtype=float)


def build_symbol_candidate(
    frame: pd.DataFrame,
    symbol: str,
    *,
    algorithm: str = "xgboost",
) -> SymbolCandidate:
    features = tuple(MARKET_FEATURES)
    subset = frame[frame["symbol"] == symbol].sort_values("window_start")
    train = subset[subset["split"] == "train"].reset_index(drop=True)
    validation = subset[subset["split"] == "validation"].reset_index(drop=True)
    test = subset[subset["split"] == "test"].reset_index(drop=True)
    if train.empty or validation.empty or test.empty:
        raise ValueError(f"not enough rows for {symbol}")
    initial = _fit(build_model(algorithm), train, features)
    validation_metrics = regression_metrics(
        validation[LABEL_COLUMN],
        _predict(initial, validation, features),
        validation["rv_60m"],
    )
    final = _fit(
        build_model(algorithm),
        pd.concat([train, validation]).sort_values("window_start"),
        features,
    )
    test_pred = _predict(final, test, features)
    test_metrics = regression_metrics(
        test[LABEL_COLUMN],
        test_pred,
        test["rv_60m"],
    )
    last_dates = sorted(test["window_start"].dt.date.unique())[-7:]
    gate = test[test["window_start"].dt.date.isin(last_dates)]
    gate_pred = _predict(final, gate, features)
    gate_metrics = regression_metrics(
        gate[LABEL_COLUMN],
        gate_pred,
        gate["rv_60m"],
    )
    gate_pass = (
        gate_metrics["mae_improvement"] >= 0.05
        and gate_metrics["rmse_change"] <= 0.05
    )
    candidate = SymbolCandidate(
        symbol=symbol,
        algorithm=algorithm,
        features=features,
        model=final,
        validation=validation_metrics,
        test=test_metrics,
        gate=gate_metrics,
        gate_pass=gate_pass,
        importance=[],
    )
    candidate.importance = feature_importance(candidate)
    return candidate


def build_all_symbols(
    frame: pd.DataFrame,
    *,
    algorithm: str = "xgboost",
) -> dict[str, SymbolCandidate]:
    return {
        symbol: build_symbol_candidate(frame, symbol, algorithm=algorithm)
        for symbol in sorted(frame["symbol"].unique())
    }


def symbol_predictions(
    frame: pd.DataFrame,
    candidates: dict[str, SymbolCandidate],
) -> pd.DataFrame:
    rows = []
    for symbol, candidate in candidates.items():
        subset = frame[frame["symbol"] == symbol].copy()
        subset["prediction"] = _predict(
            candidate.model, subset, candidate.features
        )
        rows.append(subset)
    return pd.concat(rows, ignore_index=True)


def aggregate_metrics(frame: pd.DataFrame) -> dict[str, float]:
    return regression_metrics(
        frame[LABEL_COLUMN],
        frame["prediction"].to_numpy(),
        frame["rv_60m"],
    )


def per_symbol_metrics(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        symbol: regression_metrics(
            group[LABEL_COLUMN],
            group["prediction"].to_numpy(),
            group["rv_60m"],
        )
        for symbol, group in frame.groupby("symbol", sort=True)
    }


def inference_comparison(
    frame: pd.DataFrame,
    candidates: dict[str, SymbolCandidate],
    pooled: tuple[Any, tuple[str, ...]] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, candidate in candidates.items():
        latest = frame[frame["symbol"] == symbol].sort_values("window_start").tail(1)
        if latest.empty:
            continue
        per_symbol_pred = float(
            _predict(candidate.model, latest, candidate.features)[0]
        )
        pooled_pred = None
        if pooled is not None:
            model, features = pooled
            input_frame = latest.copy()
            for name in features:
                if name.startswith("symbol_"):
                    input_frame[name] = int(name == f"symbol_{symbol}")
            pooled_pred = float(model.predict(input_frame[list(features)])[0])
        rows.append(
            {
                "symbol": symbol,
                "feature_ts": latest["window_start"].iloc[0].isoformat(),
                "pooled_predicted_rv_next_1h": pooled_pred,
                "per_symbol_predicted_rv_next_1h": per_symbol_pred,
                "difference": None
                if pooled_pred is None
                else per_symbol_pred - pooled_pred,
            }
        )
    return rows
