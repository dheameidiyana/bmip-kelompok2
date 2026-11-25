#!/usr/bin/env python3
"""Print scrape-target health and whether the nine pipeline metrics exist.

Exit code 1 when fewer than four targets are UP, which is the CP1 bar.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
METRICS = [
    "bmip_ingest_events_total",
    "bmip_duplicate_total",
    "bmip_quarantine_total",
    "bmip_consumer_lag",
    "bmip_freshness_seconds",
    "bmip_batch_duration_seconds",
    "bmip_gold_rows",
    "bmip_dq_failures_total",
    "bmip_predictions_total",
]


def get(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{PROMETHEUS}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    try:
        targets = get("/api/v1/targets")["data"]["activeTargets"]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        print(f"prometheus is not reachable at {PROMETHEUS}: {exc}", file=sys.stderr)
        return 2

    up = 0
    for target in targets:
        health = target.get("health")
        up += 1 if health == "up" else 0
        print(
            f"{health:8} {target['labels'].get('job', '-'):18} {target.get('scrapeUrl')}"
        )

    print()
    for name in METRICS:
        query = urllib.parse.urlencode({"query": name})
        try:
            series = get(f"/api/v1/query?{query}")["data"]["result"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            series = []
        state = "present" if series else "absent"
        print(f"{state:8} {name} ({len(series)} series)")

    print(f"\ntargets up: {up}/{len(targets)}")
    return 0 if up >= 4 else 1


if __name__ == "__main__":
    raise SystemExit(main())
