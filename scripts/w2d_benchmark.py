#!/usr/bin/env python3
"""W2-D benchmark matrix (T-42).

The matrix is generated from live measurements, not typed by hand. Rows cover
API latency, DQ runtime, training, inference, cAdvisor resources, replay
throughput, and a small B2 partition-pruning before/after pair. A missing
champion or sparse gold data is recorded as ``partial`` instead of being hidden.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OWNER = "lois"
EVIDENCE_ID = "T-42"
DEFAULT_OUTPUT = ROOT / "evidence" / "benchmark"
DEFAULT_API = "http://127.0.0.1:8000"
DEFAULT_CADVISOR = "http://127.0.0.1:8088"
FIELDS = (
    "scenario",
    "run",
    "started_at",
    "duration_s",
    "requests",
    "errors",
    "throughput_per_s",
    "p50_ms",
    "p95_ms",
    "p99_ms",
    "target",
    "status",
    "detail",
)
RESOURCE_FIELDS = (
    "timestamp",
    "container",
    "cpu_percent",
    "mem_usage",
    "mem_limit",
    "net_io",
    "block_io",
    "pids",
)
PREDICT_FEATURES = {
    "ret_5m": 0.0001,
    "ret_15m": 0.0002,
    "ret_60m": 0.0003,
    "rv_5m": 0.001,
    "rv_15m": 0.002,
    "rv_60m": 0.003,
    "volume_z_60m": 0.5,
    "trade_count_60m": 120.0,
    "hl_range_1m": 0.001,
    "vwap_dev": 0.0002,
    "sent_mean_1h": 0.1,
    "sent_pos_share": 0.4,
    "sent_neg_share": 0.2,
    "post_count_1h": 2.0,
    "engagement_1h": 5.0,
}


def _iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (percent / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _summary(values: list[float]) -> dict[str, float | None]:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return {"p50_ms": None, "p95_ms": None, "p99_ms": None, "mean_ms": None}
    return {
        "p50_ms": round(_percentile(clean, 50) or 0.0, 3),
        "p95_ms": round(_percentile(clean, 95) or 0.0, 3),
        "p99_ms": round(_percentile(clean, 99) or 0.0, 3),
        "mean_ms": round(statistics.fmean(clean), 3),
    }


def _row(
    scenario: str,
    run: int,
    started_at: str,
    duration_s: float,
    requests: int,
    errors: int,
    throughput_per_s: float | None,
    summary: dict[str, float | None],
    target: str,
    status: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "run": run,
        "started_at": started_at,
        "duration_s": round(duration_s, 3),
        "requests": requests,
        "errors": errors,
        "throughput_per_s": None if throughput_per_s is None else round(throughput_per_s, 3),
        "p50_ms": summary.get("p50_ms"),
        "p95_ms": summary.get("p95_ms"),
        "p99_ms": summary.get("p99_ms"),
        "target": target,
        "status": status,
        "detail": detail,
    }


def _call(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = client.request(method, path, **kwargs)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        try:
            body = response.json()
        except ValueError:
            body = None
        return {
            "status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "bytes": len(response.content),
            "body": body,
            "error": None,
        }
    except httpx.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": None,
            "elapsed_ms": elapsed_ms,
            "bytes": 0,
            "body": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _broker_address(value: str) -> str:
    return value.replace("localhost", "127.0.0.1")


def _client(api_url: str, key: str) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if key:
        headers["X-API-Key"] = key
    return httpx.Client(
        base_url=api_url.rstrip("/"),
        headers=headers,
        timeout=30.0,
        trust_env=False,
    )


def _api_latest(
    client: httpx.Client,
    rows: list[dict[str, Any]],
    *,
    requests: int,
    repeats: int,
    warmup: float,
) -> None:
    deadline = time.perf_counter() + max(0.0, warmup)
    while time.perf_counter() < deadline:
        _call(client, "GET", "/v1/market/latest", params={"symbol": "BTCUSDT"})
    for run in range(1, repeats + 1):
        started_at = _iso()
        started = time.perf_counter()
        latencies: list[float] = []
        errors = 0
        for _ in range(requests):
            result = _call(
                client,
                "GET",
                "/v1/market/latest",
                params={"symbol": "BTCUSDT"},
            )
            latencies.append(float(result["elapsed_ms"]))
            if result["status"] != 200:
                errors += 1
        duration = time.perf_counter() - started
        summary = _summary(latencies)
        p95 = summary["p95_ms"] or 0.0
        status = "pass" if errors == 0 and p95 < 300.0 else "fail"
        rows.append(
            _row(
                "api-latest",
                run,
                started_at,
                duration,
                requests,
                errors,
                requests / duration if duration else None,
                summary,
                "p95 < 300 ms",
                status,
                f"requests={requests}; errors={errors}",
            )
        )


def _api_range(
    client: httpx.Client,
    rows: list[dict[str, Any]],
    *,
    requests: int,
    repeats: int,
    range_days: int,
) -> None:
    to_ts = datetime.now(UTC)
    from_ts = to_ts - timedelta(days=range_days)
    params = {
        "symbol": "BTCUSDT",
        "from": _iso(from_ts),
        "to": _iso(to_ts),
        "limit": 1000,
    }
    for run in range(1, repeats + 1):
        started_at = _iso()
        started = time.perf_counter()
        latencies: list[float] = []
        errors = 0
        rows_returned = 0
        sources: set[str] = set()
        for _ in range(requests):
            result = _call(client, "GET", "/v1/market/ohlc", params=params)
            latencies.append(float(result["elapsed_ms"]))
            if result["status"] != 200:
                errors += 1
                continue
            body = result.get("body") or {}
            rows_returned += len(body.get("data") or [])
            sources.add(str((body.get("meta") or {}).get("source")))
        duration = time.perf_counter() - started
        summary = _summary(latencies)
        p95 = summary["p95_ms"] or 0.0
        status = "pass" if errors == 0 and p95 < 2000.0 else "fail"
        rows.append(
            _row(
                f"api-range-{range_days}d",
                run,
                started_at,
                duration,
                requests,
                errors,
                requests / duration if duration else None,
                summary,
                "p95 < 2000 ms",
                status,
                f"rows={rows_returned}; sources={sorted(sources)}; actual data may be sparse",
            )
        )


def _run_dq(rows: list[dict[str, Any]], commit: str) -> None:
    started_at = _iso()
    started = time.perf_counter()
    detail = ""
    status = "partial"
    try:
        from bmip.common.config import get_settings
        from bmip.quality.checkpoint import run_scope

        report = run_scope(
            get_settings(),
            scope="all",
            warning_only=True,
            commit=commit,
            owner=OWNER,
        )
        duration = time.perf_counter() - started
        critical = len(report.critical_failures)
        warnings = sum(len(suite.warning_failures) for suite in report.suites)
        status = "pass" if critical == 0 and duration <= 120.0 else "partial"
        detail = json.dumps(
            {
                "report_status": report.status,
                "critical": critical,
                "critical_rules": [
                    f"{suite}:{rule.id}" for suite, rule in report.critical_failures
                ],
                "warnings": warnings,
                "suites": len(report.suites),
            },
            separators=(",", ":"),
        )
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        duration = time.perf_counter() - started
        detail = f"{type(exc).__name__}: {exc}"
    rows.append(
        _row(
            "dq-runtime",
            1,
            started_at,
            duration,
            1,
            0 if status != "partial" else 1,
            None,
            {"p50_ms": duration * 1000.0, "p95_ms": duration * 1000.0, "p99_ms": duration * 1000.0},
            "<= 120 s",
            status,
            detail,
        )
    )


def _run_training(rows: list[dict[str, Any]], timeout: int) -> None:
    started_at = _iso()
    started = time.perf_counter()
    status = "partial"
    detail = ""
    try:
        process = subprocess.run(
            [sys.executable, "scripts/w2a_train.py", "--ignore-champion"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = time.perf_counter() - started
        output = (process.stdout or "") + (process.stderr or "")
        tail = " | ".join(line.strip() for line in output.splitlines()[-4:] if line.strip())
        if process.returncode == 0:
            status = "pass" if duration <= 300.0 else "partial"
        detail = f"exit={process.returncode}; {tail[-800:]}"
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - started
        status = "partial"
        detail = f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        duration = time.perf_counter() - started
        detail = f"{type(exc).__name__}: {exc}"
    rows.append(
        _row(
            "training",
            1,
            started_at,
            duration,
            1,
            0 if status == "pass" else 1,
            None,
            {"p50_ms": duration * 1000.0, "p95_ms": duration * 1000.0, "p99_ms": duration * 1000.0},
            "<= 300 s",
            status,
            detail,
        )
    )


def _run_inference(
    client: httpx.Client,
    rows: list[dict[str, Any]],
    *,
    requests: int,
) -> None:
    started_at = _iso()
    started = time.perf_counter()
    latencies: list[float] = []
    errors = 0
    statuses: dict[str, int] = {}
    for _ in range(requests):
        result = _call(
            client,
            "POST",
            "/v1/predict",
            json={"symbol": "BTCUSDT", "features": PREDICT_FEATURES},
        )
        latencies.append(float(result["elapsed_ms"]))
        if result["status"] != 200:
            errors += 1
            continue
        body = result.get("body") or {}
        key = str(body.get("status") or "unknown")
        statuses[key] = statuses.get(key, 0) + 1
    duration = time.perf_counter() - started
    summary = _summary(latencies)
    status = "pass" if errors == 0 and statuses.get("ok", 0) == requests else "partial"
    rows.append(
        _row(
            "inference",
            1,
            started_at,
            duration,
            requests,
            errors,
            requests / duration if duration else None,
            summary,
            "status=ok",
            status,
            f"statuses={statuses}; no champion yields not_available",
        )
    )


def _cadvisor_sample(client: httpx.Client) -> dict[str, float]:
    text = client.get("/metrics").text
    cpu = re.search(r'container_cpu_usage_seconds_total\{[^}]*id="/"[^}]*\}\s+([0-9.eE+-]+)', text)
    mem = re.search(r'container_memory_working_set_bytes\{[^}]*id="/"[^}]*\}\s+([0-9.eE+-]+)', text)
    if not cpu or not mem:
        raise RuntimeError("cAdvisor root CPU/memory metrics not found")
    return {
        "cpu_seconds": float(cpu.group(1)),
        "memory_bytes": float(mem.group(1)),
        "wall": time.perf_counter(),
    }


def _docker_stats() -> list[dict[str, str]]:
    try:
        process = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    resources: list[dict[str, str]] = []
    for line in (process.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        mem_usage, _, mem_limit = str(payload.get("MemUsage") or "").partition(" / ")
        resources.append(
            {
                "timestamp": _iso(),
                "container": str(payload.get("Name") or ""),
                "cpu_percent": str(payload.get("CPUPerc") or "").rstrip("%"),
                "mem_usage": mem_usage.strip(),
                "mem_limit": mem_limit.strip(),
                "net_io": str(payload.get("NetIO") or ""),
                "block_io": str(payload.get("BlockIO") or ""),
                "pids": str(payload.get("PIDs") or ""),
            }
        )
    return resources


def _run_cadvisor(
    rows: list[dict[str, Any]],
    resources: list[dict[str, str]],
    *,
    cadvisor_url: str,
) -> None:
    started_at = _iso()
    status = "partial"
    detail = ""
    try:
        with httpx.Client(
            base_url=cadvisor_url.rstrip("/"), timeout=10.0, trust_env=False
        ) as client:
            first = _cadvisor_sample(client)
            time.sleep(2.0)
            second = _cadvisor_sample(client)
        wall = second["wall"] - first["wall"]
        cpu_percent = ((second["cpu_seconds"] - first["cpu_seconds"]) / wall) * 100.0
        memory_mib = second["memory_bytes"] / (1024.0 * 1024.0)
        rows.append(
            _row(
                "cadvisor-host-cpu",
                1,
                started_at,
                wall,
                2,
                0,
                None,
                {"p50_ms": None, "p95_ms": None, "p99_ms": None},
                "resource sample",
                "pass",
                f"cpu_percent={cpu_percent:.3f}; source={cadvisor_url}",
            )
        )
        rows.append(
            _row(
                "cadvisor-host-memory",
                1,
                started_at,
                wall,
                2,
                0,
                None,
                {"p50_ms": None, "p95_ms": None, "p99_ms": None},
                "resource sample",
                "pass",
                f"memory_mib={memory_mib:.3f}; source={cadvisor_url}",
            )
        )
        status = "pass"
    except Exception as exc:  # noqa: BLE001 - fall back to docker stats
        detail = f"{type(exc).__name__}: {exc}; fallback=docker stats"
    docker_rows = _docker_stats()
    resources.extend(docker_rows)
    if status != "pass":
        rows.append(
            _row(
                "cadvisor",
                1,
                started_at,
                0.0,
                0,
                1,
                None,
                {"p50_ms": None, "p95_ms": None, "p99_ms": None},
                "resource sample",
                "partial",
                detail,
            )
        )


def _b2_rows(rows: list[dict[str, Any]]) -> None:
    started_at = _iso()
    try:
        from pyiceberg.expressions import EqualTo

        from bmip.common.config import get_settings
        from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

        settings = get_settings()
        catalog = load_rest_catalog(settings, "ml")
        table = table_with_host_io(catalog, settings, "gold.mart_market", "ml")
        scan_started = time.perf_counter()
        full = table.scan().to_arrow()
        full_ms = (time.perf_counter() - scan_started) * 1000.0
        event_dates = [row["event_date"] for row in full.to_pylist() if row.get("event_date")]
        latest = max(event_dates) if event_dates else None
        pruned_ms = 0.0
        pruned_rows = 0
        if latest is not None:
            scan_started = time.perf_counter()
            pruned = table.scan(row_filter=EqualTo("event_date", latest)).to_arrow()
            pruned_ms = (time.perf_counter() - scan_started) * 1000.0
            pruned_rows = pruned.num_rows
        detail = (
            f"full_rows={full.num_rows}; pruned_rows={pruned_rows}; "
            f"partition={latest}; dataset is small, result is indicative only"
        )
        rows.append(
            _row(
                "b2-before-full-scan",
                1,
                started_at,
                full_ms / 1000.0,
                1,
                0,
                None,
                {"p50_ms": full_ms, "p95_ms": full_ms, "p99_ms": full_ms},
                "before/after pair",
                "partial",
                detail,
            )
        )
        rows.append(
            _row(
                "b2-after-partition-pruned",
                1,
                started_at,
                pruned_ms / 1000.0,
                1,
                0,
                None,
                {"p50_ms": pruned_ms, "p95_ms": pruned_ms, "p99_ms": pruned_ms},
                "before/after pair",
                "partial",
                detail,
            )
        )
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        rows.append(
            _row(
                "b2-partition",
                1,
                started_at,
                0.0,
                1,
                1,
                None,
                {"p50_ms": None, "p95_ms": None, "p99_ms": None},
                "before/after pair",
                "partial",
                f"{type(exc).__name__}: {exc}",
            )
        )


def _last_stream_result(text: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    found: dict[str, Any] | None = None
    index = 0
    while True:
        index = text.find("{", index)
        if index < 0:
            return found or {}
        try:
            payload, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        if isinstance(payload, dict) and "stream" in payload:
            found = payload
        index += end


def _run_throughput(
    rows: list[dict[str, Any]],
    *,
    run: int,
    rate: int,
    duration: int,
    warmup: int,
    timeout: int,
) -> None:
    from confluent_kafka import Producer

    from bmip.common.config import get_settings
    from bmip.ingestion.kafka import ensure_topic

    settings = get_settings()
    brokers = _broker_address(settings.redpanda_brokers)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    topic = f"market.bench-{stamp}-{run}"
    group = f"bench-{stamp}-{run}"
    ensure_topic(brokers, topic)
    consumer_command = [
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
        "30",
        "--no-sink",
        "--no-metrics",
    ]
    consumer = subprocess.Popen(
        consumer_command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, REDPANDA_BROKERS=brokers),
    )
    started_at = _iso()
    started = time.perf_counter()
    window_start = started
    ack_latencies: list[float] = []
    errors: list[str] = []
    delivered = 0
    sent = 0
    base_id = int(time.time() * 1_000_000)
    base_ts = datetime.now(UTC) - timedelta(minutes=max(1, duration // 60))

    def callback(sent_at: float):
        def on_delivery(err: Any, _msg: Any) -> None:
            nonlocal delivered
            if err is not None:
                errors.append(str(err))
                return
            delivered += 1
            ack_latencies.append((time.perf_counter() - sent_at) * 1000.0)

        return on_delivery

    producer = Producer(
        {
            "bootstrap.servers": brokers,
            "broker.address.family": "v4",
            "acks": "all",
            "enable.idempotence": True,
            "linger.ms": 0,
            "batch.num.messages": 10000,
            "queue.buffering.max.messages": 200000,
            "message.timeout.ms": 30000,
        }
    )
    total = rate * duration
    warmup_total = rate * warmup
    try:
        for index in range(warmup_total + total):
            if index == warmup_total:
                producer.flush(30)
                ack_latencies.clear()
                delivered = 0
                window_start = time.perf_counter()
                started = window_start
            offset = index - warmup_total if index >= warmup_total else index
            target = window_start + (offset / rate)
            now = time.perf_counter()
            if now < target:
                time.sleep(min(target - now, 0.05))
            event_ts = base_ts + timedelta(microseconds=index)
            record = {
                "symbol": "BTCUSDT",
                "trade_id": base_id + index,
                "event_ts": _iso(event_ts),
                "price": f"{68000 + (index % 1000) * 0.01:.2f}",
                "qty": "0.01",
                "is_buyer_maker": False,
                "ingest_ts": _iso(),
                "source": "benchmark",
            }
            payload = json.dumps(record, separators=(",", ":")).encode("utf-8")
            while True:
                try:
                    producer.produce(
                        topic,
                        value=payload,
                        on_delivery=callback(time.perf_counter()),
                    )
                    producer.poll(0)
                    break
                except BufferError:
                    producer.poll(0.05)
            sent += 1
        producer.flush(60)
        elapsed = time.perf_counter() - started
        try:
            output, _ = consumer.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            consumer.kill()
            output, _ = consumer.communicate(timeout=10)
        result = _last_stream_result(output or "")
        stream = result.get("stream") or {}
        processed = int(stream.get("processed") or 0)
        summary = _summary(ack_latencies)
        actual_rate = delivered / elapsed if elapsed else 0.0
        status = (
            "pass"
            if not errors
            and delivered == total
            and processed >= total
            and actual_rate >= rate * 0.95
            else "partial"
        )
        detail = json.dumps(
            {
                "topic": topic,
                "group": group,
                "warmup_s": warmup,
                "target_rate": rate,
                "sent": sent,
                "delivered": delivered,
                "processed": processed,
                "processed_measured": max(0, processed - warmup_total),
                "errors": len(errors),
                "stream_exit": consumer.returncode,
                "stream": stream,
            },
            separators=(",", ":"),
        )
        rows.append(
            _row(
                "throughput-replay",
                run,
                started_at,
                elapsed,
                total,
                len(errors),
                actual_rate,
                summary,
                f">= {rate} trade/s",
                status,
                detail,
            )
        )
    except Exception as exc:  # noqa: BLE001 - evidence must record the failure
        elapsed = time.perf_counter() - started
        if consumer.poll() is None:
            consumer.kill()
        output, _ = consumer.communicate(timeout=10)
        rows.append(
            _row(
                "throughput-replay",
                run,
                started_at,
                elapsed,
                total,
                1,
                None,
                {"p50_ms": None, "p95_ms": None, "p99_ms": None},
                f">= {rate} trade/s",
                "fail",
                f"{type(exc).__name__}: {exc}; stream={_last_stream_result(output or '')}",
            )
        )


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: "" if row.get(field) is None else row.get(field) for field in fields}
            )


def _bottleneck(rows: list[dict[str, Any]]) -> str:
    candidates: list[tuple[float, str]] = []
    for row in rows:
        scenario = str(row["scenario"])
        if scenario.startswith("api-latest") and row.get("p95_ms"):
            candidates.append((float(row["p95_ms"]) / 300.0, f"{scenario} p95"))
        elif scenario.startswith("api-range") and row.get("p95_ms"):
            candidates.append((float(row["p95_ms"]) / 2000.0, f"{scenario} p95"))
        elif scenario.startswith("throughput") and row.get("throughput_per_s"):
            candidates.append(
                (1000.0 / max(float(row["throughput_per_s"]), 0.001), f"{scenario} throughput")
            )
        elif scenario.startswith("dq-runtime") and row.get("p95_ms"):
            candidates.append((float(row["p95_ms"]) / 120000.0, f"{scenario} runtime"))
        elif scenario.startswith("training") and row.get("p95_ms"):
            candidates.append((float(row["p95_ms"]) / 300000.0, f"{scenario} runtime"))
    partials = sorted(
        {str(row["scenario"]).split("-", 1)[0] for row in rows if row.get("status") == "partial"}
    )
    suffix = f" Partial blockers: {', '.join(partials)}." if partials else ""
    if not candidates:
        return (
            "No target-bearing benchmark row was produced; see partial rows for the blocker."
            + suffix
        )
    ratio, name = max(candidates, key=lambda item: item[0])
    if ratio <= 1.0:
        return (
            f"No measured target exceeded; closest row was {name} at {ratio:.2f}x its target."
            + suffix
        )
    return (
        f"Bottleneck: {name} is {ratio:.2f}x its target; "
        "inspect the row detail and resource sample." + suffix
    )


def _write_outputs(
    output_dir: Path,
    rows: list[dict[str, Any]],
    resources: list[dict[str, str]],
    *,
    commit: str,
    command: str,
) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "matrix.csv", FIELDS, rows)
    _write_csv(output_dir / "resources.csv", RESOURCE_FIELDS, resources)
    statuses = {str(row["status"]) for row in rows}
    overall = "fail" if "fail" in statuses else "partial" if "partial" in statuses else "pass"
    payload = {
        "id": EVIDENCE_ID,
        "timestamp": _iso(),
        "commit": commit,
        "command": command,
        "result": overall.upper(),
        "owner": OWNER,
        "rows": rows,
        "resources": resources,
    }
    (output_dir / "matrix.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    lines = [
        f"id        : {EVIDENCE_ID}",
        f"timestamp : {payload['timestamp']}",
        f"commit    : {commit}",
        f"command   : {command}",
        f"result    : {payload['result']}",
        f"owner     : {OWNER}",
        "",
        "| scenario | run | requests | errors | throughput/s | p50 ms | p95 ms | p99 ms | status |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]
    for row in rows:
        lines.append(
            "| {scenario} | {run} | {requests} | {errors} | {throughput_per_s} | "
            "{p50_ms} | {p95_ms} | {p99_ms} | {status} |".format(
                **{key: "" if row.get(key) is None else row.get(key) for key in FIELDS}
            )
        )
    lines.extend(
        [
            "",
            f"Bottleneck conclusion: {_bottleneck(rows)}",
            "",
            "Partial rows are expected when the champion registry is empty or gold has fewer "
            "than three labelled event dates; the detail column records the measured cause.",
            "",
            "Raw rows: `matrix.csv`, `matrix.json`; container samples: `resources.csv`.",
            "",
        ]
    )
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return overall


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W2-D benchmark matrix (T-42)")
    parser.add_argument(
        "--steps",
        default="api,dq,training,inference,cadvisor,b2,throughput",
        help="Comma-separated: api,dq,training,inference,cadvisor,b2,throughput",
    )
    parser.add_argument("--api-url", default=DEFAULT_API)
    parser.add_argument("--cadvisor-url", default=DEFAULT_CADVISOR)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=float, default=120.0, help="API warm-up seconds")
    parser.add_argument("--range-days", type=int, default=14)
    parser.add_argument("--rate", type=int, default=1000)
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--throughput-warmup", type=int, default=120)
    parser.add_argument("--throughput-repeats", type=int, default=3)
    parser.add_argument("--throughput-start-run", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--append", action="store_true", help="Append to an existing matrix.json")
    parser.add_argument("--smoke", action="store_true", help="Quick 10 second / 100 trade/s run")
    args = parser.parse_args(argv)

    if args.smoke:
        args.requests = 20
        args.repeats = 1
        args.warmup = 2.0
        args.rate = 100
        args.duration = 10
        args.throughput_warmup = 0
        args.throughput_repeats = 1
        args.throughput_start_run = 1

    steps = {step.strip() for step in args.steps.split(",") if step.strip()}
    from bmip.common.config import get_settings

    settings = get_settings()
    commit = _commit()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    rows: list[dict[str, Any]] = []
    resources: list[dict[str, str]] = []
    if args.append and (output_dir / "matrix.json").exists():
        existing = json.loads((output_dir / "matrix.json").read_text(encoding="utf-8"))
        rows.extend(existing.get("rows") or [])
        resources.extend(existing.get("resources") or [])
    client = _client(args.api_url, settings.api_key)
    try:
        if "api" in steps:
            _api_latest(
                client,
                rows,
                requests=args.requests,
                repeats=args.repeats,
                warmup=args.warmup,
            )
            _api_range(
                client,
                rows,
                requests=args.requests,
                repeats=args.repeats,
                range_days=args.range_days,
            )
        if "dq" in steps:
            _run_dq(rows, commit)
        if "training" in steps:
            _run_training(rows, args.timeout)
        if "inference" in steps:
            _run_inference(client, rows, requests=args.requests)
        if "cadvisor" in steps:
            _run_cadvisor(rows, resources, cadvisor_url=args.cadvisor_url)
        if "b2" in steps:
            _b2_rows(rows)
        if "throughput" in steps:
            for run in range(
                args.throughput_start_run,
                args.throughput_start_run + args.throughput_repeats,
            ):
                _run_throughput(
                    rows,
                    run=run,
                    rate=args.rate,
                    duration=args.duration,
                    warmup=args.throughput_warmup,
                    timeout=args.timeout,
                )
    finally:
        client.close()

    command = "python scripts/w2d_benchmark.py " + " ".join(sys.argv[1:])
    overall = _write_outputs(output_dir, rows, resources, commit=commit, command=command)
    try:
        output_label = str(output_dir.relative_to(ROOT))
    except ValueError:
        output_label = str(output_dir)
    print(
        json.dumps(
            {
                "id": EVIDENCE_ID,
                "result": overall.upper(),
                "rows": len(rows),
                "resources": len(resources),
                "output": output_label,
            },
            indent=2,
        )
    )
    return 0 if overall != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
