"""Minimal Prometheus text metrics for the stream processor."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

STREAM_METRICS: dict[str, tuple[str, str]] = {
    "bmip_ingest_events_total": ("Total market events received from Redpanda", "counter"),
    "bmip_duplicate_total": ("Duplicate market events skipped", "counter"),
    "bmip_quarantine_total": ("Market events rejected or quarantined", "counter"),
    "bmip_late_events_total": ("Market events corrected inside the late window", "counter"),
    "bmip_consumer_lag": ("Sum of partition lag for the consumer group", "gauge"),
    "bmip_batch_size": ("Records returned by the last poll", "gauge"),
    "bmip_commit_total": ("Kafka offset commits issued", "counter"),
    "bmip_ohlcv_rows_total": ("OHLCV minute rows written to silver", "counter"),
    "bmip_stream_poll_total": ("Consumer poll calls", "counter"),
    "bmip_freshness_seconds": ("Max ingest-to-event lag for silver market rows", "gauge"),
    "bmip_silver_bar_age_seconds": (
        "Seconds between now and the newest silver OHLCV window end",
        "gauge",
    ),
    "bmip_last_event_timestamp_seconds": (
        "Unix timestamp of the newest event received",
        "gauge",
    ),
}


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, float] = {}
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def declare(self, name: str, help_text: str, metric_type: str = "gauge") -> None:
        with self._lock:
            self._help[name] = help_text
            self._types[name] = metric_type
            self._values.setdefault(name, 0.0)

    def declare_all(self, metrics: dict[str, tuple[str, str]]) -> None:
        for name, (help_text, metric_type) in metrics.items():
            self.declare(name, help_text, metric_type)

    def inc(self, name: str, value: float = 1.0) -> float:
        with self._lock:
            current = self._values.get(name, 0.0)
            self._values[name] = current + value
            return self._values[name]

    def set(self, name: str, value: float) -> float:
        with self._lock:
            self._values[name] = float(value)
            return self._values[name]

    def get(self, name: str) -> float:
        with self._lock:
            return self._values.get(name, 0.0)

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def render(self) -> str:
        with self._lock:
            names = sorted(self._values)
            lines: list[str] = []
            for name in names:
                help_text = self._help.get(name, name)
                metric_type = self._types.get(name, "gauge")
                value = self._values[name]
                lines.append(f"# HELP {name} {help_text}")
                lines.append(f"# TYPE {name} {metric_type}")
                lines.append(f"{name} {format_value(value)}")
            return "\n".join(lines) + "\n"


def format_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _handler(metrics: Metrics) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "bmip-stream-metrics/0.1"

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path == "/health":
                body = b'{"status":"ok"}\n'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path in ("/metrics", "/"):
                body = metrics.render().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    return Handler


class MetricsServer:
    def __init__(self, metrics: Metrics, host: str, port: int) -> None:
        self._server = ThreadingHTTPServer((host, port), _handler(metrics))
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="bmip-metrics",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        host = str(self._server.server_address[0])
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return f"http://{host}:{self.port}"

    def start(self) -> MetricsServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def build_stream_metrics() -> Metrics:
    metrics = Metrics()
    metrics.declare_all(STREAM_METRICS)
    return metrics
