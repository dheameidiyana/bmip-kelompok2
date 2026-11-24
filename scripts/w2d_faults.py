#!/usr/bin/env python3
"""W2-D fault injection: kill the stream processor and stop MinIO.

Both scenarios are executed against the running stack. The stream scenario
publishes duplicate trade keys, kills the consumer mid-flight, restarts the same
group, and verifies that silver has exactly one row per trade. The MinIO
scenario stops object storage, verifies the API stale fallback, restarts MinIO,
and measures recovery time.

Usage:
    python scripts/w2d_faults.py
    python scripts/w2d_faults.py --only stream --records 100
    python scripts/w2d_faults.py --only minio
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from bmip.common.config import Settings, get_settings
from bmip.ingestion.kafka import ensure_topic, publish_market_trades
from bmip.transform.silver import SilverWriter
from bmip.transform.stream import group_lag

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OWNER = "lois"
EVIDENCE = ROOT / "evidence" / "faults"
BASE_URL = "http://localhost:8000"
API_KEY = os.getenv("BMIP_API_KEY", "")
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    ".env",
    "-f",
    "deploy/compose.base.yml",
    "-f",
    "deploy/compose.dev.yml",
]
STALE_PATHS = (
    ("/v1/market/volatility/range", {"symbol": "BTCUSDT", "limit": 5}),
    ("/v1/sentiment/hourly", {"limit": 5}),
    ("/v1/market/ohlc", {"symbol": "BTCUSDT", "limit": 5}),
)


def iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat(timespec="seconds").replace("+00:00", "Z")


def stamp(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def write_text(name: str, text: str) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(text, encoding="utf-8")
    return path


def write_json(name: str, payload: Any) -> Path:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE / name
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def compose(*args: str) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        [*COMPOSE, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
        check=False,
    )
    return {
        "command": " ".join([*COMPOSE, *args]),
        "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 2),
        "output": (result.stdout + result.stderr).strip()[-4000:],
    }


def request(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], Any, float]:
    query = ""
    if params:
        pairs = [f"{key}={value}" for key, value in params.items() if value is not None]
        if pairs:
            query = "?" + "&".join(pairs)
    headers = {"Accept": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    req = urllib.request.Request(f"{BASE_URL}{path}{query}", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return (
                response.status,
                {name.lower(): value for name, value in response.headers.items()},
                maybe_json(raw),
                time.monotonic() - started,
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return (
            exc.code,
            {name.lower(): value for name, value in exc.headers.items()},
            maybe_json(raw),
            time.monotonic() - started,
        )


def maybe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def wait_lake_down(timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, _, payload, elapsed = request("/health/ready")
        last = {"status": status, "payload": payload, "elapsed": elapsed}
        if status == 200 and isinstance(payload, dict):
            if payload.get("checks", {}).get("lake") is False:
                return last
        time.sleep(2)
    raise TimeoutError(f"lake path did not report down: {last}")


def wait_minio_up(timeout: float = 120.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open("http://localhost:9000/minio/health/live", timeout=2) as response:
                if response.status == 200:
                    time.sleep(2)
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    raise TimeoutError("minio did not become healthy again")


def wait_lake_up(timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, _, payload, elapsed = request("/health/ready")
        last = {"status": status, "payload": payload, "elapsed": elapsed}
        if status == 200 and isinstance(payload, dict):
            if payload.get("checks", {}).get("lake") is True:
                return last
        time.sleep(2)
    raise TimeoutError(f"lake path did not recover: {last}")


def wait_not_stale(timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, headers, _, elapsed = request(
            "/v1/market/ohlc", params={"symbol": "BTCUSDT", "limit": 5}
        )
        last = {
            "status": status,
            "x_data_stale": headers.get("x-data-stale"),
            "elapsed": elapsed,
        }
        if status == 200 and headers.get("x-data-stale") == "false":
            return last
        time.sleep(3)
    raise TimeoutError(f"api stayed stale: {last}")


def stream_command(
    group: str,
    topic: str,
    *,
    follow: bool,
    idle_timeout: float = 30.0,
    max_records: int | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "bmip.transform.cli",
        "stream",
        "--group",
        group,
        "--topic",
        topic,
        "--no-metrics",
    ]
    if follow:
        command.append("--follow")
    else:
        command.extend(["--once", "--idle-timeout", str(idle_timeout)])
        if max_records is not None:
            command.extend(["--max-records", str(max_records)])
    return command


def wait_group_empty(group: str, timeout: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "redpanda",
                "rpk",
                "group",
                "describe",
                group,
                "--format",
                "json",
                "--brokers",
                "redpanda:9092",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                row = payload[0] if isinstance(payload, list) and payload else payload
                if isinstance(row, dict):
                    last = row
                    if row.get("members") == 0 and row.get("state") in {"Empty", "Dead"}:
                        return row
            except json.JSONDecodeError:
                last = {"stdout": result.stdout[-500:], "stderr": result.stderr[-500:]}
        time.sleep(2)
    return last


def parse_stream_result(text: str) -> dict[str, Any] | None:
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
        if isinstance(payload, dict) and "stream" in payload:
            return payload["stream"]
        index += end


def read_group_lag(settings: Settings, group: str, topic: str) -> dict[str, Any]:
    last: Exception | None = None
    for _ in range(5):
        try:
            return group_lag(settings, group, topic)
        except Exception as exc:  # noqa: BLE001 - coordinator may still be settling
            last = exc
            time.sleep(3)
    assert last is not None
    raise last


def make_records(count: int, now: datetime) -> list[dict[str, Any]]:
    base_id = int(now.timestamp() * 1_000_000)
    event = now - timedelta(seconds=15)
    return [
        {
            "symbol": "BTCUSDT",
            "trade_id": base_id + index,
            "event_ts": iso(event + timedelta(milliseconds=index)),
            "price": f"{68000 + index % 50}.50",
            "qty": "0.01",
            "is_buyer_maker": False,
            "ingest_ts": iso(now),
            "source": "w2d_fault",
        }
        for index in range(count)
    ]


def stream_fault(settings: Settings, records: list[dict[str, Any]]) -> dict[str, Any]:
    started = datetime.now(UTC)
    name = f"stream-kill_{stamp(started)}"
    topic = f"market.w2d-fault-{stamp(started)}"
    group = f"w2d-fault-{stamp(started)}"
    expected_ids = {int(record["trade_id"]) for record in records}
    event_date: date = datetime.fromisoformat(records[0]["event_ts"].replace("Z", "+00:00")).date()
    messages = [record for record in records for _ in range(2)]

    process: subprocess.Popen[str] | None = None
    payload: dict[str, Any] = {
        "id": "W2D-FAULT-STREAM",
        "scenario": "kill stream processor",
        "timestamp": iso(started),
        "commit": commit(),
        "owner": OWNER,
        "topic": topic,
        "group": group,
        "unique_trades": len(records),
        "published_messages": len(messages),
        "command": "python scripts/w2d_faults.py --only stream",
        "result": "FAIL",
    }
    try:
        ensure_topic(settings.redpanda_brokers, topic)
        process = subprocess.Popen(
            stream_command(group, topic, follow=True),
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        payload["consumer_started_at"] = iso()
        time.sleep(8)
        published = publish_market_trades(settings.redpanda_brokers, topic, messages)
        payload["published"] = published
        payload["published_at"] = iso()
        time.sleep(0.4)
        kill_started = time.monotonic()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        payload["killed_at"] = iso()
        payload["kill_exit_code"] = process.returncode
        payload["kill_seconds"] = round(time.monotonic() - kill_started, 2)

        coordination_started = time.monotonic()
        payload["group_after_kill"] = wait_group_empty(group)
        payload["coordination_wait_seconds"] = round(time.monotonic() - coordination_started, 2)

        restarted_at = time.monotonic()
        payload["restarted_at"] = iso()
        restart = subprocess.run(
            stream_command(
                group,
                topic,
                follow=False,
                idle_timeout=30,
                max_records=len(messages),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            timeout=240,
            check=False,
        )
        drained_at = time.monotonic()
        payload["drained_at"] = iso()
        payload["restart_exit_code"] = restart.returncode
        payload["restart_seconds"] = round(drained_at - restarted_at, 2)
        payload["rto_seconds"] = round(drained_at - kill_started, 2)
        payload["restart_result"] = parse_stream_result(restart.stdout)
        payload["restart_output_tail"] = (restart.stdout + restart.stderr)[-3000:]

        try:
            lag = read_group_lag(settings, group, topic)
            payload["final_lag"] = lag["total_lag"]
        except Exception as exc:  # noqa: BLE001 - fall back to the restart result
            payload["lag_error"] = f"{type(exc).__name__}: {exc}"
            lag = {"total_lag": (payload.get("restart_result") or {}).get("lag")}
            payload["final_lag"] = lag["total_lag"]
        writer = SilverWriter(settings)
        rows = writer.fetch_trades("BTCUSDT", event_date)
        matched = [row for row in rows if int(row["trade_id"]) in expected_ids]
        found_ids = [int(row["trade_id"]) for row in matched]
        payload["silver_rows"] = len(found_ids)
        payload["silver_unique"] = len(set(found_ids))
        payload["silver_duplicates"] = len(found_ids) - len(set(found_ids))
        payload["missing_ids"] = sorted(expected_ids - set(found_ids))
        payload["event_date"] = str(event_date)

        passed = (
            published == len(messages)
            and restart.returncode == 0
            and lag["total_lag"] == 0
            and not payload["missing_ids"]
            and payload["silver_duplicates"] == 0
            and len(found_ids) == len(expected_ids)
        )
        payload["result"] = "PASS" if passed else "FAIL"
    except Exception as exc:  # noqa: BLE001 - evidence must record failures
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    lines = [
        f"id        : {payload['id']}",
        f"timestamp : {payload['timestamp']}",
        f"commit    : {payload['commit']}",
        f"command   : {payload['command']}",
        f"result    : {payload['result']}",
        f"owner     : {payload['owner']}",
        "",
        f"topic              : {topic}",
        f"group              : {group}",
        f"unique_trades      : {payload['unique_trades']}",
        f"published_messages : {payload.get('published')}",
        f"silver_rows        : {payload.get('silver_rows')}",
        f"silver_unique      : {payload.get('silver_unique')}",
        f"silver_duplicates  : {payload.get('silver_duplicates')}",
        f"missing_ids        : {payload.get('missing_ids')}",
        f"final_lag          : {payload.get('final_lag')}",
        f"kill_exit_code     : {payload.get('kill_exit_code')}",
        f"coordination_wait  : {payload.get('coordination_wait_seconds')}",
        f"restart_exit_code  : {payload.get('restart_exit_code')}",
        f"rto_seconds        : {payload.get('rto_seconds')}",
        f"error              : {payload.get('error')}",
        "",
        "=== payload ===",
        json.dumps(payload, indent=2, default=str),
    ]
    write_text(f"{name}.txt", "\n".join(lines) + "\n")
    write_json(f"{name}.json", payload)
    return payload


def minio_fault() -> dict[str, Any]:
    started = datetime.now(UTC)
    name = f"minio-kill_{stamp(started)}"
    payload: dict[str, Any] = {
        "id": "W2D-FAULT-MINIO",
        "scenario": "stop MinIO",
        "timestamp": iso(started),
        "commit": commit(),
        "owner": OWNER,
        "command": "python scripts/w2d_faults.py --only minio",
        "result": "FAIL",
    }
    checks: list[dict[str, Any]] = []
    try:
        status, headers, _, elapsed = request(
            "/v1/market/ohlc", params={"symbol": "BTCUSDT", "limit": 5}
        )
        payload["before"] = {
            "status": status,
            "x_data_stale": headers.get("x-data-stale"),
            "elapsed_seconds": round(elapsed, 3),
        }

        outage_started = time.monotonic()
        payload["stopped_at"] = iso()
        payload["stop"] = compose("stop", "minio")
        down = wait_lake_down()
        degraded_at = time.monotonic()
        payload["degraded_at"] = iso()
        payload["degraded_latency_seconds"] = round(degraded_at - outage_started, 2)
        payload["lake_down"] = down

        for path, params in STALE_PATHS:
            status, headers, body, elapsed = request(path, params=params)
            meta = body.get("meta", {}) if isinstance(body, dict) else {}
            checks.append(
                {
                    "path": path,
                    "status": status,
                    "x_data_stale": headers.get("x-data-stale"),
                    "x_data_source": headers.get("x-data-source"),
                    "meta_source": meta.get("source"),
                    "rows": len(body.get("data") or []) if isinstance(body, dict) else 0,
                    "elapsed_seconds": round(elapsed, 3),
                    "pass": status == 200
                    and headers.get("x-data-stale") == "true"
                    and meta.get("source") == "serving",
                }
            )
        payload["fallback_checks"] = checks

        payload["started_at"] = iso()
        payload["start"] = compose("start", "minio")
        wait_minio_up()
        payload["minio_up_at"] = iso()
        payload["lake_up"] = wait_lake_up()
        recovery = wait_not_stale()
        recovered_at = time.monotonic()
        payload["recovered_at"] = iso()
        payload["recovery"] = recovery
        payload["rto_seconds"] = round(recovered_at - outage_started, 2)
        payload["degraded_seconds"] = round(recovered_at - degraded_at, 2)

        passed = (
            payload["before"]["status"] == 200
            and payload["before"]["x_data_stale"] == "false"
            and all(check["pass"] for check in checks)
            and recovery["status"] == 200
            and recovery["x_data_stale"] == "false"
        )
        payload["result"] = "PASS" if passed else "FAIL"
    except Exception as exc:  # noqa: BLE001 - evidence must record failures
        payload["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if payload.get("result") != "PASS":
            payload["cleanup"] = compose("start", "minio")
            try:
                wait_minio_up(timeout=90)
            except Exception as exc:  # noqa: BLE001 - best effort cleanup
                payload["cleanup_error"] = str(exc)

    lines = [
        f"id        : {payload['id']}",
        f"timestamp : {payload['timestamp']}",
        f"commit    : {payload['commit']}",
        f"command   : {payload['command']}",
        f"result    : {payload['result']}",
        f"owner     : {payload['owner']}",
        "",
        f"stopped_at             : {payload.get('stopped_at')}",
        f"degraded_at            : {payload.get('degraded_at')}",
        f"degraded_latency_secs  : {payload.get('degraded_latency_seconds')}",
        f"recovered_at           : {payload.get('recovered_at')}",
        f"rto_seconds            : {payload.get('rto_seconds')}",
        f"degraded_seconds       : {payload.get('degraded_seconds')}",
        f"error                  : {payload.get('error')}",
        "",
        "| Path | HTTP | X-Data-Stale | meta.source | Rows | Pass |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| `{check['path']}` | {check['status']} | {check['x_data_stale']} | "
        f"{check['meta_source']} | {check['rows']} | {check['pass']} |"
        for check in checks
    ]
    lines += ["", "=== payload ===", json.dumps(payload, indent=2, default=str)]
    write_text(f"{name}.txt", "\n".join(lines) + "\n")
    write_json(f"{name}.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W2-D fault injection")
    parser.add_argument("--only", choices=("stream", "minio"), default=None)
    parser.add_argument("--records", type=int, default=100)
    args = parser.parse_args(argv)

    settings = get_settings()
    results: list[dict[str, Any]] = []
    if args.only in (None, "stream"):
        records = make_records(args.records, datetime.now(UTC))
        results.append(stream_fault(settings, records))
    if args.only in (None, "minio"):
        results.append(minio_fault())

    passed = bool(results) and all(item.get("result") == "PASS" for item in results)
    summary = {
        "id": "W2D-FAULTS",
        "timestamp": iso(),
        "commit": commit(),
        "owner": OWNER,
        "result": "PASS" if passed else "FAIL",
        "scenarios": results,
    }
    write_json(f"faults_{stamp()}.json", summary)
    print(json.dumps(summary, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
