#!/usr/bin/env python3
"""Validate and exercise the C3-C node profiles.

Static mode writes the 3-node and 4-node `docker compose config` artefacts and
checks the placement table in `deploy/traefik/services.yaml`. ``--live`` starts
N1+N2 on one host and records HTTP health. That live check proves the role
split and cross-node env wiring; it is not a two-laptop network test, and the
handoff says so explicitly.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "deploy"
load_dotenv(ROOT / ".env")

NODE_FILES = [ROOT / "deploy" / f"compose.node{n}.yml" for n in (1, 2, 3, 4)]
BASE = ROOT / "deploy" / "compose.base.yml"
ENV_FILES = [ROOT / ".env", ROOT / "deploy" / "env" / "node1.env"]
ALL_PROFILES = [
    "--profile",
    "n1",
    "--profile",
    "n2",
    "--profile",
    "n3",
    "--profile",
    "n4",
    "--profile",
    "governance",
    "--profile",
    "docs",
    "--profile",
    "loki",
    "--profile",
    "promtail",
]
LOCAL_ENV = {
    "BMIP_BIND_ADDRESS": "127.0.0.1",
    "BMIP_EDGE_BIND_ADDRESS": "127.0.0.1",
    "BMIP_N1_HOST": "127.0.0.1",
    "BMIP_N2_HOST": "127.0.0.1",
    "BMIP_N3_HOST": "127.0.0.1",
    "BMIP_N4_HOST": "127.0.0.1",
    "BMIP_API_2_HOST_PORT": "8001",
    "BMIP_PG_CORE_PORT": "5433",
    "BMIP_PG_ML_PORT": "5434",
}


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def _compose(
    files: list[Path], profiles: list[str], *, env: dict[str, str] | None = None
) -> list[str]:
    command = ["docker", "compose", "--env-file", str(ROOT / ".env")]
    for env_file in ENV_FILES[1:]:
        command += ["--env-file", str(env_file)]
    for path in [BASE, *files]:
        command += ["-f", str(path)]
    command += profiles
    return command


def _run(
    command: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update(LOCAL_ENV)
    if extra_env:
        environment.update(extra_env)
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=capture,
        text=True,
        env=environment,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(command)} failed ({result.returncode}): "
            f"{(result.stderr or result.stdout or '')[:800]}"
        )
    return result


def _check_placement() -> list[str]:
    payload = yaml.safe_load(
        (ROOT / "deploy" / "traefik" / "services.yaml").read_text(encoding="utf-8")
    )
    problems: list[str] = []
    nodes = payload.get("nodes") or {}
    for name, node in (payload.get("services") or {}).items():
        if node.get("node") not in nodes:
            problems.append(f"{name}: unknown node {node.get('node')!r}")
    for expected in (
        "api",
        "api-2",
        "dashboard",
        "catalog",
        "docs",
        "prometheus",
        "grafana",
        "loki",
    ):
        if expected not in (payload.get("services") or {}):
            problems.append(f"missing service placement: {expected}")
    for number, path in enumerate(NODE_FILES, start=1):
        if not path.is_file():
            problems.append(f"missing {path.relative_to(ROOT)}")
        text = path.read_text(encoding="utf-8")
        if "services:" not in text:
            problems.append(f"node{number}: no services block")
    return problems


def static() -> dict[str, Any]:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    problems = _check_placement()
    configs: dict[str, str] = {}

    node_profiles = {
        "node1": ["--profile", "n1", "--profile", "promtail"],
        "node2": ["--profile", "n2", "--profile", "promtail"],
        "node3": [
            "--profile",
            "n3",
            "--profile",
            "governance",
            "--profile",
            "docs",
            "--profile",
            "promtail",
        ],
        "node4": ["--profile", "n4", "--profile", "loki", "--profile", "promtail"],
    }
    for index, name in enumerate(("node1", "node2", "node3", "node4"), start=1):
        env_files = [ROOT / ".env", ROOT / "deploy" / "env" / f"{name}.env"]
        command = ["docker", "compose"]
        for env_file in env_files:
            command += ["--env-file", str(env_file)]
        command += ["-f", str(BASE), "-f", str(NODE_FILES[index - 1])]
        command += node_profiles[name]
        quiet = subprocess.run(
            [*command, "config", "--quiet"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, **LOCAL_ENV},
        )
        if quiet.returncode != 0:
            problems.append(f"{name} config failed: {(quiet.stderr or quiet.stdout)[:500]}")

    for name, files, profiles in (
        ("3node", NODE_FILES[:3], [*ALL_PROFILES]),
        ("4node", NODE_FILES, [*ALL_PROFILES]),
    ):
        command = _compose(files, profiles)
        result = _run([*command, "config", "--no-interpolate"], check=False)
        if result.returncode != 0:
            problems.append(f"{name} config failed: {(result.stderr or result.stdout)[:800]}")
        else:
            target = EVIDENCE / f"compose-{name}.yml"
            target.write_text(result.stdout, encoding="utf-8")
            configs[name] = str(target.relative_to(ROOT))

    stamp = _stamp()
    document = {
        "id": "CP1-node-profiles",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_nodes.py",
        "result": "PASS" if not problems else "FAIL",
        "owner": "vio",
        "configs": configs,
        "problems": problems,
    }
    output = EVIDENCE / f"nodes_{stamp}.json"
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))
    return document


def _wait(url: str, timeout: float = 240.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    last = "not tried"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code < 500:
                return {"url": url, "status": response.status_code, "ok": True}
            last = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(3)
    return {"url": url, "status": 0, "ok": False, "error": last}


def live(keep: bool) -> dict[str, Any]:
    command = _compose(
        [NODE_FILES[0], NODE_FILES[1]],
        ["--profile", "n1", "--profile", "n2", "--profile", "bootstrap"],
    )
    started: list[dict[str, Any]] = []
    running: list[str] = []
    error: str | None = None
    try:
        _run([*command, "up", "-d"])
        ps = _run([*command, "ps", "--services", "--status", "running"], check=False)
        running = [line.strip() for line in (ps.stdout or "").splitlines() if line.strip()]
        started.append(_wait("http://127.0.0.1:9000/minio/health/live", timeout=60))
        started.append(_wait("http://127.0.0.1:8181/health", timeout=60))
        started.append(_wait("http://127.0.0.1:8001/health/live"))
        started.append(_wait("http://127.0.0.1:4200/api/health"))
    except Exception as exc:  # noqa: BLE001 - recorded as evidence
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if not keep:
            _run([*command, "down", "--remove-orphans"], check=False)

    stamp = _stamp()
    required = {
        "n1": {"postgres-core", "minio", "lakekeeper", "redpanda", "api"},
        "n2": {"api-2", "prefect-server", "postgres-ml"},
    }
    missing = {
        node: sorted(services - set(running)) for node, services in required.items()
    }
    n2_http = all(
        check.get("ok") for check in started if ":8001/" in check["url"] or ":4200/" in check["url"]
    )
    passed = not error and n2_http and not any(missing.values())
    document = {
        "id": "CP1-two-node-live",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_nodes.py --live",
        "result": "PASS" if passed else "FAIL",
        "owner": "vio",
        "scope": "N1+N2 on one host; not a two-laptop tailnet test",
        "running_services": running,
        "missing_services": missing,
        "checks": started,
        "error": error,
        "kept_running": keep,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    output = EVIDENCE / f"two-node-live_{stamp}.json"
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="start N1+N2 and check health")
    parser.add_argument("--keep", action="store_true", help="keep the live stack running")
    args = parser.parse_args(argv)
    document = static()
    if args.live:
        live_document = live(args.keep)
        if live_document["result"] != "PASS":
            return 1
    return 0 if document["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
