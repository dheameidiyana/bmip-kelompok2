#!/usr/bin/env python3
"""Generate W1-B CP1 evidence: consumer lag and restart without data loss."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmip.common.config import get_settings
from bmip.ingestion.feeds import iter_static_market
from bmip.ingestion.kafka import publish_market_trades

ROOT = Path(__file__).resolve().parents[1]
OWNER = "lois"
FIXTURE = ROOT / "tests" / "fixtures" / "binance_agg_trades.jsonl"
STARTUP_DELAY = 4.0


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def parse_result(text: str, key: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    index = 0
    while True:
        index = text.find("{", index)
        if index < 0:
            return None
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(payload, dict) and key in payload:
            return payload
        index += end


def stream_command(
    group: str,
    topic: str,
    *,
    max_records: int | None = None,
    metrics_port: int | None = None,
    startup_delay: float = 0.0,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "bmip.transform.cli",
        "stream",
        "--once",
        "--group",
        group,
        "--topic",
        topic,
        "--idle-timeout",
        "5",
        "--no-sink",
    ]
    if max_records is not None:
        command.extend(["--max-records", str(max_records)])
    if metrics_port is not None:
        command.extend(["--metrics-port", str(metrics_port), "--startup-delay", str(startup_delay)])
    else:
        command.append("--no-metrics")
    return command


def run_stream(command: list[str], timeout: float = 90.0) -> dict[str, Any]:
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        timeout=timeout,
        check=False,
    )
    output = process.stdout + process.stderr
    return {
        "command": " ".join(["python", *command[1:]]),
        "exit_code": process.returncode,
        "result": (parse_result(output, "stream") or {}).get("stream", {}),
        "output": output,
    }


def metric_value(text: str, name: str) -> float | None:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            try:
                return float(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def wait_for_lag(url: str, timeout: float = 30.0) -> str | None:
    deadline = time.monotonic() + timeout
    last_text = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/metrics", timeout=2) as response:
                text = response.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.2)
            continue
        last_text = text
        lag = metric_value(text, "bmip_consumer_lag")
        if lag is not None and lag > 0:
            return text
        time.sleep(0.2)
    return last_text


def start_metric_run(group: str, topic: str, port: int) -> tuple[dict[str, Any], str | None]:
    command = stream_command(
        group,
        topic,
        max_records=1,
        metrics_port=port,
        startup_delay=STARTUP_DELAY,
    )
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
    )
    metrics_text = wait_for_lag(f"http://127.0.0.1:{port}")
    try:
        output, _ = process.communicate(timeout=90)
    except subprocess.TimeoutExpired:
        process.terminate()
        output, _ = process.communicate(timeout=10)
    result = (parse_result(output or "", "stream") or {}).get("stream", {})
    return {
        "command": " ".join(["python", *command[1:]]),
        "exit_code": process.returncode,
        "result": result,
        "output": output or "",
    }, metrics_text


def header(evidence_id: str, iso: str, commit: str, command: str, result: str) -> list[str]:
    return [
        f"id        : {evidence_id}",
        f"timestamp : {iso}",
        f"commit    : {commit}",
        f"command   : {command}",
        f"result    : {result}",
        f"owner     : {OWNER}",
        "",
    ]


def main() -> int:
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M")
    iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    commit = commit_sha()
    settings = get_settings()
    stamp = now.strftime("%Y%m%d%H%M%S")
    topic = f"market.cp1-{stamp}"
    group = f"cp1-{stamp}"

    records = list(iter_static_market(FIXTURE))
    published = publish_market_trades(settings.redpanda_brokers, topic, records)
    if published != len(records):
        raise RuntimeError(f"published {published} of {len(records)} records")

    lag_text: str | None = None
    runs: list[dict[str, Any]] = []
    metric_port = free_port()
    metric_run, lag_text = start_metric_run(group, topic, metric_port)
    runs.append(metric_run)

    runs.append(run_stream(stream_command(group, topic, max_records=1)))
    runs.append(run_stream(stream_command(group, topic)))
    runs.append(run_stream(stream_command(group, topic)))

    total_processed = sum(int(run["result"].get("processed", 0)) for run in runs)
    final_processed = int(runs[-1]["result"].get("processed", 0))
    initial_lag = metric_value(lag_text or "", "bmip_consumer_lag") or 0
    passed = (
        published == len(records)
        and initial_lag > 0
        and total_processed == len(records)
        and final_processed == 0
        and all(run["exit_code"] == 0 for run in runs)
    )
    result = "PASS" if passed else "FAIL"

    stream_dir = ROOT / "evidence" / "stream"
    stream_dir.mkdir(parents=True, exist_ok=True)
    lag_path = stream_dir / f"lag_{timestamp}.txt"
    restart_path = stream_dir / f"restart_{timestamp}.txt"

    lag_lines = header(
        "CP1-LAG",
        iso,
        commit,
        f"python scripts/stream_evidence_cp1.py ({timestamp})",
        result,
    )
    lag_lines.extend(
        [
            f"topic        : {topic}",
            f"group        : {group}",
            f"published    : {published}",
            f"initial_lag  : {initial_lag:g}",
            "",
            "=== /metrics ===",
            (lag_text or "metrics unavailable").rstrip(),
            "",
            f"$ {metric_run['command']}",
            f"exit_code: {metric_run['exit_code']}",
            metric_run["output"].rstrip(),
        ]
    )
    lag_path.write_text("\n".join(lag_lines) + "\n", encoding="utf-8")

    restart_lines = header(
        "CP1-RESTART",
        iso,
        commit,
        f"python scripts/stream_evidence_cp1.py ({timestamp})",
        result,
    )
    restart_lines.extend(
        [
            f"topic              : {topic}",
            f"group              : {group}",
            f"published          : {published}",
            f"total_processed    : {total_processed}",
            f"final_run_processed: {final_processed}",
            "",
            "=== runs ===",
        ]
    )
    for index, run in enumerate(runs, start=1):
        restart_lines.extend(
            [
                f"--- run {index} ---",
                f"$ {run['command']}",
                f"exit_code: {run['exit_code']}",
                f"result   : {json.dumps(run['result'], sort_keys=True)}",
                "",
            ]
        )
    restart_path.write_text("\n".join(restart_lines) + "\n", encoding="utf-8")

    payload = {
        "id": "CP1",
        "timestamp": iso,
        "commit": commit,
        "command": "python scripts/stream_evidence_cp1.py",
        "result": result,
        "owner": OWNER,
        "topic": topic,
        "group": group,
        "published": published,
        "initial_lag": initial_lag,
        "total_processed": total_processed,
        "final_run_processed": final_processed,
        "runs": [
            {
                "command": run["command"],
                "exit_code": run["exit_code"],
                "processed": run["result"].get("processed"),
                "lag": run["result"].get("lag"),
            }
            for run in runs
        ],
        "evidence": [
            str(lag_path.relative_to(ROOT)).replace("\\", "/"),
            str(restart_path.relative_to(ROOT)).replace("\\", "/"),
        ],
    }
    json_path = stream_dir / f"CP1_{timestamp}.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    json_relative = str(json_path.relative_to(ROOT)).replace("\\", "/")
    output = {**payload, "evidence": [*payload["evidence"], json_relative]}
    print(json.dumps(output, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
