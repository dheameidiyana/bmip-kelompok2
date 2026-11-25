#!/usr/bin/env python3
"""C3-A evidence for replica load balancing, failover, and replica health."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
CA = ROOT / "deploy" / "traefik" / "certs" / "bmip-ca.pem"
TESTS = ROOT / "evidence" / "tests"
DEPLOY = ROOT / "evidence" / "deploy"
BASE = "https://127.0.0.1"
HOST_HEADER = {"Host": "api.bmip.local"}
load_dotenv(ROOT / ".env")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def _header(identity: str, command: str, result: str) -> str:
    return "\n".join(
        [
            f"id        : {identity}",
            f"timestamp : {datetime.now(UTC).isoformat()}",
            f"commit    : {_sha()}",
            f"command   : {command}",
            f"result    : {result}",
            "owner     : anin",
            "",
        ]
    )


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _key() -> str:
    return os.getenv("BMIP_VIEWER_KEY") or os.getenv("BMIP_API_KEY", "")


def _call(client: httpx.Client) -> tuple[int, dict[str, Any]]:
    response = client.get("/v1/meta/instance", headers={"X-API-Key": _key(), **HOST_HEADER})
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "deploy/compose.base.yml",
            "-f",
            "deploy/compose.dev.yml",
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def lb() -> dict[str, Any]:
    lines = [_header("T-16", "python scripts/c3a_evidence.py --steps lb", "PASS")]
    instances: dict[str, int] = {}
    statuses: dict[int, int] = {}
    with httpx.Client(base_url=BASE, verify=str(CA), timeout=20.0) as client:
        for _ in range(30):
            status, body = _call(client)
            statuses[status] = statuses.get(status, 0) + 1
            instance = (body.get("data") or {}).get("instance") or "unknown"
            instances[instance] = instances.get(instance, 0) + 1
    passed = set(instances) >= {"api-1", "api-2"} and all(code == 200 for code in statuses)
    lines.append("statuses: " + json.dumps(statuses, sort_keys=True))
    lines.append("instances: " + json.dumps(instances, sort_keys=True))
    lines.append(f"distinct replicas: {len(instances)}")
    if not passed:
        lines[0] = _header("T-16", "python scripts/c3a_evidence.py --steps lb", "FAIL")
    _write(TESTS, "T16.txt", "\n".join(lines) + "\n")
    return {"step": "lb", "passed": passed, "instances": instances, "statuses": statuses}


def failover() -> dict[str, Any]:
    lines = [_header("T-17", "python scripts/c3a_evidence.py --steps failover", "PASS")]
    stopped = _compose("stop", "api-2")
    lines.append(f"stop api-2 exit={stopped.returncode}")
    statuses: dict[int, int] = {}
    instances: dict[str, int] = {}
    try:
        # Let Traefik health checks remove the stopped replica.
        time.sleep(12)
        with httpx.Client(base_url=BASE, verify=str(CA), timeout=20.0) as client:
            for _ in range(30):
                status, body = _call(client)
                statuses[status] = statuses.get(status, 0) + 1
                instance = (body.get("data") or {}).get("instance") or "unknown"
                instances[instance] = instances.get(instance, 0) + 1
    finally:
        started = _compose("start", "api-2")
        lines.append(f"start api-2 exit={started.returncode}")
    passed = (
        statuses.get(500, 0) == 0
        and statuses.get(502, 0) == 0
        and statuses.get(503, 0) == 0
        and statuses.get(200, 0) > 0
    )
    lines.append("statuses: " + json.dumps(statuses, sort_keys=True))
    lines.append("instances: " + json.dumps(instances, sort_keys=True))
    lines.append("expected: no 5xx while api-2 is down")
    if not passed:
        lines[0] = _header("T-17", "python scripts/c3a_evidence.py --steps failover", "FAIL")
    _write(TESTS, "T17.txt", "\n".join(lines) + "\n")
    return {"step": "failover", "passed": passed, "instances": instances, "statuses": statuses}


def summary() -> dict[str, Any]:
    lines = [_header("API2-HEALTH", "python scripts/c3a_evidence.py --steps summary", "PASS")]
    health = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            ".env",
            "-f",
            "deploy/compose.base.yml",
            "-f",
            "deploy/compose.dev.yml",
            "ps",
            "api",
            "api-2",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    lines.append(health.stdout.strip())
    ids = _compose("ps", "-q", "api", "api-2").stdout.split()
    inspect = subprocess.run(
        ["docker", "inspect", "--format", "{{.Name}} {{.State.Health.Status}}", *ids],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    lines.append(inspect.stdout.strip())
    passed = bool(ids) and "healthy" in inspect.stdout and inspect.returncode == 0
    if not passed:
        lines[0] = _header("API2-HEALTH", "python scripts/c3a_evidence.py --steps summary", "FAIL")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    _write(DEPLOY, f"api2-health_{stamp}.md", "\n".join(lines) + "\n")
    return {"step": "summary", "passed": passed}


STEPS = {"lb": lb, "failover": failover, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default="lb,failover,summary")
    args = parser.parse_args(argv)
    results = []
    for name in [part.strip() for part in args.steps.split(",") if part.strip()]:
        if name not in STEPS:
            raise SystemExit(f"unknown step: {name}")
        results.append(STEPS[name]())
    print(json.dumps(results, indent=2))
    return 0 if all(item.get("passed") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
