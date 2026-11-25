#!/usr/bin/env python3
"""T-18: latency 2 s -> Traefik circuit open -> 503 -> recovery."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "evidence" / "tests"
TOXI = "http://127.0.0.1:8474"
PROXY = "api-chaos"


def _header(identity: str, command: str, result: str) -> str:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        commit = "nogit"
    return "\n".join(
        [
            f"id        : {identity}",
            f"timestamp : {datetime.now(UTC).isoformat()}",
            f"commit    : {commit}",
            f"command   : {command}",
            f"result    : {result}",
            "owner     : anin",
            "",
        ]
    )


def _wait_toxi() -> bool:
    for _ in range(30):
        try:
            if httpx.get(f"{TOXI}/version", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return False


def main() -> int:
    lines = [_header("T-18", "python scripts/c3a_circuit.py", "PASS")]
    up = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "deploy/compose.base.yml",
            "-f",
            "deploy/compose.dev.yml",
            "-f",
            "deploy/compose.chaos.yml",
            "--profile",
            "chaos",
            "up",
            "-d",
            "toxiproxy",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    lines.append(f"toxiproxy up exit={up.returncode}")
    if not _wait_toxi():
        lines[0] = _header("T-18", "python scripts/c3a_circuit.py", "BLOCKED")
        lines.append("toxiproxy API did not become ready")
        TESTS.mkdir(parents=True, exist_ok=True)
        (TESTS / "T18.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 1

    with httpx.Client(timeout=20.0) as client:
        client.delete(f"{TOXI}/proxies/{PROXY}")
        created = client.post(
            f"{TOXI}/proxies",
            json={
                "name": PROXY,
                "listen": "0.0.0.0:8666",
                "upstream": "api:8000",
                "enabled": True,
            },
        )
        lines.append(f"create proxy: {created.status_code}")
        toxic = client.post(
            f"{TOXI}/proxies/{PROXY}/toxics",
            json={
                "name": "latency",
                "type": "latency",
                "attributes": {"latency": 2000, "jitter": 0},
            },
        )
        lines.append(f"add latency 2000ms: {toxic.status_code}")

    time.sleep(1)
    statuses: dict[int, int] = {}
    with httpx.Client(timeout=10.0) as client:
        for _ in range(30):
            response = client.get("http://127.0.0.1:8084/health/live")
            statuses[response.status_code] = statuses.get(response.status_code, 0) + 1

    with httpx.Client(timeout=10.0) as client:
        client.delete(f"{TOXI}/proxies/{PROXY}/toxics/latency")
    recovered: list[int] = []
    deadline = time.monotonic() + 75
    with httpx.Client(timeout=10.0) as client:
        while time.monotonic() < deadline:
            status = client.get("http://127.0.0.1:8084/health/live").status_code
            recovered.append(status)
            if status == 200:
                break
            time.sleep(5)

    lines.append("during latency: " + json.dumps(statuses, sort_keys=True))
    lines.append("after recovery: " + json.dumps(recovered))
    passed = statuses.get(503, 0) > 0 and 200 in recovered
    if not passed:
        lines[0] = _header("T-18", "python scripts/c3a_circuit.py", "FAIL")
    TESTS.mkdir(parents=True, exist_ok=True)
    (TESTS / "T18.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"statuses": statuses, "recovered": recovered, "passed": passed}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
