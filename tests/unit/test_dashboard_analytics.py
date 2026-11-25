from __future__ import annotations

import numpy as np
import pandas as pd

from bmip.dashboard import analytics


def _frame(symbol: str, hours: int = 60, base: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(abs(hash(symbol)) % (2**32))
    steps = rng.normal(0.0, 0.005, hours)
    close = base * np.exp(np.cumsum(steps))
    return pd.DataFrame(
        {
            "window_start": pd.date_range("2026-11-01", periods=hours, freq="h"),
            "close": close,
            "realized_vol_1h": np.abs(steps),
        }
    )


def test_log_returns_first_row_is_nan():
    frame = _frame("BTCUSDT", 10)
    returns = analytics.log_returns(frame)
    assert np.isnan(returns.iloc[0])
    assert returns.iloc[1:].notna().all()


def test_align_close_inner_join():
    frames = {"BTCUSDT": _frame("BTCUSDT", 5), "ETHUSDT": _frame("ETHUSDT", 5).iloc[1:]}
    aligned = analytics.align_close(frames)
    assert list(aligned.columns) == ["BTCUSDT", "ETHUSDT"]
    assert len(aligned) == 4


def test_correlation_matrix_has_diagonal_one():
    frames = {name: _frame(name, 60) for name in ("BTCUSDT", "ETHUSDT", "BNBUSDT")}
    matrix = analytics.correlation_matrix(analytics.returns_frame(frames))
    assert matrix.shape == (3, 3)
    assert np.allclose(np.diag(matrix), 1.0)


def test_sample_status_gate():
    assert analytics.sample_status(23) == "insufficient"
    assert analytics.sample_status(24) == "small"
    assert analytics.sample_status(48) == "full"


def test_insufficient_data_returns_empty_correlation():
    frames = {name: _frame(name, 5) for name in ("BTCUSDT", "ETHUSDT")}
    assert analytics.correlation_matrix(analytics.returns_frame(frames)).empty


def test_rolling_correlation_length():
    frames = {name: _frame(name, 60) for name in ("BTCUSDT", "ETHUSDT")}
    rolling = analytics.rolling_correlation(
        analytics.returns_frame(frames), "BTCUSDT", "ETHUSDT", 24
    )
    assert not rolling.empty
    assert rolling["correlation"].between(-1, 1).all()


def test_lead_lag_range():
    frames = {name: _frame(name, 60) for name in ("BTCUSDT", "ETHUSDT")}
    lag = analytics.lead_lag(analytics.returns_frame(frames), "BTCUSDT", "ETHUSDT", max_lag=3)
    assert list(lag["lag"]) == [-3, -2, -1, 0, 1, 2, 3]


def test_normalized_starts_at_100():
    frame = _frame("BTCUSDT", 10)
    values = analytics.normalized(frame)
    assert round(float(values.iloc[0]), 6) == 100.0
