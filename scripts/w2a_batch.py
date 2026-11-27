"""Run one hourly batch inference for all configured symbols.

W2-B adds the predictions metric: one counter per status, pushed to the
Pushgateway so the dashboard and the alert rules see a failed inference run.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bmip.common.config import get_settings
from bmip.ml.batch import run_batch
from bmip.observability import batch_run

ROOT = Path(__file__).resolve().parents[1]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _record(registry, result: dict) -> None:
    rows = (result.get("symbols") or {}).values()
    ok = sum(1 for row in rows if row.get("status") == "ok")
    error = sum(1 for row in rows if row.get("status") == "error")
    registry.set(
        "bmip_predictions_total",
        ok,
        {"status": "ok"},
        help="Inference rows written by the last batch.",
        kind="counter",
    )
    registry.set(
        "bmip_predictions_total",
        error,
        {"status": "error"},
        help="Inference rows that failed in the last batch.",
        kind="counter",
    )
    for symbol, row in (result.get("symbols") or {}).items():
        age = row.get("age_seconds")
        if age is None:
            continue
        registry.set(
            "bmip_feature_age_seconds",
            float(age),
            {"symbol": symbol},
            help="Age of the feature row used for batch inference.",
            kind="gauge",
        )


def main() -> int:
    try:
        with batch_run("predictions") as registry:
            result = run_batch(get_settings())
            _record(registry, result)
    except Exception as exc:  # noqa: BLE001 - the CLI turns every failure into exit 1
        print(f"batch inference failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"predictions_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 1 if result.get("failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
