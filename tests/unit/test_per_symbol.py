from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from bmip.ml.dataset import MARKET_FEATURES
from bmip.ml.per_symbol import build_symbol_candidate


def _frame(symbol: str) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rows = []
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(60):
        row = {
            "symbol": symbol,
            "window_start": start + timedelta(hours=index),
            "split": "train" if index < 40 else ("validation" if index < 50 else "test"),
            "rv_60m": 0.001 + index * 0.00001,
            "label_rv_next_1h": 0.001 + index * 0.00001 + rng.normal(0, 0.00001),
        }
        for feature in MARKET_FEATURES:
            row[feature] = float(rng.normal())
        rows.append(row)
    return pd.DataFrame(rows)


def test_symbol_candidate_uses_market_features_without_symbol_one_hot():
    candidate = build_symbol_candidate(_frame("BTCUSDT"), "BTCUSDT")

    assert candidate.features == tuple(MARKET_FEATURES)
    assert not any(feature.startswith("symbol_") for feature in candidate.features)
    assert candidate.test["mae"] > 0
    assert candidate.importance
