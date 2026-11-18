"""W2-A application factory that wires the champion predictor into W1-D."""

from __future__ import annotations

from fastapi import FastAPI

from bmip.api.main import create_app as create_base_app
from bmip.common.config import get_settings
from bmip.common.logging import get_logger
from bmip.ml.predictor import VolatilityPredictor

log = get_logger(__name__)


def create_app() -> FastAPI:
    app = create_base_app()
    settings = get_settings()
    try:
        app.state.predictor = VolatilityPredictor(settings)
        log.info("champion predictor loaded")
    except Exception as exc:  # noqa: BLE001 - serve not_available instead of crashing
        app.state.predictor = None
        log.warning("champion predictor unavailable", extra={"ctx_error": str(exc)})
    return app
