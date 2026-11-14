"""Public service routes: health, discovery, and metrics (W1-D).

These routes are deliberately unauthenticated. ``e2e_smoke.py`` (W1-A gate)
probes ``/api`` and the container healthcheck probes ``/health/ready``; putting
auth in front of them would break a gate that is older than this slot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse

from bmip.api.deps import build_meta, get_clock, get_instance, get_lake, get_repository
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
    summary="Prometheus metrics (minimal, W2-B extends)",
)
def metrics(request: Request) -> str:
    state = request.app.state.metrics
    lines = [
        "# HELP bmip_api_requests_total HTTP requests served by the Query API.",
        "# TYPE bmip_api_requests_total counter",
    ]
    for status in sorted(state["by_status"]):
        lines.append(
            f'bmip_api_requests_total{{status="{status}"}} {state["by_status"][status]}'
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
        ]
    )
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
