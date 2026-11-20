"""Tests for the batch metrics registry and Pushgateway helper (W2-B)."""

from __future__ import annotations

import urllib.request

import pytest

from bmip.observability.metrics import (
    Registry,
    Sample,
    batch_run,
    push,
    render_samples,
)


def test_render_groups_help_and_type_per_metric() -> None:
    registry = Registry("test")
    registry.set("bmip_gold_rows", 3, {"table": "mart_market"}, help="Rows published.")
    registry.set("bmip_gold_rows", 1, {"table": "mart_ml"}, help="Rows published.")
    registry.set("bmip_dq_failures_total", 0, kind="counter", help="Failures.")

    text = registry.render()

    assert text.count("# HELP bmip_gold_rows") == 1
    assert text.count("# TYPE bmip_gold_rows gauge") == 1
    assert 'bmip_gold_rows{table="mart_market"} 3' in text
    assert 'bmip_gold_rows{table="mart_ml"} 1' in text
    assert "# TYPE bmip_dq_failures_total counter" in text


def test_inc_accumulates_per_label_set() -> None:
    registry = Registry()
    registry.inc("bmip_dq_failures_total", 2, {"severity": "critical"})
    registry.inc("bmip_dq_failures_total", 1, {"severity": "critical"})
    registry.inc("bmip_dq_failures_total", 5, {"severity": "warning"})

    assert registry.get("bmip_dq_failures_total", {"severity": "critical"}) == 3
    assert registry.get("bmip_dq_failures_total", {"severity": "warning"}) == 5


def test_render_escapes_label_values() -> None:
    text = render_samples([Sample("bmip_probe", 1, {"path": 'a"b\n'}, "Probe.")])
    assert 'bmip_probe{path="a\\"b\\n"} 1' in text


def test_push_is_skipped_without_a_gateway(monkeypatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    registry = Registry()
    registry.set("bmip_gold_rows", 1)
    assert push(registry, "gold") is False


def test_push_posts_to_the_job_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["method"] = request.get_method()
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    registry = Registry()
    registry.set("bmip_gold_rows", 2)

    assert push(registry, "gold", gateway="http://pushgateway:9091", instance="n1")
    assert captured["url"] == "http://pushgateway:9091/metrics/job/gold/instance/n1"
    assert captured["method"] == "POST"
    assert b"bmip_gold_rows 2" in captured["data"]


def test_batch_run_records_duration_and_success(monkeypatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    with batch_run("gold") as registry:
        registry.set("bmip_gold_rows", 3)

    assert registry.get(
        "bmip_batch_duration_seconds", {"job": "gold", "status": "ok"}
    ) >= 0
    assert registry.get("bmip_last_success_timestamp_seconds", {"job": "gold"}) > 0


def test_batch_run_marks_failures(monkeypatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    with pytest.raises(RuntimeError):
        with batch_run("gold") as registry:
            raise RuntimeError("boom")

    assert registry.get("bmip_last_success_timestamp_seconds", {"job": "gold"}) == 0
    assert registry.get(
        "bmip_batch_duration_seconds", {"job": "gold", "status": "failed"}
    ) >= 0


def test_registry_applies_default_labels() -> None:
    registry = Registry("gold", {"run_id": "gold-1"})
    registry.set("bmip_gold_rows", 3, {"table": "mart_market"})

    rendered = registry.render()

    assert 'run_id="gold-1"' in rendered
    assert 'table="mart_market"' in rendered


def test_batch_run_labels_every_sample_with_run_id(monkeypatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    monkeypatch.delenv("BMIP_RUN_ID", raising=False)

    with batch_run("gold") as registry:
        registry.set("bmip_gold_rows", 1, {"table": "mart_market"})

    sample = next(
        item for item in registry.samples() if item.name == "bmip_gold_rows"
    )
    assert sample.labels["run_id"].startswith("gold-")
    assert sample.labels["table"] == "mart_market"


def test_last_success_has_no_run_id_label(monkeypatch) -> None:
    monkeypatch.delenv("PUSHGATEWAY_URL", raising=False)
    monkeypatch.delenv("BMIP_RUN_ID", raising=False)

    with batch_run("quality") as registry:
        pass

    sample = next(
        item
        for item in registry.samples()
        if item.name == "bmip_last_success_timestamp_seconds"
    )
    assert "run_id" not in sample.labels
    assert sample.labels["job"] == "quality"
