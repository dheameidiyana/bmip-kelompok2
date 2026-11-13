#!/usr/bin/env python3
"""Generate W1-B CP2 evidence: T04, T06, T07, and T08."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from confluent_kafka import Producer

from bmip.common.config import get_settings
from bmip.ingestion.kafka import ensure_topic, publish_market_trades
from bmip.transform.silver import SilverWriter

ROOT = Path(__file__).resolve().parents[1]
OWNER = "lois"
QUANT = Decimal("0.00000001")


def commit_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def parse_result(text: str, key: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    index = 0
    while True:
        index = text.find("{", index)
        if index < 0:
            return None
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(payload, dict) and key in payload:
            return payload
        index += end


def run_stream(group: str, topic: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "bmip.transform.cli",
        "stream",
        "--once",
        "--group",
        group,
        "--topic",
        topic,
        "--idle-timeout",
        "5",
        "--no-metrics",
    ]
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        timeout=180,
        check=False,
    )
    output = process.stdout + process.stderr
    return {
        "command": " ".join(["python", *command[1:]]),
        "exit_code": process.returncode,
        "result": (parse_result(output, "stream") or {}).get("stream", {}),
        "output": output,
    }


def publish_raw(brokers: str, topic: str, payload: bytes) -> None:
    ensure_topic(brokers, topic)
    producer = Producer(
        {
            "bootstrap.servers": brokers,
            "acks": "all",
            "enable.idempotence": True,
            "message.timeout.ms": 15000,
        }
    )
    errors: list[Any] = []

    def on_delivery(error: Any, _message: Any) -> None:
        if error is not None:
            errors.append(error)

    producer.produce(topic, value=payload, on_delivery=on_delivery)
    producer.flush(timeout=30)
    if errors:
        raise RuntimeError(f"failed to publish raw payload: {errors[0]}")


def trade(
    trade_id: int,
    base: datetime,
    *,
    offset_seconds: float,
    price: str,
    qty: str,
) -> dict[str, Any]:
    event_ts = base + timedelta(seconds=offset_seconds)
    return {
        "symbol": "BTCUSDT",
        "trade_id": trade_id,
        "event_ts": event_ts.isoformat().replace("+00:00", "Z"),
        "price": price,
        "qty": qty,
        "is_buyer_maker": False,
        "ingest_ts": event_ts.isoformat().replace("+00:00", "Z"),
        "source": "evidence",
    }


def decimal_value(row: dict[str, Any], key: str) -> Decimal:
    return Decimal(str(row[key])).quantize(QUANT)


def bar_map(bar: dict[str, Any]) -> dict[str, Any]:
    return {
        "open": decimal_value(bar, "open"),
        "high": decimal_value(bar, "high"),
        "low": decimal_value(bar, "low"),
        "close": decimal_value(bar, "close"),
        "volume": decimal_value(bar, "volume"),
        "quote_volume": decimal_value(bar, "quote_volume"),
        "vwap": decimal_value(bar, "vwap"),
        "trade_count": int(bar["trade_count"]),
    }


def header(evidence_id: str, iso: str, commit: str, result: str) -> list[str]:
    return [
        f"id        : {evidence_id}",
        f"timestamp : {iso}",
        f"commit    : {commit}",
        "command   : python scripts/cp2_market_evidence.py",
        f"result    : {result}",
        f"owner     : {OWNER}",
        "",
    ]


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    now = datetime.now(UTC)
    iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    commit = commit_sha()
    stamp = now.strftime("%Y%m%d%H%M%S")
    topic = f"market.cp2-{stamp}"
    group = f"cp2-{stamp}"
    settings = get_settings()

    base = (
        datetime(2020, 1, 1, tzinfo=UTC)
        + timedelta(seconds=int(now.timestamp()) % (5 * 365 * 24 * 60 * 60))
    ).replace(second=0, microsecond=0)
    window_start = base.replace(second=0, microsecond=0)
    event_date = window_start.date()

    writer = SilverWriter(settings)
    writer.ensure_tables()

    base_trade_id = int(now.timestamp() * 1_000_000)
    base_trades = [
        trade(base_trade_id + 1, base, offset_seconds=1.0, price="68000.50", qty="0.01"),
        trade(base_trade_id + 2, base, offset_seconds=2.0, price="68001.25", qty="0.02"),
        trade(base_trade_id + 3, base, offset_seconds=3.0, price="67999.75", qty="0.01"),
    ]
    late_trade = trade(
        base_trade_id + 4,
        base,
        offset_seconds=0.5,
        price="68002.00",
        qty="0.003",
    )

    evidence_dir = ROOT / "evidence" / "tests"
    summary: dict[str, Any] = {
        "id": "CP2",
        "timestamp": iso,
        "commit": commit,
        "command": "python scripts/cp2_market_evidence.py",
        "owner": OWNER,
        "topic": topic,
        "group": group,
        "window_start": window_start.isoformat().replace("+00:00", "Z"),
        "tests": {},
    }

    published = publish_market_trades(settings.redpanda_brokers, topic, base_trades)
    if published != len(base_trades):
        raise RuntimeError(f"published {published} of {len(base_trades)} base trades")
    first_run = run_stream(group, topic)

    trades_before = writer.fetch_trades("BTCUSDT", event_date)
    bars_before = writer.fetch_ohlcv("BTCUSDT", window_start)
    if len(bars_before) != 1:
        raise RuntimeError(f"expected one OHLCV row, found {len(bars_before)}")
    bar_before = bar_map(bars_before[0])

    expected = {
        "open": Decimal("68000.50000000"),
        "high": Decimal("68001.25000000"),
        "low": Decimal("67999.75000000"),
        "close": Decimal("67999.75000000"),
        "volume": Decimal("0.04000000"),
        "quote_volume": Decimal("2720.02750000"),
        "vwap": Decimal("68000.68750000"),
        "trade_count": 3,
    }
    t08_passed = bar_before == expected
    expected_json = json.dumps({k: str(v) for k, v in expected.items()}, sort_keys=True)
    actual_json = json.dumps({k: str(v) for k, v in bar_before.items()}, sort_keys=True)
    t08_lines = header("T08", iso, commit, "PASS" if t08_passed else "FAIL")
    t08_lines.extend(
        [
            f"topic        : {topic}",
            f"window_start : {window_start.isoformat()}",
            f"expected     : {expected_json}",
            f"actual       : {actual_json}",
            "",
            f"$ {first_run['command']}",
            f"exit_code: {first_run['exit_code']}",
            first_run["output"].rstrip(),
        ]
    )
    write_text(evidence_dir / "T08.txt", t08_lines)
    summary["tests"]["T08"] = {"result": "PASS" if t08_passed else "FAIL", "actual": bar_before}

    duplicate = publish_market_trades(
        settings.redpanda_brokers,
        topic,
        [base_trades[0]],
    )
    if duplicate != 1:
        raise RuntimeError("failed to publish duplicate trade")
    duplicate_run = run_stream(group, topic)
    trades_after = writer.fetch_trades("BTCUSDT", event_date)
    bars_after = writer.fetch_ohlcv("BTCUSDT", window_start)
    if len(bars_after) != 1:
        raise RuntimeError(f"expected one OHLCV row after duplicate, found {len(bars_after)}")
    bar_after = bar_map(bars_after[0])
    t04_passed = (
        len(trades_after) == len(trades_before)
        and bar_after["volume"] == bar_before["volume"]
        and int(duplicate_run["result"].get("duplicates", 0)) >= 1
    )
    t04_lines = header("T04", iso, commit, "PASS" if t04_passed else "FAIL")
    t04_lines.extend(
        [
            f"topic              : {topic}",
            f"trades_before      : {len(trades_before)}",
            f"trades_after       : {len(trades_after)}",
            f"volume_before      : {bar_before['volume']}",
            f"volume_after       : {bar_after['volume']}",
            f"duplicate_processed: {duplicate_run['result'].get('duplicates')}",
            "",
            f"$ {duplicate_run['command']}",
            f"exit_code: {duplicate_run['exit_code']}",
            duplicate_run["output"].rstrip(),
        ]
    )
    write_text(evidence_dir / "T04.txt", t04_lines)
    summary["tests"]["T04"] = {
        "result": "PASS" if t04_passed else "FAIL",
        "trades_before": len(trades_before),
        "trades_after": len(trades_after),
        "volume_before": str(bar_before["volume"]),
        "volume_after": str(bar_after["volume"]),
    }

    publish_market_trades(settings.redpanda_brokers, topic, [late_trade])
    late_run = run_stream(group, topic)
    bars_late = writer.fetch_ohlcv("BTCUSDT", window_start)
    if len(bars_late) != 1:
        raise RuntimeError(f"expected one OHLCV row after late trade, found {len(bars_late)}")
    bar_late = bar_map(bars_late[0])
    expected_late = {
        "open": Decimal("68002.00000000"),
        "high": Decimal("68002.00000000"),
        "low": Decimal("67999.75000000"),
        "close": Decimal("67999.75000000"),
        "volume": Decimal("0.04300000"),
        "quote_volume": Decimal("2924.03350000"),
        "vwap": Decimal("68000.77906977"),
        "trade_count": 4,
    }
    t06_passed = bar_late == expected_late
    expected_late_json = json.dumps(
        {k: str(v) for k, v in expected_late.items()},
        sort_keys=True,
    )
    actual_late_json = json.dumps({k: str(v) for k, v in bar_late.items()}, sort_keys=True)
    t06_lines = header("T06", iso, commit, "PASS" if t06_passed else "FAIL")
    t06_lines.extend(
        [
            f"topic        : {topic}",
            f"window_start : {window_start.isoformat()}",
            f"late_trade   : {json.dumps(late_trade, sort_keys=True)}",
            f"expected     : {expected_late_json}",
            f"actual       : {actual_late_json}",
            f"late_events  : {late_run['result'].get('late_events')}",
            "",
            f"$ {late_run['command']}",
            f"exit_code: {late_run['exit_code']}",
            late_run["output"].rstrip(),
        ]
    )
    write_text(evidence_dir / "T06.txt", t06_lines)
    summary["tests"]["T06"] = {
        "result": "PASS" if t06_passed else "FAIL",
        "actual": bar_late,
        "late_events": late_run["result"].get("late_events"),
    }

    publish_raw(settings.redpanda_brokers, topic, b"{not-json")
    quarantine_run = run_stream(group, topic)
    quarantine_rows = writer.fetch_quarantine(topic=topic, reason="malformed_json")
    t07_passed = (
        len(quarantine_rows) >= 1
        and int(quarantine_run["result"].get("quarantined", 0)) >= 1
    )
    t07_lines = header("T07", iso, commit, "PASS" if t07_passed else "FAIL")
    t07_lines.extend(
        [
            f"topic            : {topic}",
            f"quarantine_rows  : {len(quarantine_rows)}",
            f"reasons          : {[row['reason'] for row in quarantine_rows]}",
            f"quarantined_metric: {quarantine_run['result'].get('quarantined')}",
            "",
            f"$ {quarantine_run['command']}",
            f"exit_code: {quarantine_run['exit_code']}",
            quarantine_run["output"].rstrip(),
        ]
    )
    write_text(evidence_dir / "T07.txt", t07_lines)
    summary["tests"]["T07"] = {
        "result": "PASS" if t07_passed else "FAIL",
        "rows": len(quarantine_rows),
        "reasons": [row["reason"] for row in quarantine_rows],
    }

    passed = all(test["result"] == "PASS" for test in summary["tests"].values())
    summary["result"] = "PASS" if passed else "FAIL"
    summary["evidence"] = [
        "evidence/tests/T04.txt",
        "evidence/tests/T06.txt",
        "evidence/tests/T07.txt",
        "evidence/tests/T08.txt",
    ]
    summary_path = evidence_dir / f"CP2_{stamp}.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    summary["evidence"].append(str(summary_path.relative_to(ROOT)).replace("\\", "/"))
    print(json.dumps(summary, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
