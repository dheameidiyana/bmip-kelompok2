#!/usr/bin/env python3
"""Run the C3-C Iceberg lifecycle job and write before/after evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "storage"
load_dotenv(ROOT / ".env")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-compact", action="store_true")
    parser.add_argument("--no-expire", action="store_true")
    parser.add_argument(
        "--orphans",
        action="store_true",
        help="delete orphan data files older than 24h (default: report only)",
    )
    parser.add_argument(
        "--retention-apply",
        default="",
        help="comma list of layers to delete for real (bronze,silver,gold)",
    )
    parser.add_argument("--as-of", default="", help="YYYY-MM-DD reference date")
    parser.add_argument(
        "--tables",
        default="",
        help="comma list of tables; default: every C3-C candidate",
    )
    args = parser.parse_args(argv)

    from bmip.common.config import get_settings
    from bmip.lifecycle import LAYER_RETENTION, run

    settings = get_settings()
    layers = {part.strip() for part in args.retention_apply.split(",") if part.strip()}
    unknown = layers - set(LAYER_RETENTION)
    if unknown:
        raise SystemExit(f"unknown retention layers: {sorted(unknown)}")
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    tables = [part.strip() for part in args.tables.split(",") if part.strip()] or None

    report = run(
        settings,
        compact=not args.no_compact,
        expire=not args.no_expire,
        orphans=args.orphans,
        retention_apply=layers,
        as_of=as_of,
        tables=tables,
    )
    stamp = _stamp()
    compaction_path = EVIDENCE / f"compaction_{stamp}.json"
    compaction_path.parent.mkdir(parents=True, exist_ok=True)
    compaction_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    lines = [
        "id        : CP3-lifecycle-retention",
        f"timestamp : {report['started_at']}",
        f"commit    : {_sha()}",
        "command   : python scripts/c3c_lifecycle.py",
        f"result    : {'PASS' if report['fixture_retention']['result'] == 'PASS' else 'FAIL'}",
        "owner     : vio",
        "",
        "Retention policy: bronze 14 days, silver 30 days, gold 90 days.",
        "Production retention is dry-run in this run; the apply path is proven on "
        "the fixture table below (user decision for C3-C).",
        "",
        "| table | files before | files after | snaps before | snaps after | "
        "old partitions | old rows |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for identifier, entry in report["tables"].items():
        if entry.get("status") != "ok":
            lines.append(f"| {identifier} | - | - | - | - | - | {entry.get('detail', '')} |")
            continue
        compaction = entry.get("compaction") or {}
        before = compaction.get("before") or {}
        after = compaction.get("after") or {}
        snapshots = entry.get("snapshots") or {}
        plan = entry.get("retention_plan") or {}
        lines.append(
            f"| {identifier} | {before.get('files', '-')} | {after.get('files', '-')} | "
            f"{snapshots.get('before', '-')} | {snapshots.get('after', '-')} | "
            f"{plan.get('old_partitions', '-')} | {plan.get('old_rows', '-')} |"
        )
    fixture = report["fixture_retention"]
    lines += [
        "",
        "Fixture retention:",
        f"- table: {fixture['table']}",
        f"- cutoff: {fixture['cutoff']}",
        f"- rows before/after: {fixture['before_rows']} / {fixture['after_rows']}",
        f"- expected after: {fixture['expected_after']}",
        f"- result: {fixture['result']}",
        "",
        f"compaction evidence: {compaction_path.relative_to(ROOT)}",
    ]
    retention_path = EVIDENCE / f"retention_{stamp}.txt"
    retention_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    passed = fixture["result"] == "PASS" and all(
        entry.get("status") in {"ok", "missing"} for entry in report["tables"].values()
    )
    print(
        json.dumps(
            {
                "result": "PASS" if passed else "FAIL",
                "tables": len(report["tables"]),
                "fixture": fixture["result"],
                "compaction": str(compaction_path.relative_to(ROOT)),
                "retention": str(retention_path.relative_to(ROOT)),
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
