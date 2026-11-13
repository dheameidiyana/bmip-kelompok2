#!/usr/bin/env python3
"""W1-A end-to-end smoke gate: health, replay, bronze, ledger, idempotence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from bmip.common.config import get_settings
from bmip.ingestion.bronze import BronzeWriter
from bmip.ingestion.smoke import accepted_statuses, counts_match, ledger_rows_ok

ROOT = Path(__file__).resolve().parents[1]
OWNER = "dhea"
MARKET_FIXTURE = "tests/fixtures/binance_agg_trades.jsonl"
SOCIAL_FIXTURE = "tests/fixtures/bluesky_posts.json"
HTTP_TARGETS = (
    ("traefik/ping", "http://localhost:8082/ping"),
    ("traefik/api", "http://localhost:8080/api"),
    ("api/ready", "http://localhost:8000/health/ready"),
    ("minio/live", "http://localhost:9000/minio/health/live"),
    ("lakekeeper/health", "http://localhost:8181/health"),
)
MINIMUMS = {"bronze.market_trade_raw": 3, "bronze.social_post_raw": 2}


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def extract_result(text: str, key: str) -> dict[str, Any] | None:
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


def http_check(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400, f"HTTP {response.status}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def run_replay(source: str, fixture: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "bmip.ingestion.cli",
        source,
        "--replay",
        fixture,
    ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    output = process.stdout + process.stderr
    payload = extract_result(output, source) or {}
    return {
        "command": " ".join(["python", *command[1:]]),
        "exit_code": process.returncode,
        "output": output,
        "result": payload.get(source, {}),
    }


def bronze_counts() -> dict[str, int]:
    rows = BronzeWriter(get_settings()).counts()
    return {str(row["table"]): int(row["row_count"]) for row in rows}


def ledger_rows(batch_ids: set[str]) -> list[dict[str, Any]]:
    if not batch_ids:
        return []
    query = """
        SELECT batch_id, checksum, row_count, status
        FROM ops.batch_runs
        WHERE batch_id = ANY(%s)
    """
    with psycopg.connect(get_settings().postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query, (list(batch_ids),))
            rows = cursor.fetchall()
    return [
        {
            "batch_id": row[0],
            "checksum": row[1],
            "row_count": row[2],
            "status": row[3],
        }
        for row in rows
    ]


def evaluate() -> tuple[list[tuple[str, bool, str]], list[dict[str, Any]]]:
    checks: list[tuple[str, bool, str]] = []
    outputs: list[dict[str, Any]] = []

    for name, url in HTTP_TARGETS:
        passed, detail = http_check(url)
        checks.append((name, passed, detail))

    # Warm-up: make sure the fixture batches exist before the measured rounds.
    # Without this, the first replay legitimately inserts rows and the
    # before/after comparison can never pass on a clean stack.
    for source, fixture in (("market", MARKET_FIXTURE), ("social", SOCIAL_FIXTURE)):
        warmup = run_replay(source, fixture)
        checks.append(
            (
                f"ingest/{source}/warmup",
                warmup["exit_code"] == 0,
                f"exit={warmup['exit_code']} status={warmup['result'].get('status')}",
            )
        )

    try:
        before = bronze_counts()
    except Exception as exc:
        before = {}
        checks.append(("bronze/counts-before", False, str(exc)))

    first_runs = []
    second_runs = []
    for source, fixture in (("market", MARKET_FIXTURE), ("social", SOCIAL_FIXTURE)):
        first = run_replay(source, fixture)
        first_runs.append(first)
        outputs.append(first)
        first_status = first["result"].get("status")
        checks.append(
            (
                f"ingest/{source}/first",
                first["exit_code"] == 0,
                f"exit={first['exit_code']} status={first_status}",
            )
        )

    for source, fixture in (("market", MARKET_FIXTURE), ("social", SOCIAL_FIXTURE)):
        second = run_replay(source, fixture)
        second_runs.append(second)
        outputs.append(second)
        second_status = second["result"].get("status")
        checks.append(
            (
                f"ingest/{source}/second",
                second["exit_code"] == 0,
                f"exit={second['exit_code']} status={second_status}",
            )
        )

    for source, first, second in zip(
        ("market", "social"), first_runs, second_runs, strict=True
    ):
        checks.append(
            (
                f"ingest/{source}/idempotent",
                accepted_statuses(
                    first["result"].get("status"),
                    second["result"].get("status"),
                ),
                f"first={first['result'].get('status')} second={second['result'].get('status')}",
            )
        )

    try:
        after = bronze_counts()
    except Exception as exc:
        after = {}
        checks.append(("bronze/counts-after", False, str(exc)))

    counts_detail = (
        f"before={json.dumps(before, sort_keys=True)} "
        f"after={json.dumps(after, sort_keys=True)}"
    )
    checks.append(
        (
            "bronze/counts-stable",
            counts_match(before, after, MINIMUMS),
            counts_detail,
        )
    )

    batch_ids = {
        str(run["result"]["batch_id"])
        for run in second_runs
        if run["result"].get("batch_id")
    }
    try:
        rows = ledger_rows(batch_ids)
    except Exception as exc:
        rows = []
        checks.append(("ledger/read", False, str(exc)))
    checks.append(
        (
            "ledger/batches",
            ledger_rows_ok(rows, batch_ids),
            f"expected={sorted(batch_ids)} rows={rows}",
        )
    )
    return checks, outputs


def write_evidence(
    checks: list[tuple[str, bool, str]],
    outputs: list[dict[str, Any]],
    timestamp: str,
    iso: str,
    commit: str,
    passed: bool,
) -> Path:
    target = ROOT / "evidence" / "e2e" / f"SMOKE-W1A_{timestamp}_{commit}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "id        : E2E-W1A",
        f"timestamp : {iso}",
        f"commit    : {commit}",
        "command   : python scripts/e2e_smoke.py",
        f"result    : {'PASS' if passed else 'FAIL'}",
        f"owner     : {OWNER}",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for name, ok, detail in checks:
        lines.append(f"| `{name}` | {'PASS' if ok else 'FAIL'} | {detail} |")
    lines.extend(["", "=== replay output ==="])
    for output in outputs:
        lines.extend(
            [
                f"$ {output['command']}",
                f"exit_code: {output['exit_code']}",
                output["output"].rstrip(),
                "",
            ]
        )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def main() -> int:
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M")
    iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    commit = commit_sha()

    try:
        checks, outputs = evaluate()
    except Exception as exc:
        checks = [("smoke/exception", False, str(exc))]
        outputs = []

    passed = bool(checks) and all(ok for _, ok, _ in checks)
    target = write_evidence(checks, outputs, timestamp, iso, commit, passed)
    print(
        json.dumps(
            {
                "result": "PASS" if passed else "FAIL",
                "commit": commit,
                "evidence": str(target.relative_to(ROOT)).replace("\\", "/"),
                "checks": [
                    {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail}
                    for name, ok, detail in checks
                ],
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
