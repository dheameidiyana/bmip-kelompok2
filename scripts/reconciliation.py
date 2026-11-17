#!/usr/bin/env python3
"""Reconciliation draft (T-37, W1-D): API vs serving SQL vs Iceberg gold.

The final reconciliation (including Grafana panels) is W2-B scope; this file is
the draft the workplan asks W1-D to record.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from api_evidence import step_reconcile  # noqa: E402


def main() -> int:
    result = step_reconcile({"with_faults": False})
    print(json.dumps(result, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
