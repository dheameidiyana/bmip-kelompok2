"""Pure pandas analytics for the dashboard.

The UI must not fabricate a correlation when the joined history is too short.
All functions return empty frames or explicit ``n`` counts so the caller can
show an honest "data belum cukup" state.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_PAIRS = 24
FULL_PAIRS = 48


def utc_frame(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["window_start"] = pd.to_datetime(frame["window_start"], utc=True).dt.tz_localize(None)
    return frame.sort_values("window_start").reset_index(drop=True)


def log_returns(frame: pd.DataFrame, column: str = "close") -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(frame[column], errors="coerce")
    returns = np.log(values / values.shift(1))
    return returns.replace([np.inf, -np.inf], np.nan)


def normalized(frame: pd.DataFrame, column: str = "close") -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype="float64")
    values = pd.to_numeric(frame[column], errors="coerce")
    first = values.dropna()
    if first.empty or first.iloc[0] == 0:
        return pd.Series(index=frame.index, dtype="float64")
    return values / first.iloc[0] * 100.0


def align_close(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Inner-join close series on window_start; one column per symbol."""
    series = []
    for symbol, frame in frames.items():
        if frame.empty or "window_start" not in frame or "close" not in frame:
            continue
        item = frame.set_index("window_start")["close"].astype(float).rename(symbol)
        series.append(item)
    if not series:
        return pd.DataFrame()
    aligned = pd.concat(series, axis=1, join="inner").dropna(how="any")
    return aligned.sort_index()


def returns_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    aligned = align_close(frames)
    if aligned.empty:
        return aligned
    return np.log(aligned / aligned.shift(1)).replace([np.inf, -np.inf], np.nan).dropna(how="any")


def volatility_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    series = []
    for symbol, frame in frames.items():
        if frame.empty or "window_start" not in frame or "realized_vol_1h" not in frame:
            continue
        item = frame.set_index("window_start")["realized_vol_1h"].astype(float).rename(symbol)
        series.append(item)
    if not series:
        return pd.DataFrame()
    return pd.concat(series, axis=1, join="inner").dropna(how="any").sort_index()


def correlation_matrix(frame: pd.DataFrame, method: str = "pearson") -> pd.DataFrame:
    if frame.empty or frame.shape[1] < 2 or len(frame) < MIN_PAIRS:
        return pd.DataFrame()
    return frame.corr(method=method)


def sample_status(n: int) -> str:
    if n >= FULL_PAIRS:
        return "full"
    if n >= MIN_PAIRS:
        return "small"
    return "insufficient"


def pairwise_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    if matrix.empty:
        return pd.DataFrame(columns=["pair", "correlation"])
    rows = []
    columns = list(matrix.columns)
    for i, left in enumerate(columns):
        for right in columns[i + 1 :]:
            rows.append(
                {"pair": f"{left} / {right}", "correlation": float(matrix.loc[left, right])}
            )
    return pd.DataFrame(rows).sort_values("correlation", ascending=False).reset_index(drop=True)


def rolling_correlation(
    frame: pd.DataFrame,
    left: str,
    right: str,
    window: int = 24,
) -> pd.DataFrame:
    if frame.empty or left not in frame or right not in frame or len(frame) < window + 1:
        return pd.DataFrame(columns=["window_start", "correlation"])
    corr = frame[left].rolling(window).corr(frame[right]).dropna()
    result = corr.rename("correlation").reset_index()
    if "index" in result.columns:
        result = result.rename(columns={"index": "window_start"})
    return result


def lead_lag(
    frame: pd.DataFrame,
    left: str,
    right: str,
    max_lag: int = 3,
) -> pd.DataFrame:
    if frame.empty or left not in frame or right not in frame or len(frame) < MIN_PAIRS:
        return pd.DataFrame(columns=["lag", "correlation"])
    rows = []
    for lag in range(-max_lag, max_lag + 1):
        shifted = frame[right].shift(lag)
        pair = pd.concat([frame[left], shifted], axis=1).dropna()
        if len(pair) < MIN_PAIRS:
            continue
        rows.append({"lag": lag, "correlation": float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))})
    return pd.DataFrame(rows)
