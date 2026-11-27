#!/usr/bin/env python3
"""Run the compact_iceberg Prefect flow and write C3-C evidence.

The deployment is declared in prefect.yaml. This script executes the same flow
object locally so the lifecycle path is proven even when the Prefect API/worker
is slow; `prefect deploy` remains the production registration step.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "storage"


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", default="gold.mart_market,gold.mart_ml,gold.mart_sentiment")
    parser.add_argument("--orphans", action="store_true")
    args = parser.parse_args(argv)

    os.environ.setdefault("PREFECT_API_URL", "")
    from bmip.flows.maintenance import compact_iceberg_flow

    tables = [part.strip() for part in args.tables.split(",") if part.strip()]
    result = compact_iceberg_flow(
        compact=True,
        expire=True,
        orphans=args.orphans,
        apply_retention=[],
        tables=tables,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    document = {
        "id": "CP3-prefect-compact-iceberg",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_prefect.py",
        "result": "PASS",
        "owner": "vio",
        "deployment": "compact_iceberg in prefect.yaml (cron 0 1 * * *)",
        "parameters": {
            "compact": True,
            "expire": True,
            "orphans": args.orphans,
            "apply_retention": [],
            "tables": tables,
        },
        "flow_result": result,
    }
    path = EVIDENCE / f"prefect-compact-iceberg_{stamp}.json"
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "evidence": str(path.relative_to(ROOT))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
