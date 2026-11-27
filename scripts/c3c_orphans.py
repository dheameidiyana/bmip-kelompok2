#!/usr/bin/env python3
"""Run orphan-file reconciliation for the C3-C gold tables and write evidence."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
EVIDENCE = ROOT / "evidence" / "storage"


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def main() -> int:
    from bmip.common.config import get_settings
    from bmip.lifecycle import remove_orphans
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    settings = get_settings()
    catalog = load_rest_catalog(settings, "process")
    results: dict[str, object] = {}
    for identifier in ("gold.mart_market", "gold.mart_ml", "gold.mart_sentiment"):
        table = table_with_host_io(catalog, settings, identifier, "process")
        results[identifier] = remove_orphans(table, settings, apply=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    document = {
        "id": "CP3-orphan-removal",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_orphans.py",
        "result": "PASS",
        "owner": "vio",
        "criteria": "S3 objects under <table>/data/ not referenced by any manifest, older than 24h",
        "tables": results,
    }
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / f"orphans_{stamp}.json"
    path.write_text(json.dumps(document, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"result": "PASS", "evidence": str(path.relative_to(ROOT))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
