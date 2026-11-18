"""Hourly batch inference for all configured symbols."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from mlflow.tracking import MlflowClient

from bmip.common.config import Settings
from bmip.ml.dataset import latest_feature_row
from bmip.ml.predictor import VolatilityPredictor


def _hash(row: dict[str, Any]) -> str:
    raw = json.dumps(
        {key: row[key] for key in sorted(row) if key not in {"window_start"}},
        default=str,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _write_cache(rows: dict[str, dict[str, Any]]) -> None:
    path = Path(os.getenv("ML_FEATURE_CACHE", "data/ml/latest_features.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "symbols": rows,
            },
            default=str,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def run_batch(settings: Settings) -> dict[str, Any]:
    predictor = VolatilityPredictor(settings)
    version = MlflowClient().get_model_version_by_alias(
        "volatility_model", "champion"
    ).version
    request_id = f"batch-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    results: dict[str, Any] = {}
    cache_rows: dict[str, dict[str, Any]] = {}
    with psycopg.connect(settings.postgres_dsn) as connection:
        for symbol in settings.market_symbols:
            latest = latest_feature_row(settings, symbol)
            if latest is None:
                results[symbol] = {"status": "error", "detail": "no feature row"}
                _insert(
                    connection,
                    settings,
                    symbol=symbol,
                    window_start=datetime.now(UTC).replace(
                        minute=0, second=0, microsecond=0
                    ),
                    feature_ts=None,
                    status="error",
                    detail="no feature row",
                    model_version=version,
                    predicted=None,
                    input_hash=None,
                    request_id=request_id,
                )
                continue
            cache_rows[symbol] = latest
            row = {feature: latest.get(feature) for feature in predictor.features}
            for feature in predictor.features:
                if feature.startswith("symbol_"):
                    row[feature] = int(feature == f"symbol_{symbol}")
                if row[feature] is None:
                    row[feature] = 0.0
            frame = pd.DataFrame([row])
            for feature in predictor.features:
                if feature.startswith("symbol_"):
                    frame[feature] = frame[feature].astype("int32")
            predicted = float(predictor.model.predict(frame)[0])
            results[symbol] = {
                "status": "ok",
                "predicted_rv_next_1h": predicted,
                "feature_ts": latest["window_start"].isoformat(),
            }
            _insert(
                connection,
                settings,
                symbol=symbol,
                window_start=latest["window_start"],
                feature_ts=latest["window_start"],
                status="ok",
                detail=None,
                model_version=version,
                predicted=predicted,
                input_hash=_hash(row),
                request_id=request_id,
            )
        connection.commit()
    _write_cache(cache_rows)
    return {
        "request_id": request_id,
        "model_name": "volatility_model",
        "model_version": version,
        "symbols": results,
    }


def _insert(
    connection,
    settings: Settings,
    *,
    symbol: str,
    window_start: datetime,
    feature_ts: datetime | None,
    status: str,
    detail: str | None,
    model_version: str,
    predicted: float | None,
    input_hash: str | None,
    request_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO serving.predictions
            (symbol, window_start, model_version, model_name, model_alias,
             predicted_rv_next_1h, feature_ts, predicted_at, status, detail,
             request_id, input_hash)
        VALUES (%s, %s, %s, 'volatility_model', 'champion', %s, %s, now(),
                %s, %s, %s, %s)
        ON CONFLICT (symbol, window_start, model_version) DO UPDATE SET
            predicted_rv_next_1h = EXCLUDED.predicted_rv_next_1h,
            feature_ts = EXCLUDED.feature_ts,
            predicted_at = now(),
            status = EXCLUDED.status,
            detail = EXCLUDED.detail,
            request_id = EXCLUDED.request_id,
            input_hash = EXCLUDED.input_hash
        """,
        (
            symbol,
            window_start,
            model_version,
            predicted,
            feature_ts,
            status,
            detail,
            request_id,
            input_hash,
        ),
    )
