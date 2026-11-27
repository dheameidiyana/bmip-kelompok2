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
from bmip.ml.features import latest_features
from bmip.ml.predictor import VolatilityPredictor

MAX_FEATURE_AGE_SECONDS = 7200


def _as_of(settings: Settings) -> datetime:
    if settings.bmip_as_of:
        parsed = datetime.fromisoformat(settings.bmip_as_of.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return datetime.now(UTC)


def _hash(row: dict[str, Any]) -> str:
    raw = json.dumps(
        {key: row[key] for key in sorted(row) if key not in {"window_start"}},
        default=str,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_feature_cache(rows: dict[str, dict[str, Any]]) -> None:
    path = Path(os.getenv("ML_FEATURE_CACHE", "data/ml/latest_features.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
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
    temporary.replace(path)


def run_batch(settings: Settings) -> dict[str, Any]:
    predictor = VolatilityPredictor(settings)
    version = MlflowClient().get_model_version_by_alias(
        "volatility_model", "champion"
    ).version
    now = _as_of(settings)
    request_id = f"batch-{now.strftime('%Y%m%dT%H%M%SZ')}"
    results: dict[str, Any] = {}
    cache_rows: dict[str, dict[str, Any]] = {}
    stale_symbols: list[str] = []
    failed = False
    with psycopg.connect(settings.postgres_dsn) as connection:
        for symbol in settings.market_symbols:
            latest = latest_features(settings, symbol, at=now)
            if latest is None:
                failed = True
                results[symbol] = {"status": "error", "detail": "no feature row"}
                _insert(
                    connection,
                    settings,
                    symbol=symbol,
                    window_start=now.replace(minute=0, second=0, microsecond=0),
                    feature_ts=None,
                    status="error",
                    detail="no feature row",
                    model_version=version,
                    predicted=None,
                    input_hash=None,
                    request_id=request_id,
                )
                continue
            feature_ts = pd.Timestamp(latest["window_start"]).to_pydatetime()
            age_seconds = (now - feature_ts).total_seconds()
            if age_seconds > MAX_FEATURE_AGE_SECONDS:
                failed = True
                stale_symbols.append(symbol)
                detail = (
                    f"latest feature is {age_seconds:.0f}s old; "
                    f"maximum is {MAX_FEATURE_AGE_SECONDS}s"
                )
                results[symbol] = {
                    "status": "error",
                    "detail": detail,
                    "feature_ts": feature_ts.isoformat(),
                    "age_seconds": age_seconds,
                }
                _insert(
                    connection,
                    settings,
                    symbol=symbol,
                    window_start=feature_ts,
                    feature_ts=feature_ts,
                    status="error",
                    detail=detail,
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
            if row.get("trade_count_60m") is not None:
                row["trade_count_60m"] = int(row["trade_count_60m"])
            frame = pd.DataFrame([row])
            for feature in predictor.features:
                if feature.startswith("symbol_"):
                    frame[feature] = frame[feature].astype("int32")
            predicted = float(predictor.model.predict(frame)[0])
            results[symbol] = {
                "status": "ok",
                "predicted_rv_next_1h": predicted,
                "feature_ts": feature_ts.isoformat(),
                "age_seconds": age_seconds,
            }
            _insert(
                connection,
                settings,
                symbol=symbol,
                window_start=feature_ts,
                feature_ts=feature_ts,
                status="ok",
                detail=None,
                model_version=version,
                predicted=predicted,
                input_hash=_hash(row),
                request_id=request_id,
            )
        connection.commit()
    if cache_rows and not failed:
        write_feature_cache(cache_rows)
    return {
        "request_id": request_id,
        "as_of": now.isoformat(),
        "model_name": "volatility_model",
        "model_version": version,
        "failed": failed,
        "stale_symbols": stale_symbols,
        "max_feature_age_seconds": MAX_FEATURE_AGE_SECONDS,
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
