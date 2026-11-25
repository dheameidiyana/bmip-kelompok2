"""Champion predictor that uses the MLflow registry and latest gold features."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd

from bmip.api.models import PredictRequest
from bmip.common.config import Settings
from bmip.ml.dataset import latest_feature_row

MARKET_FEATURES = {
    "ret_5m",
    "ret_15m",
    "ret_60m",
    "rv_5m",
    "rv_15m",
    "rv_60m",
    "volume_z_60m",
    "trade_count_60m",
    "hl_range_1m",
    "vwap_dev",
}


class VolatilityPredictor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        tracking = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
        mlflow.set_tracking_uri(tracking)
        self.model = mlflow.pyfunc.load_model(
            "models:/volatility_model@champion"
        )
        signature = self.model.metadata.signature
        if signature is None or signature.inputs is None:
            raise RuntimeError("champion model has no input signature")
        self.features = tuple(field.name for field in signature.inputs)
        cache_path = os.getenv("ML_FEATURE_CACHE")
        self.cache: dict[str, dict[str, Any]] | None = None
        if cache_path:
            self.cache = {}
            try:
                payload = json.loads(Path(cache_path).read_text(encoding="utf-8"))
                self.cache = dict(payload.get("symbols") or {})
            except (OSError, ValueError, TypeError):
                self.cache = {}

    def _row(
        self,
        payload: PredictRequest,
        *,
        feature_ts: datetime,
    ) -> dict[str, Any] | None:
        latest = None
        if self.cache is not None:
            latest = self.cache.get(payload.symbol)
        else:
            latest = latest_feature_row(
                self.settings,
                payload.symbol,
                at=payload.window_start or datetime.now(UTC),
            )
        row: dict[str, Any] = {}
        if latest is not None:
            row.update(latest)
            if isinstance(row.get("window_start"), str):
                row["window_start"] = pd.to_datetime(row["window_start"], utc=True)
        if payload.features:
            row.update(payload.features)
        for feature in self.features:
            if feature.startswith("symbol_"):
                row[feature] = int(feature == f"symbol_{payload.symbol}")
        missing = [
            feature
            for feature in self.features
            if feature not in row or pd.isna(row[feature])
        ]
        if any(feature in MARKET_FEATURES for feature in missing):
            return None
        for feature in missing:
            row[feature] = 0.0
        row.setdefault("window_start", feature_ts)
        return row

    def __call__(self, payload: PredictRequest) -> dict[str, Any] | None:
        return self.predict(payload)

    def predict(self, payload: PredictRequest) -> dict[str, Any] | None:
        feature_ts = payload.window_start or datetime.now(UTC).replace(
            minute=0,
            second=0,
            microsecond=0,
        )
        row = self._row(payload, feature_ts=feature_ts)
        if row is None:
            return None
        frame = pd.DataFrame([{feature: row[feature] for feature in self.features}])
        for feature in self.features:
            if feature.startswith("symbol_"):
                frame[feature] = frame[feature].astype("int32")
        predicted = float(self.model.predict(frame)[0])
        return {
            "predicted_rv_next_1h": predicted,
            "feature_ts": row.get("window_start", feature_ts),
        }
