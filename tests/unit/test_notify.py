"""The notifier is the only place that formats an alert message (W2-B)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "bmip_notify", ROOT / "deploy" / "notify" / "notify.py"
)
notify = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(notify)


def _alert(status: str = "firing") -> dict:
    return {
        "status": status,
        "labels": {
            "alertname": "BmipConsumerLagHigh",
            "severity": "warning",
            "alert_class": "stream-lag",
            "owner": "vio",
            "run_id": "run-20261119T1200",
        },
        "annotations": {
            "summary": "Consumer lag 5000 pesan",
            "description": "Processor tertinggal lebih dari 1000 pesan.",
            "impact": "Silver dan gold akan terlambat.",
            "first_step": "Cek lag per partisi.",
            "runbook": "docs/runbooks/alert-stream-freshness.md",
            "runbook_url": "https://example.invalid/runbook",
        },
    }


def test_message_has_status_class_run_id_and_runbook() -> None:
    text = notify.format_message(_alert(), "firing")

    assert text.startswith("[AKTIF] Consumer lag 5000 pesan (peringatan)")
    assert "kelas: stream-lag" in text
    assert "pemilik: vio" in text
    assert "run_id: run-20261119T1200" in text
    assert "Dampak: Silver dan gold akan terlambat." in text
    assert "Langkah pertama: Cek lag per partisi." in text
    assert "Kode: BmipConsumerLagHigh" in text
    assert "runbook: https://example.invalid/runbook" in text


def test_payload_is_written_and_delivery_recorded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(notify, "DATA_DIR", tmp_path)
    monkeypatch.setattr(
        notify,
        "send_telegram",
        lambda text: {"ok": False, "skipped": True, "detail": "no token"},
    )

    results = notify.handle_payload(
        {"status": "firing", "alerts": [_alert()]}
    )

    assert len(results) == 1
    assert results[0]["alert"] == "BmipConsumerLagHigh"
    assert results[0]["telegram"]["skipped"] is True

    stored = [
        json.loads(line)
        for line in (tmp_path / "alerts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert stored[0]["payload"]["status"] == "firing"

    deliveries = [
        json.loads(line)
        for line in (tmp_path / "deliveries.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert deliveries[0]["run_id"] == "run-20261119T1200"


def test_resolved_service_alert_uses_indonesian_and_na_run_id() -> None:
    alert = _alert("resolved")
    alert["labels"]["alert_class"] = "service"
    alert["labels"].pop("run_id")
    alert["annotations"]["summary"] = "Query API tidak bisa di-scrape"

    text = notify.format_message(alert, "resolved")

    assert text.startswith("[SELESAI] Query API tidak bisa di-scrape (peringatan)")
    assert "run_id: n/a (alert service)" in text
