#!/usr/bin/env python3
"""Snapshot serving.predictions health and optionally clean stale ok rows."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from dotenv import load_dotenv

from bmip.common.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
STALE_CONDITION = "feature_ts < now() - interval '2 hours'"


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def counts(connection) -> dict[str, Any]:
    rows = connection.execute(
        f"""
        SELECT status, count(*) AS rows,
               count(*) FILTER (WHERE {STALE_CONDITION}) AS stale_rows
        FROM serving.predictions
        GROUP BY status
        ORDER BY status
        """
    ).fetchall()
    stale_ok = connection.execute(
        f"SELECT count(*) FROM serving.predictions WHERE status='ok' AND {STALE_CONDITION}"
    ).fetchone()[0]
    return {
        "by_status": [
            {"status": status, "rows": int(rows_count), "stale_rows": int(stale)}
            for status, rows_count, stale in rows
        ],
        "stale_ok": int(stale_ok),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    settings = get_settings()
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    with psycopg.connect(settings.postgres_dsn) as connection:
        before = counts(connection)
        updated = []
        if args.clean:
            rows = connection.execute(
                f"""
                UPDATE serving.predictions
                SET status='error',
                    detail='stale feature_ts; marked error by W2-A cleanup'
                WHERE status='ok' AND {STALE_CONDITION}
                RETURNING symbol, window_start, feature_ts, request_id
                """
            ).fetchall()
            updated = [
                {
                    "symbol": symbol,
                    "window_start": window_start.isoformat(),
                    "feature_ts": feature_ts.isoformat() if feature_ts else None,
                    "request_id": request_id,
                }
                for symbol, window_start, feature_ts, request_id in rows
            ]
        after = counts(connection)
        connection.commit()

    payload = {
        "id": "W2-A-PREDICTION-HEALTH",
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "commit": commit_sha(),
        "command": "python scripts/w2a_prediction_health.py" + (" --clean" if args.clean else ""),
        "result": "PASS" if after["stale_ok"] == 0 else "FAIL",
        "before": before,
        "updated_rows": updated,
        "after": after,
    }
    target = ROOT / "evidence" / "ml" / f"predictions_health_{stamp}.json"
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
