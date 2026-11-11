#!/usr/bin/env python3
"""Generate CP2 evidence: contract tests, bronze counts, and the batch ledger."""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from bmip.common.config import get_settings
from bmip.ingestion.bronze import BronzeWriter
from bmip.ingestion.contracts import (
    load_fixture,
    validate_market_trade,
    validate_social_post,
)

ROOT = Path(__file__).resolve().parents[1]
OWNER = "dhea"


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def contract_tests(timestamp: str, commit: str) -> bool:
    social = validate_social_post(load_fixture("social_post_valid.json"))
    t01 = {
        "id": "T-01",
        "timestamp": timestamp,
        "commit": commit,
        "command": "python scripts/cp2_evidence.py",
        "result": "PASS" if social.ok else "FAIL",
        "owner": OWNER,
        "fixture": "tests/fixtures/social_post_valid.json",
        "errors": [
            {"path": issue.path, "message": issue.message} for issue in social.errors
        ],
    }
    write_json(ROOT / "evidence" / "tests" / "T01.json", t01)

    market = validate_market_trade(load_fixture("market_trade_negative_price.json"))
    price_error = any(issue.path == "$.price" for issue in market.errors)
    t02 = {
        "id": "T-02",
        "timestamp": timestamp,
        "commit": commit,
        "command": "python scripts/cp2_evidence.py",
        "result": "PASS" if (not market.ok and price_error) else "FAIL",
        "owner": OWNER,
        "fixture": "tests/fixtures/market_trade_negative_price.json",
        "errors": [
            {"path": issue.path, "message": issue.message} for issue in market.errors
        ],
    }
    write_json(ROOT / "evidence" / "tests" / "T02.json", t02)
    return bool(t01["result"] == "PASS" and t02["result"] == "PASS")


def write_counts(timestamp: str, commit: str) -> bool:
    settings = get_settings()
    rows = BronzeWriter(settings).counts()
    target = ROOT / "evidence" / "ingestion" / f"counts_{timestamp}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "generated_at",
                "commit",
                "command",
                "table",
                "row_count",
                "min_ts",
                "max_ts",
                "error",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "generated_at": timestamp,
                    "commit": commit,
                    "command": "python scripts/cp2_evidence.py",
                    **row,
                }
            )
    return all(row["row_count"] > 0 for row in rows)


def write_ledger(timestamp: str, commit: str) -> bool:
    settings = get_settings()
    query = """
        SELECT batch_id, source, window_start, window_end, row_count,
               checksum, status, created_at, updated_at
        FROM ops.batch_runs
        ORDER BY created_at
    """
    with psycopg.connect(settings.postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
    target = ROOT / "evidence" / "batch" / f"ledger_{timestamp}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "generated_at",
                "commit",
                "command",
                "batch_id",
                "source",
                "window_start",
                "window_end",
                "row_count",
                "checksum",
                "status",
                "created_at",
                "updated_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    timestamp,
                    commit,
                    "python scripts/cp2_evidence.py",
                    *[value.isoformat() if hasattr(value, "isoformat") else value for value in row],
                ]
            )
    return bool(rows)


def main() -> int:
    commit = commit_sha()
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M")
    iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    contracts_ok = contract_tests(iso, commit)
    counts_ok = write_counts(timestamp, commit)
    ledger_ok = write_ledger(timestamp, commit)
    result = "PASS" if contracts_ok and counts_ok and ledger_ok else "FAIL"
    print(
        json.dumps(
            {
                "result": result,
                "contracts": contracts_ok,
                "counts": counts_ok,
                "ledger": ledger_ok,
                "commit": commit,
                "timestamp": timestamp,
            },
            indent=2,
        )
    )
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
