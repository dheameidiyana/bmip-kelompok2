"""FastAPI application factory for the BMIP Query API (W1-D).

Run with ``uvicorn bmip.api.main:create_app --factory`` so importing this
module never requires a configured environment (tests build their own app).
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from bmip.api.deps import require_api_key
from bmip.api.errors import ApiProblem, problem_response
from bmip.api.lake import build_lake
from bmip.api.routers import (
    dataset,
    freshness,
    market,
    meta,
    model,
    predict,
    quality,
    sentiment,
)
from bmip.common.config import Settings, get_settings
from bmip.common.logging import configure_logging, get_logger
from bmip.serving.repository import ServingNotReady

log = get_logger("bmip.api")

VERSION = "0.2.0-w1d"
ROOT = Path(__file__).resolve().parents[3]

DESCRIPTION = """
Read-only query layer for the Bitcoin Market Intelligence Platform.

* Market, sentiment, volatility, freshness, catalogue, quality, and model routes.
* Range queries read Iceberg through DuckDB and fall back to the PostgreSQL
  serving tables, marking the response with ``X-Data-Stale: true``.
* Errors follow RFC 7807 (``application/problem+json``) and carry ``request_id``.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="BMIP Query API",
        version=VERSION,
        description=DESCRIPTION,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    started = time.time()
    app.state.settings = settings
    app.state.instance = os.getenv("BMIP_INSTANCE", socket.gethostname())
    app.state.version = VERSION
    app.state.commit = _commit()
    app.state.started_epoch = started
    app.state.uptime = lambda: time.time() - started
    app.state.lake = build_lake(settings)
    app.state.predictor = None
    app.state.metrics = {
        "by_status": defaultdict(int),
        "errors": 0,
        "fallbacks": 0,
        "duration": 0.0,
        "timed": 0,
        "started_epoch": round(started, 3),
    }

    _register_middleware(app)
    _register_exception_handlers(app)

    app.include_router(meta.public_router)
    app.include_router(meta.v1_router, dependencies=[Depends(require_api_key)])
    for module in (market, sentiment, freshness, dataset, quality, model, predict):
        app.include_router(
            module.router, prefix="/v1", dependencies=[Depends(require_api_key)]
        )
    app.include_router(
        dataset.catalog_router, prefix="/v1", dependencies=[Depends(require_api_key)]
    )
    return app


def _register_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req-{uuid4().hex[:16]}"
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            request.app.state.metrics["errors"] += 1
            raise
        elapsed = time.perf_counter() - started
        metrics = request.app.state.metrics
        metrics["duration"] += elapsed
        metrics["timed"] += 1
        metrics["by_status"][f"{response.status_code // 100}xx"] += 1
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        log.info(
            "http_request",
            extra={
                "ctx_request_id": request_id,
                "ctx_method": request.method,
                "ctx_path": request.url.path,
                "ctx_status": response.status_code,
                "ctx_duration_ms": round(elapsed * 1000, 2),
                "ctx_instance": request.app.state.instance,
            },
        )
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem):
        return problem_response(
            request,
            status=exc.status,
            slug=exc.slug,
            title=exc.title,
            detail=exc.detail,
            headers=exc.headers,
            extra=exc.extra,
        )

    @app.exception_handler(ServingNotReady)
    async def serving_not_ready_handler(request: Request, exc: ServingNotReady):
        return problem_response(
            request,
            status=503,
            slug="serving-not-initialised",
            title="Serving tier is empty",
            detail=str(exc),
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = [
            {
                "loc": list(error.get("loc", ())),
                "msg": str(error.get("msg", "")),
                "type": str(error.get("type", "")),
            }
            for error in exc.errors()
        ]
        return problem_response(
            request,
            status=422,
            slug="validation-error",
            title="Request validation failed",
            detail=f"{len(errors)} parameter(s) are invalid.",
            extra={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        slugs = {404: "not-found", 405: "method-not-allowed"}
        return problem_response(
            request,
            status=exc.status_code,
            slug=slugs.get(exc.status_code, "http-error"),
            title=str(exc.detail),
            detail=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        log.exception(
            "unhandled api error",
            extra={
                "ctx_request_id": getattr(request.state, "request_id", "unknown"),
                "ctx_path": request.url.path,
            },
        )
        return problem_response(
            request,
            status=500,
            slug="internal-error",
            title="Internal server error",
            detail="The request failed. Quote the request_id when reporting it.",
        )


def _commit() -> str:
    configured = os.getenv("BMIP_COMMIT")
    if configured:
        return configured
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            ).stdout.strip()
            or "unknown"
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
