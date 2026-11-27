"""Exercise the promotion/archive decision logic without changing MLflow."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bmip.ml.registry import promotion_plan

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cases = [
        {
            "case": "better challenger accepted",
            "gate_pass": True,
            "champion_before": "2",
            "candidate_version": "6",
            "expected": {
                "decision": "promoted",
                "champion_after": "6",
                "archived_version": "2",
            },
        },
        {
            "case": "worse challenger rejected",
            "gate_pass": False,
            "champion_before": "2",
            "candidate_version": "7",
            "expected": {
                "decision": "rejected",
                "champion_after": "2",
                "archived_version": None,
            },
        },
    ]
    results = []
    for case in cases:
        plan = promotion_plan(
            gate_pass=case["gate_pass"],
            champion_before=case["champion_before"],
            candidate_version=case["candidate_version"],
        )
        passed = all(plan[key] == value for key, value in case["expected"].items())
        results.append({**case, "actual": plan, "pass": passed})
    payload = {
        "id": "C3-B-promotion-logic",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "Controlled gate-logic fixture; no MLflow alias is changed.",
        "pass": all(item["pass"] for item in results),
        "cases": results,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"promotion_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["pass"] else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
