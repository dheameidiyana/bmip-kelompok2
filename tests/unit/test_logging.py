"""The JSON log contract from workplan W2-B (six fields)."""

from __future__ import annotations

import json
import logging

from bmip.common.logging import JsonFormatter, set_run_id, set_service


def _record(message: str = "http_request", level: int = logging.INFO):
    return logging.LogRecord(
        "bmip.api", level, __file__, 12, message, None, None
    )


def test_formatter_emits_the_six_contract_fields() -> None:
    set_service("api")
    set_run_id("run-20261119T1200")
    record = _record()
    record.ctx_request_id = "req-abc123"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["timestamp"].startswith("20")
    assert payload["severity"] == "INFO"
    assert payload["service"] == "api"
    assert payload["run_id"] == "run-20261119T1200"
    assert payload["request_id"] == "req-abc123"
    assert payload["message"] == "http_request"


def test_error_severity_and_exception_are_recorded() -> None:
    set_service("gold")
    set_run_id("")
    try:
        raise ValueError("bad row")
    except ValueError:
        import sys

        record = logging.LogRecord(
            "bmip.gold",
            logging.ERROR,
            __file__,
            30,
            "gold build failed",
            None,
            sys.exc_info(),
        )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["severity"] == "ERROR"
    assert "run_id" not in payload
    assert "ValueError: bad row" in payload["exception"]


def test_configure_logging_sets_the_service(monkeypatch) -> None:
    from bmip.common import logging as logging_module

    logging_module.configure_logging("INFO", service="stream")
    record = _record()
    payload = json.loads(JsonFormatter().format(record))
    assert payload["service"] == "stream"

    # Restore the default so other tests do not inherit this service name.
    set_service("bmip")
