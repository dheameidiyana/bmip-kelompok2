"""Run one hourly batch inference for all configured symbols."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bmip.common.config import get_settings
from bmip.ml.batch import run_batch

ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    result = run_batch(get_settings())
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"predictions_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
