#!/usr/bin/env python3
"""Verify Prefect deployments, schedules, concurrency, and recent runs."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from prefect.client.orchestration import get_client

ROOT = Path(__file__).resolve().parents[1]
OWNER = "lois"
EXPECTED = {
    "harvest-social": "10 * * * *",
    "transform-silver": "40 * * * *",
}


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def server_health(api_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{api_url.rstrip('/')}/health", timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


async def collect(pool_name: str) -> dict[str, Any]:
    async with get_client() as client:
        pool = await client.read_work_pool(pool_name)
        deployments = await client.read_deployments()
        runs = await client.read_flow_runs(limit=50)

        deployment_rows = []
        for deployment in deployments:
            if deployment.name not in EXPECTED:
                continue
            schedules = await client.read_deployment_schedules(deployment.id)
            deployment_runs = [run for run in runs if run.deployment_id == deployment.id]
            completed = [
                run
                for run in deployment_runs
                if str(run.state_type).endswith("COMPLETED")
            ]
            deployment_rows.append(
                {
                    "name": deployment.name,
                    "id": str(deployment.id),
                    "entrypoint": deployment.entrypoint,
                    "work_pool": deployment.work_pool_name,
                    "work_queue": deployment.work_queue_name,
                    "global_concurrency_limit": (
                        deployment.global_concurrency_limit.limit
                        if deployment.global_concurrency_limit
                        else None
                    ),
                    "schedules": [
                        {
                            "cron": schedule.schedule.cron,
                            "timezone": schedule.schedule.timezone,
                            "active": schedule.active,
                        }
                        for schedule in schedules
                    ],
                    "completed_runs": len(completed),
                    "latest_completed": str(completed[0].id) if completed else None,
                }
            )

        return {
            "work_pool": {
                "name": pool.name,
                "type": pool.type,
                "concurrency_limit": pool.concurrency_limit,
                "status": str(pool.status),
            },
            "deployments": sorted(deployment_rows, key=lambda row: row["name"]),
        }


def evaluate(data: dict[str, Any], health: bool) -> bool:
    if not health:
        return False
    if data["work_pool"]["concurrency_limit"] != 1:
        return False
    deployments = {row["name"]: row for row in data["deployments"]}
    if set(deployments) != set(EXPECTED):
        return False
    for name, cron in EXPECTED.items():
        row = deployments[name]
        schedules = row["schedules"]
        if not any(
            schedule["cron"] == cron and schedule["active"] for schedule in schedules
        ):
            return False
        if row["global_concurrency_limit"] != 1:
            return False
        if row["completed_runs"] < 1:
            return False
    return True


def main() -> int:
    load_dotenv(ROOT / ".env")
    api_url = os.getenv("PREFECT_API_URL", "http://localhost:4200/api")
    os.environ.setdefault("PREFECT_API_URL", api_url)
    pool_name = os.getenv("PREFECT_WORK_POOL", "local-process")

    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%S")
    health = server_health(api_url)
    data = asyncio.run(collect(pool_name))
    passed = evaluate(data, health)
    payload = {
        "id": "PREFECT-W1B",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "commit": commit_sha(),
        "owner": OWNER,
        "command": "python scripts/prefect_evidence.py",
        "result": "PASS" if passed else "FAIL",
        "api_url": api_url,
        "health": health,
        **data,
    }
    target = ROOT / "evidence" / "deploy" / f"prefect_{stamp}_{payload['commit']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
