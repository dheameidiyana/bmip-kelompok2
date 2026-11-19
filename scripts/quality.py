#!/usr/bin/env python3
"""Run the Great Expectations checkpoint and write dq_report.json.

A critical failure exits non-zero and blocks gold promotion. ``--warning-only``
keeps the run alive but records the override in the report so the deviation is
visible instead of silent (workplan W1-C risk table).

W2-B also pushes the failure counts to the Pushgateway so the dashboard and the
alert rules can see a gate that just failed.
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


def _run(args: argparse.Namespace, registry):
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

    warnings = sum(len(suite.warning_failures) for suite in report.suites)
    registry.set(
        "bmip_dq_failures_total",
        len(report.critical_failures),
        {"severity": "critical", "scope": args.scope},
        help="Critical rule failures in the last checkpoint.",
        kind="counter",
    )
    registry.set(
        "bmip_dq_failures_total",
        warnings,
        {"severity": "warning", "scope": args.scope},
        help="Warning rule failures in the last checkpoint.",
        kind="counter",
    )
    return report, output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BMIP data-quality checkpoint")
    parser.add_argument("--scope", choices=("silver", "gold", "all"), default="all")
    parser.add_argument("--output", default="evidence/dq/dq_report.json")
    parser.add_argument("--warning-only", action="store_true")
    parser.add_argument("--owner", default="vio")
    args = parser.parse_args(argv)

    from bmip.observability import batch_run

    try:
        with batch_run("quality") as registry:
            report, output = _run(args, registry)
    except Exception as exc:  # noqa: BLE001 - the CLI turns every failure into exit 1
        print(f"quality run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

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
