#!/usr/bin/env python3
"""Write Loki/Promtail evidence for C3-C CP1.

The stream processor runs on the host in normal operation, so this script
writes its JSON log to ``logs/stream-processor.jsonl`` (the path Promtail
tails) instead of pretending that every BMIP job is a container. Docker
container logs are shipped by the same Promtail through the Docker socket.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOKI = "http://127.0.0.1:3100"
LOGS = ROOT / "logs"
EVIDENCE = ROOT / "evidence" / "logs"
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    str(ROOT / ".env"),
    "-f",
    str(ROOT / "deploy" / "compose.base.yml"),
    "-f",
    str(ROOT / "deploy" / "compose.dev.yml"),
    "--profile",
    "n1",
    "--profile",
    "n2",
    "--profile",
    "n3",
    "--profile",
    "n4",
    "--profile",
    "loki",
    "--profile",
    "promtail",
]


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def _run(command: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False
    )


def _start() -> str:
    LOGS.mkdir(parents=True, exist_ok=True)
    result = _run([*COMPOSE, "up", "-d", "loki", "promtail"])
    if result.returncode != 0:
        return (result.stderr or result.stdout or "loki start failed")[:800]
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            response = httpx.get(f"{LOKI}/ready", timeout=3)
            if response.status_code == 200:
                return ""
        except httpx.HTTPError:
            pass
        time.sleep(2)
    return "loki did not become ready within 90s"


def _stream_log() -> dict[str, Any]:
    run_id = f"c3c-loki-{int(time.time())}"
    target = LOGS / "stream-processor.jsonl"
    target.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment["BMIP_LOG_FILE"] = str(target)
    environment["BMIP_RUN_ID"] = run_id
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bmip.transform.cli",
            "stream",
            "--once",
            "--group",
            "c3c-loki-evidence",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=environment,
        check=False,
    )
    lines = 0
    if target.exists():
        lines = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
    return {
        "run_id": run_id,
        "returncode": result.returncode,
        "log_file": str(target.relative_to(ROOT)),
        "log_lines": lines,
        "stderr_tail": (result.stderr or "")[-400:],
        "stdout_tail": (result.stdout or "")[-400:],
    }


def _query(query: str) -> dict[str, Any]:
    end = datetime.now(UTC)
    start = end - timedelta(minutes=15)
    last = "not tried"
    for _ in range(12):
        try:
            response = httpx.get(
                f"{LOKI}/loki/api/v1/query_range",
                params={
                    "query": query,
                    "start": int(start.timestamp() * 1e9),
                    "end": int(end.timestamp() * 1e9),
                    "limit": 100,
                },
                timeout=10,
            )
            if response.status_code == 200:
                payload = response.json()
                streams = (payload.get("data") or {}).get("result") or []
                lines = [
                    {"labels": stream.get("stream"), "line": value[1]}
                    for stream in streams
                    for value in (stream.get("values") or [])
                ]
                if lines:
                    return {"result": "PASS", "lines": lines, "raw": payload}
                last = "query returned no lines"
            else:
                last = f"HTTP {response.status_code}: {response.text[:200]}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(5)
    return {"result": "FAIL", "error": last, "lines": []}


def _labels() -> list[str]:
    try:
        response = httpx.get(f"{LOKI}/loki/api/v1/labels", timeout=10)
        if response.status_code == 200:
            return sorted(response.json().get("data") or [])
    except httpx.HTTPError:
        pass
    return []


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    start_error = _start()
    stream = _stream_log()
    query = '{service="stream-processor"} |= "run_id"'
    result = _query(query)
    labels = _labels()
    passed = not start_error and result["result"] == "PASS"

    stamp = _stamp()
    document = {
        "id": "CP1-loki-promtail",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_loki.py",
        "result": "PASS" if passed else "FAIL",
        "owner": "vio",
        "start_error": start_error,
        "query": query,
        "labels": labels,
        "stream": stream,
        "line_count": len(result.get("lines") or []),
        "sample_lines": (result.get("lines") or [])[:5],
        "query_error": result.get("error"),
    }
    target = EVIDENCE / f"loki_{stamp}.json"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    text = EVIDENCE / f"loki_{stamp}.txt"
    text.write_text(
        "\n".join(
            [
                "id        : CP1-loki-promtail",
                f"timestamp : {document['timestamp']}",
                f"commit    : {document['commit']}",
                "command   : python scripts/c3c_loki.py",
                f"result    : {document['result']}",
                "owner     : vio",
                "",
                f"query        : {query}",
                f"labels       : {labels}",
                f"line_count   : {document['line_count']}",
                f"stream       : {json.dumps(stream, ensure_ascii=True)}",
                f"start_error  : {start_error or '-'}",
                f"query_error  : {document.get('query_error') or '-'}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": document["result"],
                "query": query,
                "labels": labels,
                "line_count": document["line_count"],
                "evidence": str(target.relative_to(ROOT)),
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
