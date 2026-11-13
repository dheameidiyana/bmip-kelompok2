"""Tests for the stream metrics registry and HTTP exposition."""

from __future__ import annotations

import urllib.request

from bmip.transform.metrics import MetricsServer, build_stream_metrics, format_value


def test_metrics_render_prometheus_text() -> None:
    metrics = build_stream_metrics()
    metrics.inc("bmip_ingest_events_total", 3)
    metrics.set("bmip_consumer_lag", 5)
    text = metrics.render()
    assert "# TYPE bmip_ingest_events_total counter" in text
    assert "bmip_ingest_events_total 3" in text
    assert "bmip_consumer_lag 5" in text


def test_metrics_inc_set_get() -> None:
    metrics = build_stream_metrics()
    assert metrics.get("bmip_duplicate_total") == 0
    metrics.inc("bmip_duplicate_total", 2)
    metrics.inc("bmip_duplicate_total")
    metrics.set("bmip_batch_size", 7)
    assert metrics.get("bmip_duplicate_total") == 3
    assert metrics.get("bmip_batch_size") == 7
    assert metrics.snapshot()["bmip_batch_size"] == 7


def test_metrics_server_serves_metrics_and_health() -> None:
    metrics = build_stream_metrics()
    metrics.set("bmip_consumer_lag", 11)
    server = MetricsServer(metrics, "127.0.0.1", 0).start()
    try:
        with urllib.request.urlopen(f"{server.url}/metrics", timeout=5) as response:
            body = response.read().decode("utf-8")
        assert response.status == 200
        assert "bmip_consumer_lag 11" in body
        with urllib.request.urlopen(f"{server.url}/health", timeout=5) as response:
            assert response.status == 200
    finally:
        server.stop()


def test_format_value() -> None:
    assert format_value(3.0) == "3"
    assert format_value(1.25) == "1.25"
    assert format_value(0.0) == "0"
