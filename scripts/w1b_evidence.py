#!/usr/bin/env python3
"""Generate W1-B CP3 evidence: T05, T24, T28, and T29."""

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
from bmip.transform.dlq import read_dlq
from bmip.transform.silver import SilverWriter, compute_silver_freshness

ROOT = Path(__file__).resolve().parents[1]
OWNER = "lois"
QUANT = Decimal("0.00000001")


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


def run_cli(args: list[str], *, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    command = [sys.executable, "-m", "bmip.transform.cli", *args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if extra_env:
        env.update(extra_env)
    process = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=600,
        check=False,
    )
    output = process.stdout + process.stderr
    return {
        "command": " ".join(["python", *command[1:]]),
        "exit_code": process.returncode,
        "result": (parse_result(output, args[0]) or {}).get(args[0], {}),
        "output": output,
    }


def trade(
    trade_id: int,
    event_ts: datetime,
    *,
    price: str,
    qty: str,
    ingest_ts: datetime | None = None,
) -> dict[str, Any]:
    ingest = ingest_ts or event_ts
    return {
        "symbol": "BTCUSDT",
        "trade_id": trade_id,
        "event_ts": iso_z(event_ts),
        "price": price,
        "qty": qty,
        "is_buyer_maker": False,
        "ingest_ts": iso_z(ingest),
        "source": "evidence",
    }


def publish_bytes(brokers: str, topic: str, payload: bytes) -> None:
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


def bar_map(bar: dict[str, Any]) -> dict[str, Any]:
    def decimal_value(key: str) -> Decimal:
        return Decimal(str(bar[key])).quantize(QUANT)

    return {
        "window_start": iso_z(bar["window_start"]),
        "open": decimal_value("open"),
        "high": decimal_value("high"),
        "low": decimal_value("low"),
        "close": decimal_value("close"),
        "volume": decimal_value("volume"),
        "quote_volume": decimal_value("quote_volume"),
        "vwap": decimal_value("vwap"),
        "trade_count": int(bar["trade_count"]),
    }


def header(evidence_id: str, iso: str, commit: str, result: str) -> list[str]:
    return [
        f"id        : {evidence_id}",
        f"timestamp : {iso}",
        f"commit    : {commit}",
        "command   : python scripts/w1b_evidence.py",
        f"result    : {result}",
        f"owner     : {OWNER}",
        "",
    ]


def write_text(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def run_t05(
    settings: Any,
    writer: SilverWriter,
    *,
    iso: str,
    commit: str,
    stamp: str,
    now: datetime,
) -> dict[str, Any]:
    topic = f"market.t05-{stamp}"
    group_a = f"t05-a-{stamp}"
    group_b = f"t05-b-{stamp}"
    base = (now - timedelta(days=365)).replace(second=0, microsecond=0) - timedelta(
        minutes=int(stamp) % 100000
    )
    end = base + timedelta(hours=1)
    base_id = int(now.timestamp() * 1_000_000)
    records = []
    for minute in range(60):
        for index in range(2):
            event_ts = base + timedelta(minutes=minute, seconds=5 + index * 20)
            records.append(
                trade(
                    base_id + minute * 10 + index,
                    event_ts,
                    price=f"{68000 + minute * 0.5 + index * 0.25:.2f}",
                    qty="0.01" if index == 0 else "0.02",
                )
            )
    published = publish_market_trades(settings.redpanda_brokers, topic, records)
    first = run_cli(
        [
            "replay",
            "--from",
            iso_z(base),
            "--to",
            iso_z(end),
            "--topic",
            topic,
            "--group",
            group_a,
            "--idle-timeout",
            "3",
        ]
    )
    bars_a = writer.fetch_ohlcv_range("BTCUSDT", base, end)
    second = run_cli(
        [
            "replay",
            "--from",
            iso_z(base),
            "--to",
            iso_z(end),
            "--topic",
            topic,
            "--group",
            group_b,
            "--idle-timeout",
            "3",
        ]
    )
    bars_b = writer.fetch_ohlcv_range("BTCUSDT", base, end)
    signature_a = [bar_map(bar) for bar in bars_a]
    signature_b = [bar_map(bar) for bar in bars_b]
    identical = signature_a == signature_b
    complete = len(bars_a) == 60 and all(bar["trade_count"] == 2 for bar in signature_a)
    passed = (
        first["exit_code"] == 0
        and second["exit_code"] == 0
        and int(first["result"].get("processed", 0)) == len(records)
        and int(second["result"].get("processed", 0)) == len(records)
        and identical
        and complete
    )
    lines = header("T05", iso, commit, "PASS" if passed else "FAIL")
    lines.extend(
        [
            f"topic          : {topic}",
            f"published      : {published}",
            f"range          : {iso_z(base)} .. {iso_z(end)}",
            f"bars_first     : {len(bars_a)}",
            f"bars_second    : {len(bars_b)}",
            f"identical      : {identical}",
            f"complete       : {complete}",
            f"processed_a    : {first['result'].get('processed')}",
            f"processed_b    : {second['result'].get('processed')}",
            f"duplicates_b   : {second['result'].get('duplicates')}",
            f"flushes_a      : {first['result'].get('flushes')}",
            f"flushes_b      : {second['result'].get('flushes')}",
            f"signature_sha  : {hash(json.dumps(signature_a, default=str, sort_keys=True))}",
            "",
            f"$ {first['command']}",
            f"exit_code: {first['exit_code']}",
            first["output"].rstrip(),
            "",
            f"$ {second['command']}",
            f"exit_code: {second['exit_code']}",
            second["output"].rstrip(),
        ]
    )
    write_text(ROOT / "evidence" / "replay" / "T05.txt", lines)
    return {
        "result": "PASS" if passed else "FAIL",
        "topic": topic,
        "published": published,
        "bars_first": len(bars_a),
        "bars_second": len(bars_b),
        "identical": identical,
        "complete": complete,
        "first": first["result"],
        "second": second["result"],
    }


def run_t24(
    settings: Any,
    writer: SilverWriter,
    *,
    iso: str,
    commit: str,
    stamp: str,
    now: datetime,
) -> dict[str, Any]:
    topic = f"market.t24-{stamp}"
    group = f"t24-{stamp}"
    event_ts = now - timedelta(seconds=20)
    ingest_ts = now - timedelta(seconds=5)
    record = trade(
        int(now.timestamp() * 1_000_000) + 10_000_000,
        event_ts,
        price="68010.25",
        qty="0.01",
        ingest_ts=ingest_ts,
    )
    published = publish_market_trades(settings.redpanda_brokers, topic, [record])
    stream = run_cli(
        [
            "stream",
            "--once",
            "--group",
            group,
            "--topic",
            topic,
            "--idle-timeout",
            "3",
            "--no-metrics",
        ]
    )
    trade_rows = [
        row
        for row in writer.fetch_trades("BTCUSDT", event_ts.date())
        if int(row["trade_id"]) == record["trade_id"]
    ]
    window_start = event_ts.replace(second=0, microsecond=0)
    bar_rows = writer.fetch_ohlcv("BTCUSDT", window_start)
    freshness = compute_silver_freshness(
        trade_rows,
        bar_rows,
        now=datetime.now(UTC),
    )
    lag = freshness.ingest_lag_seconds
    age = freshness.bar_age_seconds
    passed = (
        stream["exit_code"] == 0
        and published == 1
        and lag is not None
        and lag <= 120
        and age is not None
        and age <= 120
    )
    lines = header("T24", iso, commit, "PASS" if passed else "FAIL")
    lines.extend(
        [
            f"topic              : {topic}",
            f"published          : {published}",
            f"event_ts           : {iso_z(event_ts)}",
            f"ingest_ts          : {iso_z(ingest_ts)}",
            f"freshness          : {json.dumps(freshness.to_dict(), sort_keys=True)}",
            f"ingest_lag_seconds : {lag}",
            f"bar_age_seconds    : {age}",
            "threshold_seconds  : 120",
            "",
            f"$ {stream['command']}",
            f"exit_code: {stream['exit_code']}",
            stream["output"].rstrip(),
        ]
    )
    write_text(ROOT / "evidence" / "tests" / "T24.txt", lines)
    return {
        "result": "PASS" if passed else "FAIL",
        "topic": topic,
        "freshness": freshness.to_dict(),
        "stream": stream["result"],
    }


def run_t28(
    settings: Any,
    writer: SilverWriter,
    *,
    iso: str,
    commit: str,
    stamp: str,
    now: datetime,
) -> dict[str, Any]:
    topic = f"market.t28-{stamp}"
    group = f"t28-{stamp}"
    base = (now - timedelta(minutes=10)).replace(second=0, microsecond=0)
    base_id = int(now.timestamp() * 1_000_000)
    records = [
        trade(
            base_id + 20_000_000 + index,
            base + timedelta(seconds=index),
            price=f"{68000 + index:.2f}",
            qty="0.01",
        )
        for index in range(10)
    ]
    published = publish_market_trades(settings.redpanda_brokers, topic, records)
    first = run_cli(
        [
            "stream",
            "--once",
            "--group",
            group,
            "--topic",
            topic,
            "--max-records",
            "4",
            "--idle-timeout",
            "2",
            "--no-metrics",
        ]
    )
    second = run_cli(
        [
            "stream",
            "--once",
            "--group",
            group,
            "--topic",
            topic,
            "--idle-timeout",
            "3",
            "--no-metrics",
        ]
    )
    rows = writer.fetch_trades("BTCUSDT", base.date())
    ids = {int(row["trade_id"]) for row in rows}
    processed = int(first["result"].get("processed", 0)) + int(
        second["result"].get("processed", 0)
    )
    expected_ids = {record["trade_id"] for record in records}
    passed = (
        published == 10
        and first["exit_code"] == 0
        and second["exit_code"] == 0
        and processed == 10
        and expected_ids.issubset(ids)
    )
    lines = header("T28", iso, commit, "PASS" if passed else "FAIL")
    lines.extend(
        [
            f"topic          : {topic}",
            f"group          : {group}",
            f"published      : {published}",
            f"processed_first: {first['result'].get('processed')}",
            f"processed_rest : {second['result'].get('processed')}",
            f"processed_total: {processed}",
            f"silver_rows    : {len(ids & expected_ids)}",
            f"expected_rows  : {len(expected_ids)}",
            "",
            f"$ {first['command']}",
            f"exit_code: {first['exit_code']}",
            first["output"].rstrip(),
            "",
            f"$ {second['command']}",
            f"exit_code: {second['exit_code']}",
            second["output"].rstrip(),
        ]
    )
    write_text(ROOT / "evidence" / "stream" / "T28.txt", lines)
    return {
        "result": "PASS" if passed else "FAIL",
        "topic": topic,
        "group": group,
        "published": published,
        "processed": processed,
        "silver_rows": len(ids & expected_ids),
        "first": first["result"],
        "second": second["result"],
    }


def run_t29(
    settings: Any,
    writer: SilverWriter,
    *,
    iso: str,
    commit: str,
    stamp: str,
    now: datetime,
) -> dict[str, Any]:
    topic = f"market.t29-{stamp}"
    dlq_topic = f"market.t29-dlq-{stamp}"
    group = f"t29-{stamp}"
    event_ts = now - timedelta(minutes=2)
    poison = {
        "symbol": "BTCUSDT",
        "event_ts": iso_z(event_ts),
        "price": "68020.50",
        "qty": "0.01",
        "is_buyer_maker": False,
        "ingest_ts": iso_z(now),
        "source": "evidence",
    }
    ensure_topic(settings.redpanda_brokers, dlq_topic)
    publish_bytes(
        settings.redpanda_brokers,
        topic,
        json.dumps(poison, separators=(",", ":")).encode("utf-8"),
    )
    published = 1
    capture = run_cli(
        [
            "stream",
            "--once",
            "--group",
            group,
            "--topic",
            topic,
            "--idle-timeout",
            "3",
            "--no-metrics",
        ],
        extra_env={"MARKET_DLQ_TOPIC": dlq_topic},
    )
    captured = [
        record
        for record in read_dlq(settings, topic=dlq_topic)
        if record.get("topic") == topic
    ]
    record = captured[-1] if captured else {}
    corrected = json.loads(record.get("raw_payload") or "{}")
    corrected["trade_id"] = int(now.timestamp() * 1_000_000) + 30_000_000
    corrected["ingest_ts"] = iso_z(datetime.now(UTC))
    replayed = publish_market_trades(settings.redpanda_brokers, topic, [corrected])
    replay = run_cli(
        [
            "stream",
            "--once",
            "--group",
            group,
            "--topic",
            topic,
            "--idle-timeout",
            "3",
            "--no-metrics",
        ],
        extra_env={"MARKET_DLQ_TOPIC": dlq_topic},
    )
    rows = writer.fetch_trades("BTCUSDT", event_ts.date())
    accepted = any(int(row["trade_id"]) == corrected["trade_id"] for row in rows)
    passed = (
        published == 1
        and capture["exit_code"] == 0
        and len(captured) >= 1
        and record.get("reason") == "schema_violation"
        and "trade_id" in str(record.get("details") or "")
        and replayed == 1
        and replay["exit_code"] == 0
        and accepted
    )
    payload = {
        "id": "T29",
        "timestamp": iso,
        "commit": commit,
        "command": "python scripts/w1b_evidence.py",
        "owner": OWNER,
        "result": "PASS" if passed else "FAIL",
        "topic": topic,
        "dlq_topic": dlq_topic,
        "published_poison": published,
        "captured": captured,
        "capture_stream": capture["result"],
        "corrected": corrected,
        "replayed": replayed,
        "replay_stream": replay["result"],
        "accepted": accepted,
        "capture_output": capture["output"],
        "replay_output": replay["output"],
    }
    write_json(ROOT / "evidence" / "stream" / "T29.json", payload)
    return {
        "result": payload["result"],
        "topic": topic,
        "dlq_topic": dlq_topic,
        "captured": len(captured),
        "reason": record.get("reason"),
        "replayed": replayed,
        "accepted": accepted,
    }


def main() -> int:
    now = datetime.now(UTC)
    iso = iso_z(now)
    commit = commit_sha()
    stamp = now.strftime("%Y%m%d%H%M%S")
    settings = get_settings()
    writer = SilverWriter(settings)
    writer.ensure_tables()

    tests = {
        "T24": run_t24(settings, writer, iso=iso, commit=commit, stamp=stamp, now=now),
        "T28": run_t28(settings, writer, iso=iso, commit=commit, stamp=stamp, now=now),
        "T29": run_t29(settings, writer, iso=iso, commit=commit, stamp=stamp, now=now),
        "T05": run_t05(settings, writer, iso=iso, commit=commit, stamp=stamp, now=now),
    }
    passed = all(test["result"] == "PASS" for test in tests.values())
    summary = {
        "id": "CP3-W1B",
        "timestamp": iso,
        "commit": commit,
        "owner": OWNER,
        "result": "PASS" if passed else "FAIL",
        "tests": tests,
        "evidence": [
            "evidence/replay/T05.txt",
            "evidence/tests/T24.txt",
            "evidence/stream/T28.txt",
            "evidence/stream/T29.json",
        ],
    }
    write_json(ROOT / "evidence" / f"CP3_W1B_{stamp}.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
