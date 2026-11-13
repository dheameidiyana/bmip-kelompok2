#!/usr/bin/env python3
"""Run the Great Expectations checkpoint and write dq_report.json.

A critical failure exits non-zero and blocks gold promotion. ``--warning-only``
keeps the run alive but records the override in the report so the deviation is
visible instead of silent (workplan W1-C risk table).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BMIP data-quality checkpoint")
    parser.add_argument("--scope", choices=("silver", "gold", "all"), default="all")
    parser.add_argument("--output", default="evidence/dq/dq_report.json")
    parser.add_argument("--warning-only", action="store_true")
    parser.add_argument("--owner", default="vio")
    args = parser.parse_args(argv)

    from bmip.common.config import get_settings
    from bmip.quality.checkpoint import run_scope

    report = run_scope(
        get_settings(),
        scope=args.scope,
        warning_only=True,
        commit=_commit(),
        owner=args.owner,
    )
    report.warning_only = args.warning_only

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    report.write(output)

    blocked = bool(report.critical_failures) and not args.warning_only
    for suite_name, rule in report.critical_failures:
        print(f"critical: {suite_name}:{rule.id} {rule.detail}".strip(), file=sys.stderr)
    print(
        f"status={'fail' if blocked else report.status} "
        f"suites={len(report.suites)} report={output}"
    )
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
