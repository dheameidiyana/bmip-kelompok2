"""Public service routes: health, discovery, and metrics (W1-D).

These routes are deliberately unauthenticated. ``e2e_smoke.py`` (W1-A gate)
probes ``/api`` and the container healthcheck probes ``/health/ready``; putting
auth in front of them would break a gate that is older than this slot.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from bmip.api.deps import (
    build_meta,
    freshness_payload,
    get_clock,
    get_instance,
    get_lake,
    get_repository,
)
from bmip.serving.repository import ServingRepository

public_router = APIRouter()
v1_router = APIRouter(prefix="/v1", tags=["meta"])

ENDPOINTS = [
    "GET /v1/meta/instance",
    "GET /v1/market/latest",
    "GET /v1/market/ohlc",
    "GET /v1/market/volatility/latest",
    "GET /v1/market/volatility/range",
    "GET /v1/sentiment/latest",
    "GET /v1/sentiment/hourly",
    "GET /v1/sentiment/range",
    "GET /v1/freshness",
    "GET /v1/dataset",
    "GET /v1/dataset/{id}/schema",
    "GET /v1/quality/status",
    "GET /v1/model/latest",
    "POST /v1/predict",
]


@public_router.get("/api", summary="Service discovery (public)")
def api_index(request: Request) -> dict[str, Any]:
    app = request.app
    now, clock = get_clock(request)
    return {
        "service": "bmip-api",
        "version": app.state.version,
        "commit": app.state.commit,
        "instance": app.state.instance,
        "env": app.state.settings.env,
        "clock": clock,
        "as_of": now.isoformat(),
        "endpoints": ENDPOINTS,
        "health": ["/health/live", "/health/ready"],
        "docs": ["/docs", "/openapi.json"],
    }


@public_router.get("/health/live", summary="Liveness")
def health_live(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "bmip-api",
        "instance": get_instance(request),
        "uptime_seconds": round(request.app.state.uptime(), 3),
    }


@public_router.get("/health/ready", summary="Readiness (lake or serving)")
def health_ready(
    request: Request,
    response: Response,
    repository: ServingRepository = Depends(get_repository),
    lake=Depends(get_lake),
) -> dict[str, Any]:
    postgres = repository.ping()
    try:
        lake_ok = bool(lake.health())
    except Exception:  # noqa: BLE001 - readiness must never raise
        lake_ok = False
    ready = postgres or lake_ok
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "unavailable",
        "checks": {"lake": lake_ok, "serving": postgres},
        "instance": get_instance(request),
        "detail": None
        if ready
        else "Neither the lake path nor the serving path is usable.",
    }


@public_router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics for the Query API and the serving freshness",
)
def metrics(
    request: Request,
    repository: ServingRepository = Depends(get_repository),
) -> str:
    state = request.app.state.metrics
    lines = [
        "# HELP bmip_api_requests_total HTTP requests served by the Query API.",
        "# TYPE bmip_api_requests_total counter",
    ]
    for status in sorted(state["by_status"]):
        lines.append(
            f'bmip_api_requests_total{{status="{status}"}} {state["by_status"][status]}'
        )
    feature_age = state.get("feature_age_seconds") or {}
    lines.extend(
        [
            "# HELP bmip_feature_age_seconds Age of the feature row used for scoring.",
            "# TYPE bmip_feature_age_seconds gauge",
        ]
    )
    for symbol in sorted(feature_age):
        lines.append(
            f'bmip_feature_age_seconds{{symbol="{symbol}"}} '
            f"{float(feature_age[symbol]):.3f}"
        )
    lines.extend(
        [
            "# HELP bmip_api_errors_total Unhandled errors.",
            "# TYPE bmip_api_errors_total counter",
            f"bmip_api_errors_total {state['errors']}",
            "# HELP bmip_api_fallback_total Range queries answered from PostgreSQL.",
            "# TYPE bmip_api_fallback_total counter",
            f"bmip_api_fallback_total {state['fallbacks']}",
            "# HELP bmip_api_request_duration_seconds_sum Total request time.",
            "# TYPE bmip_api_request_duration_seconds_sum counter",
            f"bmip_api_request_duration_seconds_sum {state['duration']:.6f}",
            "# HELP bmip_api_request_duration_seconds_count Requests timed.",
            "# TYPE bmip_api_request_duration_seconds_count counter",
            f"bmip_api_request_duration_seconds_count {state['timed']}",
            "# HELP bmip_api_start_time_seconds Process start time.",
            "# TYPE bmip_api_start_time_seconds gauge",
            f"bmip_api_start_time_seconds {state['started_epoch']}",
            "# HELP bmip_api_uptime_seconds Seconds since the process started.",
            "# TYPE bmip_api_uptime_seconds gauge",
            f"bmip_api_uptime_seconds {max(0.0, time.time() - state['started_epoch']):.3f}",
            "# HELP bmip_api_info Build identity of this replica.",
            "# TYPE bmip_api_info gauge",
            f'bmip_api_info{{version="{request.app.state.version}",'
            f'commit="{request.app.state.commit}",'
            f'instance="{request.app.state.instance}"}} 1',
        ]
    )

    # Serving freshness is the signal the pipeline alerts read. The endpoint
    # must stay scrapeable even when the serving tier is empty, so every
    # failure degrades to "no freshness samples" instead of a 500.
    try:
        now, clock = get_clock(request)
        rows = repository.freshness()
        freshness_lines = [
            "# HELP bmip_freshness_seconds Age of the newest serving row.",
            "# TYPE bmip_freshness_seconds gauge",
            "# HELP bmip_freshness_slo_seconds Freshness SLO for the dataset.",
            "# TYPE bmip_freshness_slo_seconds gauge",
        ]
        for row in rows:
            payload = freshness_payload(row, now=now, clock=clock) if row else None
            if not payload or payload.get("age_seconds") is None:
                continue
            dataset = str(payload["metric"])
            freshness_lines.append(
                f'bmip_freshness_seconds{{dataset="{dataset}"}} '
                f'{float(payload["age_seconds"]):.3f}'
            )
            freshness_lines.append(
                f'bmip_freshness_slo_seconds{{dataset="{dataset}"}} '
                f'{int(payload["slo_seconds"])}'
            )
        lines.extend(freshness_lines)
    except Exception:  # noqa: BLE001 - a scrape must never take the API down
        pass

    return "\n".join(lines) + "\n"


@v1_router.get("/meta/instance", summary="Replica identity")
def instance(request: Request) -> dict[str, Any]:
    now, clock = get_clock(request)
    return {
        "data": {
            "instance": get_instance(request),
            "version": request.app.state.version,
            "commit": request.app.state.commit,
            "env": request.app.state.settings.env,
            "started_at": datetime.fromtimestamp(
                request.app.state.started_epoch, tz=UTC
            ).isoformat(),
            "uptime_seconds": round(request.app.state.uptime(), 3),
        },
        "meta": build_meta(request, source="memory", stale=False).model_dump(
            mode="json"
        ),
    }
