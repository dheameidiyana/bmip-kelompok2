#!/usr/bin/env python3
"""Run the T-40 restart persistence check and write recovery evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from w2d_backup import ROOT, container_for, table_stats, targets

OWNER = "lois"
COMPOSE_FILES = (
    "deploy/compose.base.yml",
    "deploy/compose.dev.yml",
    "deploy/compose.host-ml.yml",
)
COMPOSE_PROFILE = "governance"
REDPANDA_CONTAINER = "bmip-redpanda-1"
REDPANDA_BROKERS = "redpanda:9092"

CRITICAL_TABLES = {
    "ops.api_keys",
    "ops.audit_log",
    "ops.backfill_requests",
    "ops.batch_runs",
    "ops.dataset_registry",
    "ops.lineage_edges",
    "ops.social_watermark",
    "serving.catalog_datasets",
    "serving.dq_results",
    "serving.dq_runs",
    "serving.freshness",
    "serving.market_hourly",
    "serving.market_latest",
    "serving.model_decisions",
    "serving.model_metrics",
    "serving.predictions",
    "serving.sentiment_hourly",
}

HTTP_CHECKS = (
    ("api", "http://127.0.0.1:8000/health/ready"),
    ("mlflow", "http://127.0.0.1:5000/health"),
    ("dashboard", "http://127.0.0.1:8501/_stcore/health"),
    ("catalog", "http://127.0.0.1:8502/_stcore/health"),
    ("prometheus", "http://127.0.0.1:9090/-/ready"),
    ("grafana", "http://127.0.0.1:3000/api/health"),
    ("minio", "http://127.0.0.1:9000/minio/health/live"),
    ("prefect", "http://127.0.0.1:4200/api/health"),
    ("alertmanager", "http://127.0.0.1:9093/-/healthy"),
    ("pushgateway", "http://127.0.0.1:9091/-/healthy"),
)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_value(*args: str) -> str:
    process = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    return process.stdout.strip() if process.returncode == 0 else ""


def compose_command(*args: str) -> list[str]:
    command = ["docker", "compose", "--env-file", ".env"]
    for path in COMPOSE_FILES:
        command.extend(["-f", path])
    command.extend(["--profile", COMPOSE_PROFILE])
    command.extend(args)
    return command


def compose(*args: str, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        compose_command(*args),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )


def docker_exec(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "exec", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=timeout,
    )


def running_services() -> list[dict[str, Any]]:
    process = compose("ps", "--format", "json")
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout).strip())
    text = process.stdout.strip()
    if not text:
        return []
    if text.startswith("["):
        items = json.loads(text)
    else:
        items = [json.loads(line) for line in text.splitlines() if line.strip()]
    return [item for item in items if item.get("State") == "running"]


def http_check(name: str, url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with OPENER.open(request, timeout=8) as response:
            body = response.read(256).decode("utf-8", errors="replace")
            return {
                "name": name,
                "url": url,
                "status": response.status,
                "ok": 200 <= response.status < 300,
                "body": body.strip(),
            }
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"name": name, "url": url, "status": None, "ok": False, "error": str(exc)}


def health_snapshot() -> dict[str, Any]:
    return {name: http_check(name, url) for name, url in HTTP_CHECKS}


def wait_ready(timeout: float) -> tuple[list[dict[str, Any]], dict[str, Any], float]:
    started = time.monotonic()
    deadline = started + timeout
    last_services: list[dict[str, Any]] = []
    last_health: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_services = running_services()
        unhealthy = [
            item.get("Service")
            for item in last_services
            if item.get("Health") and item.get("Health") != "healthy"
        ]
        last_health = health_snapshot()
        if not unhealthy and all(item["ok"] for item in last_health.values()):
            return last_services, last_health, time.monotonic() - started
        time.sleep(2)
    failed = [item["name"] for item in last_health.values() if not item["ok"]]
    raise TimeoutError(f"stack did not become ready within {timeout:g}s; failed={failed}")


def database_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for target in targets():
        container = container_for(target)
        stats = table_stats(container, target.user, target.database)
        snapshot[target.database] = {
            "service": target.service,
            "container": container,
            "tables": stats,
            "row_total": sum(int(item["rows"]) for item in stats),
        }
    return snapshot


def compare_databases(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    databases: dict[str, Any] = {}
    business_ok = True
    row_totals_not_decreased = True
    all_tables_identical = True
    for database in sorted(before):
        if database not in after:
            databases[database] = {"present_after": False}
            business_ok = False
            row_totals_not_decreased = False
            all_tables_identical = False
            continue
        before_tables = {str(item["table"]): item for item in before[database]["tables"]}
        after_tables = {str(item["table"]): item for item in after[database]["tables"]}
        missing = sorted(set(before_tables) - set(after_tables))
        extra = sorted(set(after_tables) - set(before_tables))
        mismatches = []
        for name in sorted(set(before_tables) & set(after_tables)):
            left = before_tables[name]
            right = after_tables[name]
            if left["rows"] != right["rows"] or left["checksum"] != right["checksum"]:
                mismatches.append(
                    {
                        "table": name,
                        "before_rows": left["rows"],
                        "after_rows": right["rows"],
                        "before_checksum": left["checksum"],
                        "after_checksum": right["checksum"],
                    }
                )
        critical = sorted(CRITICAL_TABLES) if database == "bmip" else []
        critical_mismatches = [item for item in mismatches if item["table"] in set(critical)]
        critical_missing = [name for name in missing if name in set(critical)]
        business_ok = business_ok and not critical_mismatches and not critical_missing
        row_totals_not_decreased = row_totals_not_decreased and int(
            after[database]["row_total"]
        ) >= int(before[database]["row_total"])
        identical = not missing and not extra and not mismatches
        all_tables_identical = all_tables_identical and identical
        databases[database] = {
            "present_after": True,
            "before_rows": before[database]["row_total"],
            "after_rows": after[database]["row_total"],
            "tables_before": len(before_tables),
            "tables_after": len(after_tables),
            "identical": identical,
            "missing": missing,
            "extra": extra,
            "mismatches": mismatches,
            "critical_mismatches": critical_mismatches,
            "critical_missing": critical_missing,
        }
    return {
        "databases": databases,
        "business_tables_identical": business_ok,
        "row_totals_not_decreased": row_totals_not_decreased,
        "all_tables_identical": all_tables_identical,
    }


def kafka_offsets() -> dict[str, Any]:
    process = docker_exec(
        REDPANDA_CONTAINER,
        "rpk",
        "group",
        "describe",
        "-r",
        "*",
        "--format",
        "json",
        "--brokers",
        REDPANDA_BROKERS,
        timeout=60,
    )
    if process.returncode != 0:
        raise RuntimeError((process.stderr or process.stdout).strip())
    groups = json.loads(process.stdout or "[]")
    offsets: dict[str, Any] = {}
    for group in groups:
        partitions = []
        for item in group.get("partitions", []):
            partitions.append(
                {
                    "topic": item.get("topic"),
                    "partition": item.get("partition"),
                    "current_offset": item.get("current_offset"),
                    "log_start_offset": item.get("log_start_offset"),
                    "log_end_offset": item.get("log_end_offset"),
                }
            )
        partitions.sort(key=lambda item: (str(item["topic"]), int(item["partition"])))
        offsets[str(group.get("group_name"))] = {
            "state": group.get("state"),
            "partitions": partitions,
        }
    return offsets


def compare_offsets(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(set(before) - set(after))
    extra = sorted(set(after) - set(before))
    mismatches = []
    for group in sorted(set(before) & set(after)):
        left = before[group]["partitions"]
        right = after[group]["partitions"]
        if left != right:
            mismatches.append({"group": group, "before": left, "after": right})
    return {
        "groups_before": len(before),
        "groups_after": len(after),
        "missing": missing,
        "extra": extra,
        "mismatches": mismatches,
        "identical": bool(before) and not missing and not extra and not mismatches,
    }


def write_text(path: Path, payload: dict[str, Any]) -> None:
    databases = payload["databases"]["comparison"]["databases"]
    lines = [
        "T-40 Restart persistence",
        f"generated_at={payload['timestamp']}",
        f"commit={payload['commit']}",
        f"branch={payload['branch']}",
        f"command={payload['command']}",
        f"result={payload['result']}",
        f"services_restarted={len(payload['restart']['services'])}",
        f"restart_command_seconds={payload['restart']['command_seconds']:.2f}",
        f"ready_seconds={payload['restart']['ready_seconds']:.2f}",
        "",
        "=== databases ===",
    ]
    for name, item in sorted(databases.items()):
        lines.append(
            f"{name} rows_before={item.get('before_rows')} rows_after={item.get('after_rows')} "
            f"tables_identical={'PASS' if item.get('identical') else 'FAIL'}"
        )
        for mismatch in item.get("mismatches", []):
            lines.append(
                f"  mismatch {mismatch['table']} "
                f"rows={mismatch['before_rows']}->{mismatch['after_rows']}"
            )
        for name_missing in item.get("missing", []):
            lines.append(f"  missing_table={name_missing}")
        for name_extra in item.get("extra", []):
            lines.append(f"  extra_table={name_extra}")
    lines.extend(
        [
            "",
            "=== offsets ===",
            f"groups_before={payload['offsets']['comparison']['groups_before']}",
            f"groups_after={payload['offsets']['comparison']['groups_after']}",
            f"identical={'PASS' if payload['offsets']['comparison']['identical'] else 'FAIL'}",
        ]
    )
    for mismatch in payload["offsets"]["comparison"]["mismatches"]:
        lines.append(f"  mismatch_group={mismatch['group']}")
    lines.extend(["", "=== health ==="])
    for name, item in sorted(payload["health"]["after"].items()):
        lines.append(
            f"{name} status={item.get('status')} ok={'PASS' if item.get('ok') else 'FAIL'}"
        )
    lines.append("")
    lines.append(f"RESULT: {payload['result']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence",
        default="evidence/recovery/T40.json",
        help="JSON evidence path",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="seconds to wait for the stack after restart",
    )
    args = parser.parse_args(argv)

    evidence_path = Path(args.evidence)
    if not evidence_path.is_absolute():
        evidence_path = ROOT / evidence_path
    text_path = evidence_path.with_suffix(".txt")

    services_before, health_before, _ = wait_ready(60)
    databases_before = database_snapshot()
    offsets_before = kafka_offsets()

    services = sorted({str(item["Service"]) for item in services_before})
    restart_started_at = iso()
    restart_started = time.monotonic()
    restart = compose("restart", *services, timeout=args.timeout)
    command_seconds = time.monotonic() - restart_started
    if restart.returncode != 0:
        detail = (restart.stderr or restart.stdout).strip()
        raise RuntimeError(f"docker compose restart failed: {detail}")

    services_after, health_after, ready_seconds = wait_ready(args.timeout)
    databases_after = database_snapshot()
    offsets_after = kafka_offsets()

    database_comparison = compare_databases(databases_before, databases_after)
    offset_comparison = compare_offsets(offsets_before, offsets_after)
    health_ok = all(item["ok"] for item in health_after.values())
    services_ok = len(services_after) >= len(services_before)
    passed = (
        health_ok
        and services_ok
        and database_comparison["business_tables_identical"]
        and database_comparison["row_totals_not_decreased"]
        and offset_comparison["identical"]
    )

    payload = {
        "id": "T-40",
        "timestamp": iso(),
        "commit": git_value("rev-parse", "--short", "HEAD"),
        "branch": git_value("rev-parse", "--abbrev-ref", "HEAD"),
        "command": "python scripts/w2d_restart.py",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "compose": {
            "files": list(COMPOSE_FILES),
            "profile": COMPOSE_PROFILE,
            "restart_services": services,
            "return_code": restart.returncode,
        },
        "restart": {
            "started_at": restart_started_at,
            "command_seconds": round(command_seconds, 2),
            "ready_seconds": round(ready_seconds, 2),
            "services": services,
            "services_after": sorted(str(item["Service"]) for item in services_after),
        },
        "health": {"before": health_before, "after": health_after},
        "databases": {
            "before": databases_before,
            "after": databases_after,
            "comparison": database_comparison,
        },
        "offsets": {
            "before": offsets_before,
            "after": offsets_after,
            "comparison": offset_comparison,
        },
        "evidence": [evidence_path.relative_to(ROOT).as_posix()],
    }

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_text(text_path, payload)
    payload["evidence"].append(text_path.relative_to(ROOT).as_posix())
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
