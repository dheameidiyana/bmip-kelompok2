"""Regression and directional metrics for the volatility model."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from bmip.ml.dataset import LABEL_COLUMN


def regression_metrics(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
    baseline: pd.Series | np.ndarray,
) -> dict[str, float]:
    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    b = np.asarray(baseline, dtype=float)
    error = y - p
    base_error = y - b
    mae = float(np.mean(np.abs(error)))
    rmse = float(math.sqrt(np.mean(error**2)))
    base_mae = float(np.mean(np.abs(base_error)))
    base_rmse = float(math.sqrt(np.mean(base_error**2)))
    direction = float(np.mean(np.sign(p - b) == np.sign(y - b)))
    return {
        "mae": mae,
        "rmse": rmse,
        "baseline_mae": base_mae,
        "baseline_rmse": base_rmse,
        "mae_improvement": (base_mae - mae) / base_mae if base_mae else 0.0,
        "rmse_change": (rmse - base_rmse) / base_rmse if base_rmse else 0.0,
        "directional_accuracy": direction,
    }


def per_symbol_metrics(
    frame: pd.DataFrame,
    predictions: np.ndarray,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for symbol, group in frame.groupby("symbol", sort=True):
        result[str(symbol)] = regression_metrics(
            group["label_rv_next_1h"],
            predictions[group.index],
            group["rv_60m"],
        )
    return result


def ewma_baseline(frame: pd.DataFrame, alpha: float = 0.06) -> pd.Series:
    values = []
    for _, group in frame.sort_values(["symbol", "window_start"]).groupby("symbol"):
        series = group["rv_60m"].ewm(alpha=alpha, adjust=False).mean().shift(1)
        values.append(series)
    if not values:
        return pd.Series(dtype=float)
    return pd.concat(values).sort_index()


def regression_scores(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
) -> dict[str, float]:
    """Score one prediction series without a reference baseline."""

    y = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    error = y - p
    mae = float(np.mean(np.abs(error)))
    rmse = float(math.sqrt(np.mean(error**2)))
    variance = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(error**2)) / variance if variance else 0.0
    spearman = float(pd.Series(y).corr(pd.Series(p), method="spearman"))
    return {
        "count": int(len(y)),
        "mae": mae,
        "rmse": rmse,
        "r2": r2,
        "spearman": spearman,
    }


def baseline_metrics(
    frame: pd.DataFrame,
    *,
    alpha: float = 0.06,
    splits: tuple[str, ...] = ("validation", "test"),
) -> dict[str, dict[str, dict[str, float]]]:
    """Persistence and EWMA scores on the requested chronological splits.

    ``alpha=0.06`` is equivalent to the architecture's ``lambda=0.94`` and the
    EWMA is shifted one hour so the prediction never sees the target window.
    """

    scored = frame.copy()
    scored["_ewma"] = ewma_baseline(scored, alpha=alpha)
    result: dict[str, dict[str, dict[str, float]]] = {}
    for split in splits:
        subset = scored[scored["split"] == split]
        result[split] = {
            "persistence": regression_scores(
                subset[LABEL_COLUMN],
                subset["rv_60m"],
            ),
            "ewma": regression_scores(
                subset[LABEL_COLUMN],
                subset["_ewma"],
            ),
        }
    return result


def metrics_payload(metrics: dict[str, Any]) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in metrics.items()
        if isinstance(value, (int, float, np.floating))
    }
