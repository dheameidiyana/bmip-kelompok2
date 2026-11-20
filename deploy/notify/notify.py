#!/usr/bin/env python3
"""Alertmanager webhook receiver for BMIP (W2-B).

Alertmanager posts the standard webhook payload here. The receiver does three
things, in this order:

1. append the raw payload to ``$NOTIFY_DATA_DIR/alerts.jsonl`` (always);
2. format one message per alert and send it to Telegram (when a bot token and
   chat id are configured);
3. record the delivery result in ``deliveries.jsonl`` (always).

Step 1 and 3 are what make the drill provable on a machine without a Telegram
token, which is exactly the risk the workplan calls out.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("NOTIFY_DATA_DIR", "/data"))
LOCK = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _log(message: str, *, severity: str = "INFO", **fields: Any) -> None:
    payload = {
        "timestamp": _now(),
        "severity": severity,
        "service": "notify",
        "message": message,
    }
    payload.update(fields)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def _append(name: str, payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
    with LOCK:
        with (DATA_DIR / name).open("a", encoding="utf-8") as handle:
            handle.write(line)


STATUS_ID = {"firing": "AKTIF", "resolved": "SELESAI"}
SEVERITY_ID = {"critical": "kritis", "warning": "peringatan"}


def format_message(alert: dict[str, Any], group_status: str) -> str:
    """Render one alert for Telegram.

    The message answers five questions in order: what is wrong, how bad, who
    owns it, what it impacts, and what to do first. The rule name stays as a
    traceability line at the bottom.
    """
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    raw_status = str(alert.get("status") or group_status or "firing").lower()
    status = STATUS_ID.get(raw_status, raw_status.upper())
    raw_severity = str(labels.get("severity") or "").lower()
    severity = SEVERITY_ID.get(raw_severity, raw_severity or "-")
    name = labels.get("alertname", "unknown")
    run_id = labels.get("run_id") or annotations.get("run_id") or "n/a (alert service)"
    runbook = annotations.get("runbook_url") or annotations.get("runbook") or "-"
    summary = annotations.get("summary") or name
    detail = annotations.get("description")
    impact = annotations.get("impact")
    first_step = annotations.get("first_step")

    lines = [
        f"[{status}] {summary} ({severity})",
        (
            f"kelas: {labels.get('alert_class', '-')} | "
            f"pemilik: {labels.get('owner', '-')} | run_id: {run_id}"
        ),
    ]
    if detail:
        lines.append(f"Detail: {detail}")
    if impact:
        lines.append(f"Dampak: {impact}")
    if first_step:
        lines.append(f"Langkah pertama: {first_step}")
    lines.append(f"Kode: {name}")
    lines.append(f"runbook: {runbook}")
    return "\n".join(lines)


def send_telegram(text: str) -> dict[str, Any]:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return {"ok": False, "skipped": True, "detail": "telegram not configured"}
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return {"ok": 200 <= response.status < 300, "status": response.status}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "detail": str(exc)}


def handle_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(payload.get("status") or "firing")
    _append(
        "alerts.jsonl",
        {"received_at": _now(), "status": status, "payload": payload},
    )
    alerts = payload.get("alerts") or []
    _log("alert payload received", status=status, alerts=len(alerts))
    results: list[dict[str, Any]] = []
    for alert in alerts:
        text = format_message(alert, status)
        result = send_telegram(text)
        record = {
            "received_at": _now(),
            "alert": (alert.get("labels") or {}).get("alertname"),
            "status": alert.get("status") or status,
            "run_id": (alert.get("labels") or {}).get("run_id"),
            "message": text,
            "telegram": result,
        }
        _append("deliveries.jsonl", record)
        _log(
            "alert delivered",
            severity="INFO" if result.get("ok") else "WARNING",
            alert=record["alert"],
            status=record["status"],
            run_id=record["run_id"],
            telegram_ok=bool(result.get("ok")),
            telegram_skipped=bool(result.get("skipped")),
        )
        results.append(record)
    return results


class Handler(BaseHTTPRequestHandler):
    server_version = "bmip-notify/0.1"

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/healthz":
            self._json(
                200,
                {
                    "status": "ok",
                    "telegram_configured": bool(
                        (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
                        and (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
                    ),
                },
            )
            return
        if self.path in ("/events", "/alerts"):
            path = DATA_DIR / "alerts.jsonl"
            rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            self._json(200, [json.loads(row) for row in rows if row.strip()])
            return
        if self.path == "/deliveries":
            path = DATA_DIR / "deliveries.jsonl"
            rows = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            self._json(200, [json.loads(row) for row in rows if row.strip()])
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/alert":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        results = handle_payload(payload)
        self._json(200, {"accepted": len(results)})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main() -> None:
    port = int(os.getenv("NOTIFY_PORT", "8080"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    _log("notify started", port=port, data=str(DATA_DIR))
    server.serve_forever()


if __name__ == "__main__":
    main()
