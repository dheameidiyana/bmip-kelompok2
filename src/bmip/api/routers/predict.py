"""Scoring endpoint (W1-D validates, W2-A scores).

Contract:
* malformed body              -> 422 problem+json (Pydantic)
* business out-of-range       -> 200 ``status="error"`` and a row with status=error
* no champion yet             -> 200 ``status="not_available"`` (never a fake value)
* champion + scorer wired     -> 200 ``status="ok"`` (W2-A sets app.state.predictor)
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from bmip.api.deps import (
    build_meta,
    get_clock,
    get_repository,
    get_request_id,
    get_settings,
    validate_symbol,
)
from bmip.api.models import PredictOut, PredictRequest
from bmip.api.routers.model import NO_MODEL_DETAIL
from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.serving.repository import ServingRepository

log = get_logger(__name__)
router = APIRouter(tags=["predict"])

MAX_ABS_FEATURE = 1e6
NON_NEGATIVE_FEATURES = ("rv_5m", "rv_15m", "rv_60m", "volume_z_60m", "post_count_1h")


@router.post(
    "/predict",
    response_model=PredictOut,
    summary="Score the next-hour realized volatility",
)
def predict(
    request: Request,
    response: Response,
    payload: PredictRequest,
    repository: ServingRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> PredictOut:
    symbol = validate_symbol(payload.symbol, settings)
    now, clock = get_clock(request)
    window_start = payload.window_start or now.replace(minute=0, second=0, microsecond=0)
    request_id = get_request_id(request)
    response.headers["X-Data-Source"] = "serving"
    response.headers["X-Data-Stale"] = "false"

    problems = _feature_problems(payload.features)
    if problems:
        repository.insert_prediction(
            symbol=symbol,
            window_start=window_start,
            status="error",
            detail="; ".join(problems),
            request_id=request_id,
            input_hash=_input_hash(payload),
        )
        log.warning(
            "prediction rejected",
            extra={"ctx_request_id": request_id, "ctx_problems": problems},
        )
        return PredictOut(
            status="error",
            symbol=symbol,
            window_start=window_start,
            detail="; ".join(problems),
            meta=build_meta(request, source="serving", stale=False),
        )

    predictor: Callable[[PredictRequest], dict[str, Any]] | None = getattr(
        request.app.state, "predictor", None
    )
    champion = repository.champion()
    if predictor is None or champion is None:
        return PredictOut(
            status="not_available",
            symbol=symbol,
            window_start=window_start,
            detail=NO_MODEL_DETAIL,
            meta=build_meta(request, source="serving", stale=False),
        )

    result = predictor(payload)
    repository.insert_prediction(
        symbol=symbol,
        window_start=window_start,
        status="ok",
        model_name=str(champion["model_name"]),
        model_version=str(champion["version"]),
        model_alias=str(champion.get("alias") or "champion"),
        predicted_rv_next_1h=float(result["predicted_rv_next_1h"]),
        request_id=request_id,
        input_hash=_input_hash(payload),
    )
    return PredictOut(
        status="ok",
        symbol=symbol,
        window_start=window_start,
        predicted_rv_next_1h=float(result["predicted_rv_next_1h"]),
        model_name=str(champion["model_name"]),
        model_version=str(champion["version"]),
        meta=build_meta(request, source="serving", stale=False),
    )


def _feature_problems(features: dict[str, float] | None) -> list[str]:
    if not features:
        return []
    problems: list[str] = []
    for name, value in features.items():
        try:
            number = float(value)
        except (TypeError, ValueError):
            problems.append(f"{name} is not a number")
            continue
        if not math.isfinite(number):
            problems.append(f"{name} is not finite")
        elif abs(number) > MAX_ABS_FEATURE:
            problems.append(f"{name} is outside ±{MAX_ABS_FEATURE:g}")
        elif name in NON_NEGATIVE_FEATURES and number < 0:
            problems.append(f"{name} must be non-negative")
    return problems


def _input_hash(payload: PredictRequest) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
