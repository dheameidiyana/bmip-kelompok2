#!/usr/bin/env python3
"""Generate W1-B T27 evidence: retry after a post-bronze failure."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from bmip.common.config import get_settings
from bmip.ingestion.bronze import BronzeWriter
from bmip.ingestion.ledger import get_batch
from bmip.ingestion.pipeline import run_market_batch

ROOT = Path(__file__).resolve().parents[1]
OWNER = "lois"


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


class FailAfterBronzeWriter(BronzeWriter):
    def append_market(self, rows: list[dict[str, Any]]) -> int:
        super().append_market(rows)
        raise RuntimeError("injected failure after bronze append")


def market_items(now: datetime, trade_id: int) -> list[dict[str, Any]]:
    event_ts = now - timedelta(minutes=2)
    payload = {
        "symbol": "BTCUSDT",
        "trade_id": trade_id,
        "event_ts": iso_z(event_ts),
        "price": 68100.50,
        "qty": 0.01,
        "is_buyer_maker": False,
        "ingest_ts": iso_z(now),
        "source": "binance_ws",
        "schema_version": "1.0",
        "payload_hash": hashlib.sha256(f"t27-{trade_id}".encode()).hexdigest(),
    }
    return [payload]


def main() -> int:
    now = datetime.now(UTC)
    iso = iso_z(now)
    commit = commit_sha()
    settings = get_settings()
    trade_id = int(now.timestamp() * 1_000_000) + 27_000_000

    first_error = None
    try:
        run_market_batch(
            settings,
            market_items(now, trade_id),
            publish=False,
            writer=FailAfterBronzeWriter(settings),
        )
    except RuntimeError as exc:
        first_error = str(exc)

    event_ts = now - timedelta(minutes=2)
    batch_id = f"market-binance_ws-{event_ts:%Y%m%dT%H%M%S}-{trade_id}"
    failed = get_batch(settings.postgres_dsn, batch_id)
    writer = BronzeWriter(settings)
    rows_before = writer.fetch_market_batch(batch_id)

    retry = run_market_batch(
        settings,
        market_items(now, trade_id),
        publish=False,
        writer=writer,
    )
    succeeded = get_batch(settings.postgres_dsn, batch_id)
    rows_after = writer.fetch_market_batch(batch_id)
    duplicate_count = len(rows_after) - len(rows_before)

    passed = (
        first_error == "injected failure after bronze append"
        and failed is not None
        and failed.status == "failed"
        and succeeded is not None
        and succeeded.status == "succeeded"
        and retry.status == "succeeded"
        and len(rows_before) == 1
        and len(rows_after) == 1
        and duplicate_count == 0
    )
    payload = {
        "id": "T27",
        "timestamp": iso,
        "commit": commit,
        "command": "python scripts/t27_evidence.py",
        "owner": OWNER,
        "result": "PASS" if passed else "FAIL",
        "batch_id": batch_id,
        "first_error": first_error,
        "ledger_first": failed.__dict__ if failed else None,
        "ledger_retry": succeeded.__dict__ if succeeded else None,
        "bronze_rows_before_retry": len(rows_before),
        "bronze_rows_after_retry": len(rows_after),
        "duplicate_count": duplicate_count,
        "retry": retry.as_dict(),
    }
    path = ROOT / "evidence" / "batch" / "T27.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
