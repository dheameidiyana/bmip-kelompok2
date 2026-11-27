"""Structured JSON logging shared by all BMIP services (W2-B).

Every line carries the six fields the workplan asks for:

``timestamp``, ``severity``, ``service``, ``run_id``, ``request_id``, ``message``

``run_id`` and ``request_id`` are only emitted when the caller knows them; a
missing value is omitted rather than printed as ``null`` so a grep for
``"request_id"`` only returns lines that actually have one.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_state: dict[str, str] = {
    "service": os.getenv("BMIP_SERVICE", "bmip"),
    "run_id": os.getenv("BMIP_RUN_ID", ""),
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "severity": record.levelname,
            "service": _state["service"],
            "logger": record.name,
            "message": record.getMessage(),
        }
        if _state["run_id"]:
            payload["run_id"] = _state["run_id"]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str | None = None, service: str | None = None) -> None:
    if service:
        _state["service"] = service
    formatter = JsonFormatter()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    log_file = os.getenv("BMIP_LOG_FILE")
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    root.setLevel((level or os.getenv("BMIP_LOG_LEVEL", "INFO")).upper())


def set_service(service: str) -> None:
    _state["service"] = service


def set_run_id(run_id: str) -> None:
    _state["run_id"] = run_id


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
