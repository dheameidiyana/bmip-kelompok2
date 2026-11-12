#!/usr/bin/env python3
"""Generate CP3 evidence: replay the pipeline twice and prove idempotence (T-26)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bmip.common.config import get_settings
from bmip.ingestion.bronze import BronzeWriter

ROOT = Path(__file__).resolve().parents[1]
OWNER = "dhea"
MARKET_FIXTURE = "tests/fixtures/binance_agg_trades.jsonl"
SOCIAL_FIXTURE = "tests/fixtures/bluesky_posts.json"


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


def display(command: list[str]) -> str:
    return " ".join(["python", *command[1:]])


def run(command: list[str]) -> tuple[int, str]:
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
    return process.returncode, process.stdout + process.stderr


def replay_once(command: list[str], key: str) -> dict[str, Any]:
    print(f"$ {display(command)}", flush=True)
    code, output = run(command)
    print(output, end="" if output.endswith("\n") else "\n", flush=True)
    result = extract_result(output, key)
    return {"exit_code": code, "output": output, "result": result or {}}


def counts() -> dict[str, int]:
    rows = BronzeWriter(get_settings()).counts()
    return {row["table"]: row["row_count"] for row in rows}


def main() -> int:
    commit = commit_sha()
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M")
    iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    python = sys.executable

    market_cmd = [python, "-m", "bmip.ingestion.cli", "market", "--replay", MARKET_FIXTURE]
    social_cmd = [python, "-m", "bmip.ingestion.cli", "social", "--replay", SOCIAL_FIXTURE]
    commands = [market_cmd, social_cmd]

    before = counts()
    first = []
    second = []
    for command, key in zip(commands, ("market", "social"), strict=True):
        print("=== replay run 1 ===", flush=True)
        first.append(replay_once(command, key))
    for command, key in zip(commands, ("market", "social"), strict=True):
        print("=== replay run 2 ===", flush=True)
        second.append(replay_once(command, key))
    after = counts()

    market_second = second[0]["result"].get("market", {})
    social_second = second[1]["result"].get("social", {})
    idempotent = (
        market_second.get("status") == "skipped_identical"
        and social_second.get("status") == "skipped_identical"
        and before == after
        and all(item["exit_code"] == 0 for item in first + second)
    )
    result = "PASS" if idempotent else "FAIL"

    header = [
        "id        : T-26",
        f"timestamp : {iso}",
        f"commit    : {commit}",
        f"command   : python scripts/cp3_evidence.py ({timestamp})",
        f"result    : {result}",
        f"owner     : {OWNER}",
        "",
    ]
    body = ["=== commands ==="]
    for command in commands:
        body.extend([f"$ {display(command)}", ""])
    for label, runs in (("run 1", first), ("run 2", second)):
        body.extend([f"=== {label} ==="])
        for item in runs:
            body.append(f"exit_code: {item['exit_code']}")
            body.append(item["output"].rstrip())
            body.append("")
    body.extend(
        [
            "=== bronze counts ===",
            f"before: {json.dumps(before, sort_keys=True)}",
            f"after : {json.dumps(after, sort_keys=True)}",
        ]
    )
    replay_path = ROOT / "evidence" / "ingestion" / f"replay_{timestamp}.txt"
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_path.write_text("\n".join(header + body) + "\n", encoding="utf-8")

    evidence = {
        "id": "T-26",
        "timestamp": iso,
        "commit": commit,
        "command": "python scripts/cp3_evidence.py",
        "result": result,
        "owner": OWNER,
        "runs": [
            {
                "source": source,
                "first_status": first[index]["result"].get(source, {}).get("status"),
                "second_status": second[index]["result"].get(source, {}).get("status"),
                "batch_id": second[index]["result"].get(source, {}).get("batch_id"),
                "checksum": second[index]["result"].get(source, {}).get("checksum"),
            }
            for index, source in enumerate(("market", "social"))
        ],
        "bronze_counts": {"before": before, "after": after},
        "replay_log": str(replay_path.relative_to(ROOT)).replace("\\", "/"),
    }
    target = ROOT / "evidence" / "batch" / "T26.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": result,
                "t26": evidence,
                "files": [
                    str(replay_path.relative_to(ROOT)).replace("\\", "/"),
                    str(target.relative_to(ROOT)).replace("\\", "/"),
                ],
            },
            indent=2,
        )
    )
    return 0 if idempotent else 1


if __name__ == "__main__":
    raise SystemExit(main())
