#!/usr/bin/env python3
"""Check the health of the BMIP dev stack and write CP1 evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "deploy/compose.base.yml",
    "-f",
    "deploy/compose.dev.yml",
]
EXPECTED_SERVICES = [
    "traefik",
    "redpanda",
    "postgres-core",
    "minio",
    "lakekeeper",
    "api",
]
EXPECTED_BUCKETS = {"lakehouse", "artifacts", "backups", "docs", "quarantine"}
EXPECTED_NAMESPACES = {"bronze", "silver", "gold"}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


def _http(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(200).decode("utf-8", errors="replace").strip()
            return 200 <= response.status < 400, f"HTTP {response.status} {body[:80]}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def _ps() -> tuple[dict[str, dict], str | None]:
    try:
        result = subprocess.run(
            [*COMPOSE, "ps", "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, str(exc)

    if result.returncode != 0:
        return {}, result.stderr.strip() or "docker compose ps failed"

    text = result.stdout.strip()
    if not text:
        return {}, None

    try:
        parsed = json.loads(text)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]

    return {row.get("Service", ""): row for row in rows}, None


def _service_checks() -> tuple[list[Check], dict[str, dict], str | None]:
    rows, error = _ps()
    checks: list[Check] = []
    for name in EXPECTED_SERVICES:
        row = rows.get(name)
        if row is None:
            checks.append(Check(f"service/{name}", False, "not created"))
            continue
        state = row.get("State", "unknown")
        health = row.get("Health") or "-"
        passed = state == "running" and health in ("healthy", "-")
        checks.append(Check(f"service/{name}", passed, f"state={state} health={health}"))
    return checks, rows, error


def _http_checks() -> list[Check]:
    targets = [
        ("http/traefik-ping", "http://localhost:8082/ping"),
        ("http/traefik-api", "http://localhost:8080/api"),
        ("http/minio-live", "http://localhost:9000/minio/health/live"),
        ("http/lakekeeper", "http://localhost:8181/health"),
        ("http/api-ready", "http://localhost:8000/health/ready"),
    ]
    checks: list[Check] = []
    for name, url in targets:
        passed, detail = _http(url)
        checks.append(Check(name, passed, detail))
    return checks


def _s3_check() -> list[Check]:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        return [Check("s3/buckets", False, f"boto3 missing: {exc}")]

    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD"),
        region_name=os.getenv("MINIO_S3_REGION", "local"),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    try:
        found = {bucket["Name"] for bucket in client.list_buckets().get("Buckets", [])}
    except Exception as exc:  # noqa: BLE001 - report any client failure as a check
        return [Check("s3/buckets", False, str(exc))]

    missing = EXPECTED_BUCKETS - found
    return [
        Check(
            "s3/buckets",
            not missing,
            f"found={sorted(found)} missing={sorted(missing)}",
        )
    ]


def _lakekeeper_check() -> list[Check]:
    base = os.getenv("LAKEKEEPER_URL", "http://localhost:8181").rstrip("/")
    warehouse = os.getenv("LAKEKEEPER_WAREHOUSE", "lakehouse")
    try:
        with urllib.request.urlopen(f"{base}/management/v1/warehouse", timeout=5) as response:
            warehouses = json.loads(response.read().decode("utf-8")).get("warehouses", [])
        warehouse_id = next(
            (item["id"] for item in warehouses if item.get("name") == warehouse), None
        )
        if warehouse_id is None:
            return [Check("lakekeeper/namespaces", False, f"warehouse {warehouse} missing")]
        with urllib.request.urlopen(
            f"{base}/catalog/v1/{warehouse_id}/namespaces", timeout=5
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [Check("lakekeeper/namespaces", False, str(exc))]

    found = {item[0] for item in payload.get("namespaces", []) if item}
    missing = EXPECTED_NAMESPACES - found
    return [
        Check(
            "lakekeeper/namespaces",
            not missing,
            f"found={sorted(found)} missing={sorted(missing)}",
        )
    ]


def _postgres_check() -> list[Check]:
    user = os.getenv("POSTGRES_USER", "bmip")
    database = os.getenv("POSTGRES_DB", "bmip")
    lakekeeper_db = os.getenv("LAKEKEEPER_DB_NAME", "lakekeeper")
    sql = (
        "select to_regclass('ops.batch_runs') is not null "
        "and to_regclass('ops.social_watermark') is not null"
    )
    try:
        result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres-core",
                "psql",
                "-U",
                user,
                "-d",
                database,
                "-tAc",
                sql,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "t":
            return [
                Check(
                    "postgres/ops-tables",
                    False,
                    result.stderr.strip() or f"stdout={result.stdout.strip()}",
                )
            ]

        db_result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres-core",
                "psql",
                "-U",
                user,
                "-d",
                database,
                "-tAc",
                f"select 1 from pg_database where datname = '{lakekeeper_db}'",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Check("postgres/ops-tables", False, str(exc))]

    checks = [Check("postgres/ops-tables", True, "ops.batch_runs + ops.social_watermark")]
    checks.append(
        Check(
            "postgres/lakekeeper-db",
            db_result.stdout.strip() == "1",
            f"database={lakekeeper_db}",
        )
    )
    return checks


def collect(services_only: bool) -> list[Check]:
    checks, _rows, error = _service_checks()
    if error:
        checks.append(Check("compose/ps", False, error))
    else:
        checks.append(Check("compose/ps", True, "docker compose ps ok"))

    checks.extend(_http_checks())
    if not services_only:
        checks.extend(_s3_check())
        checks.extend(_lakekeeper_check())
        checks.extend(_postgres_check())
    return checks


def print_table(checks: list[Check]) -> None:
    width = max(len(check.name) for check in checks)
    print(f"{'CHECK'.ljust(width)}  STATUS  DETAIL")
    print(f"{'-' * width}  ------  ------")
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"{check.name.ljust(width)}  {status}    {check.detail}")


def write_evidence(checks: list[Check]) -> Path:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip() or "nogit"
    except (OSError, subprocess.TimeoutExpired):
        sha = "nogit"

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M")
    target = ROOT / "evidence" / "deploy" / f"health_{stamp}_{sha}.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# CP1 health - {stamp} UTC",
        "",
        f"- commit: `{sha}`",
        f"- env: `{os.getenv('BMIP_ENV', 'dev')}`",
        f"- result: `{'PASS' if all(c.passed for c in checks) else 'FAIL'}`",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| `{check.name}` | {'PASS' if check.passed else 'FAIL'} | {check.detail} |"
        )
    lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return target


def wait_for_services(timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        checks = collect(services_only=True)
        if all(check.passed for check in checks):
            return True
        time.sleep(5)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services-only", action="store_true")
    parser.add_argument("--wait", action="store_true", help="poll until services are healthy")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--evidence", action="store_true", help="write evidence/deploy/health_*.md")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.wait:
        if not wait_for_services(args.timeout):
            print(f"services did not become healthy within {args.timeout}s", file=sys.stderr)
            print_table(collect(services_only=args.services_only))
            return 1

    checks = collect(services_only=args.services_only)
    print_table(checks)

    if args.evidence:
        path = write_evidence(checks)
        print(f"\nevidence: {path.relative_to(ROOT)}")

    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
