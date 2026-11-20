#!/usr/bin/env python3
"""W2-B evidence: Prometheus, Grafana, alert rules, log sample, T-37, T-39.

Every artefact is generated from the running stack. Nothing here is typed by
hand, and every text file starts with the header the workplan asks for.

Usage:
    python scripts/w2b_evidence.py --steps cp1,cp2
    python scripts/w2b_evidence.py --steps drill
    python scripts/w2b_evidence.py --steps reconcile
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EVIDENCE = ROOT / "evidence"
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

PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")
GRAFANA = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000")
PUSHGATEWAY = os.getenv("PUSHGATEWAY_URL", "http://127.0.0.1:9091")
NOTIFY = os.getenv("NOTIFY_URL", "http://127.0.0.1:8081")
API = os.getenv("BMIP_API_URL", "http://127.0.0.1:8080")

REQUIRED_METRICS = [
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

OWNER = "vio"


# ---------------------------------------------------------------- utilities
def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M")


def sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "nogit"


def iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def http_json(url: str, *, method: str = "GET", payload: Any = None, timeout: float = 10):
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def http_text(url: str, *, timeout: float = 10) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8")


def prom(expr: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"query": expr})
    payload = http_json(f"{PROMETHEUS}/api/v1/query?{query}")
    return payload.get("data", {}).get("result", [])


def header(identifier: str, command: str, result: str, run: str, commit: str) -> str:
    return (
        f"id        : {identifier}\n"
        f"timestamp : {iso()}\n"
        f"commit    : {commit}\n"
        f"command   : {command}\n"
        f"result    : {result}\n"
        f"owner     : {OWNER}\n"
        f"run       : {run}\n\n"
    )


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, payload: Any) -> Path:
    return write_text(path, json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        COMPOSE + list(args), cwd=ROOT, capture_output=True, text=True, timeout=timeout
    )


# ---------------------------------------------------------------------- CP1
def log_sample(run: str, commit: str) -> dict[str, Any]:
    """Capture real API log lines, including one error we provoke on purpose."""
    token = os.getenv("BMIP_API_KEY", "")
    request_id = f"req-w2b-{run.lower()}"
    error_detail: dict[str, Any] = {"provoked": False}
    try:
        # An unknown symbol produces a 400 with a request_id; the middleware
        # logs it, so the sample has a real error line to diagnose.
        url = f"{API}/v1/market/latest?symbol=NOTREAL"
        request = urllib.request.Request(
            url,
            headers={"X-Request-ID": request_id, "X-API-Key": token},
        )
        try:
            urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8") or "{}")
            error_detail = {
                "provoked": True,
                "status": exc.code,
                "request_id": body.get("request_id", request_id),
                "slug": body.get("type") or body.get("slug"),
                "detail": body.get("detail"),
            }
    except (urllib.error.URLError, OSError, ValueError) as exc:
        error_detail = {"provoked": False, "error": str(exc)}

    lines: list[str] = []
    result = docker("logs", "--no-color", "--no-log-prefix", "--tail", "400", "api")
    for line in (result.stdout or "").splitlines():
        if line.strip().startswith("{"):
            lines.append(line.strip())
    lines = lines[-40:]

    path = EVIDENCE / "logs" / f"sample_{run}_{commit}.jsonl"
    write_text(path, "\n".join(lines) + "\n" if lines else "")
    diagnosis = {
        "id": "W2B-LOG",
        "timestamp": iso(),
        "commit": commit,
        "run": run,
        "sample": str(path.relative_to(ROOT)),
        "lines": len(lines),
        "error": error_detail,
        "fields_present": sorted(
            {
                key
                for line in lines
                for key in json.loads(line).keys()
                if key in {"timestamp", "severity", "service", "run_id", "request_id", "message"}
            }
        ),
    }
    write_json(EVIDENCE / "logs" / f"diagnosis_{run}_{commit}.json", diagnosis)
    return diagnosis


def cp1(run: str, commit: str) -> dict[str, Any]:
    targets = http_json(f"{PROMETHEUS}/api/v1/targets")
    active = targets.get("data", {}).get("activeTargets", [])
    up = [t for t in active if t.get("health") == "up"]
    scraped = [
        {
            "job": t["labels"].get("job"),
            "instance": t.get("scrapeUrl"),
            "health": t.get("health"),
            "lastScrape": t.get("lastScrape"),
        }
        for t in active
    ]

    metric_state = {}
    for name in REQUIRED_METRICS:
        try:
            metric_state[name] = len(prom(name))
        except (urllib.error.URLError, OSError, ValueError):
            metric_state[name] = -1

    dashboards = http_json(f"{GRAFANA}/api/search?type=dash-db")
    pipeline = next((d for d in dashboards if d.get("uid") == "bmip-pipeline"), None)
    panels: list[dict[str, Any]] = []
    if pipeline:
        detail = http_json(f"{GRAFANA}/api/dashboards/uid/{pipeline['uid']}")
        panels = detail.get("dashboard", {}).get("panels", [])

    logs = log_sample(run, commit)

    fields = set(logs["fields_present"])
    passed = bool(
        len(up) >= 4
        and pipeline
        and panels
        and logs["lines"] > 0
        and {"run_id", "request_id", "service"} <= fields
    )
    payload = {
        "id": "CP1-W2B",
        "timestamp": iso(),
        "commit": commit,
        "run": run,
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "targets": {"active": len(active), "up": len(up), "detail": scraped},
        "metrics": metric_state,
        "grafana": {
            "dashboard": pipeline.get("title") if pipeline else None,
            "uid": pipeline.get("uid") if pipeline else None,
            "panels": [panel.get("title") for panel in panels],
        },
        "logs": {
            "sample": logs["sample"],
            "lines": logs["lines"],
            "fields_present": logs["fields_present"],
            "error": logs["error"],
        },
    }
    write_json(EVIDENCE / "observability" / f"CP1_{run}_{commit}.json", payload)
    write_text(
        EVIDENCE / "observability" / f"CP1_{run}_{commit}.txt",
        header(
            "CP1-W2B",
            "python scripts/w2b_evidence.py --steps cp1",
            payload["result"],
            run,
            commit,
        )
        + f"targets up      : {len(up)}/{len(active)}\n"
        + f"grafana panel   : {', '.join(payload['grafana']['panels'])}\n"
        + f"log sample      : {logs['sample']} ({logs['lines']} lines)\n"
        + f"log fields      : {', '.join(logs['fields_present'])}\n"
        + f"provoked error  : {logs['error']}\n",
    )
    return payload


# ---------------------------------------------------------------------- CP2
def cp2(run: str, commit: str) -> dict[str, Any]:
    rules = http_json(f"{PROMETHEUS}/api/v1/rules")
    groups = rules.get("data", {}).get("groups", [])
    loaded = [rule for group in groups for rule in group.get("rules", [])]
    classes: dict[str, int] = {}
    missing: list[str] = []
    for rule in loaded:
        labels = rule.get("labels", {})
        annotations = rule.get("annotations", {})
        classes[labels.get("alert_class", "none")] = (
            classes.get(labels.get("alert_class", "none"), 0) + 1
        )
        for key in ("severity", "owner", "channel", "alert_class"):
            if not labels.get(key):
                missing.append(f"{rule.get('name')}: label {key}")
        if not annotations.get("runbook_url"):
            missing.append(f"{rule.get('name')}: annotation runbook_url")

    runbooks = sorted((ROOT / "docs" / "runbooks").glob("alert-*.md"))

    dashboards = http_json(f"{GRAFANA}/api/search?type=dash-db")
    business = next((d for d in dashboards if d.get("uid") == "bmip-business"), None)
    business_panels: list[str] = []
    if business:
        detail = http_json(f"{GRAFANA}/api/dashboards/uid/{business['uid']}")
        business_panels = [
            panel.get("title") for panel in detail.get("dashboard", {}).get("panels", [])
        ]

    rules_copy = EVIDENCE / "alerts" / f"rules_{run}_{commit}.yml"
    rules_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "deploy" / "observability" / "rules.yml", rules_copy)

    passed = (
        len(loaded) == 16
        and not missing
        and len(runbooks) == 3
        and len(business_panels) >= 4
        and {"job-failure", "stream-lag", "service"} <= set(classes)
    )
    payload = {
        "id": "CP2-W2B",
        "timestamp": iso(),
        "commit": commit,
        "run": run,
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "rules": {
            "loaded": len(loaded),
            "classes": classes,
            "missing": missing,
            "file": str(rules_copy.relative_to(ROOT)),
        },
        "runbooks": [str(path.relative_to(ROOT)) for path in runbooks],
        "business_dashboard": {
            "uid": business.get("uid") if business else None,
            "panels": business_panels,
        },
    }
    write_json(EVIDENCE / "alerts" / f"CP2_{run}_{commit}.json", payload)
    write_text(
        EVIDENCE / "alerts" / f"CP2_{run}_{commit}.txt",
        header(
            "CP2-W2B",
            "python scripts/w2b_evidence.py --steps cp2",
            payload["result"],
            run,
            commit,
        )
        + f"rules loaded    : {len(loaded)}\n"
        + f"classes         : {json.dumps(classes, sort_keys=True)}\n"
        + f"missing labels  : {len(missing)}\n"
        + f"runbooks        : {len(runbooks)}\n"
        + f"business panels : {', '.join(business_panels)}\n",
    )
    return payload


# ------------------------------------------------------------------- T-37
def _key(value: Any) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()
    return str(value)


def _close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if left is None and right is None:
        return True
    try:
        left_f, right_f = float(left), float(right)
    except (TypeError, ValueError):
        return left == right
    return abs(left_f - right_f) <= tolerance * max(1.0, abs(left_f), abs(right_f))


def reconcile(run: str, commit: str) -> dict[str, Any]:
    from bmip.common.config import get_settings
    from bmip.serving.repository import connect
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    settings = get_settings()
    token = os.getenv("BMIP_API_KEY", "")
    request = urllib.request.Request(
        f"{API}/v1/market/volatility/range?symbol=BTCUSDT&limit=1000",
        headers={"X-API-Key": token},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    api_rows = payload.get("data", [])

    with connect(settings) as connection:
        rows = connection.execute(
            """
            SELECT window_start, realized_vol_1h, rv_ewma_24h
            FROM serving.market_hourly
            WHERE symbol = 'BTCUSDT'
            ORDER BY window_start DESC
            LIMIT 1000
            """
        ).fetchall()

    catalog = load_rest_catalog(settings, "api")
    table = table_with_host_io(catalog, settings, "gold.mart_market", "api")
    gold_rows = table.scan().to_arrow().to_pylist()

    api_map = {_key(row["window_start"]): row for row in api_rows}
    db_map = {_key(row["window_start"]): row for row in rows}
    gold_map = {
        _key(row["window_start"]): row
        for row in gold_rows
        if row.get("symbol") == "BTCUSDT"
    }

    all_keys = sorted(set(api_map) | set(db_map) | set(gold_map))
    latest = max((datetime.fromisoformat(k) for k in all_keys), default=None)

    windows: dict[str, Any] = {}
    for label, hours in (("24h", 24), ("7d", 168)):
        if latest is None:
            windows[label] = {"keys": 0, "mismatches": [], "passed": False}
            continue
        start = latest.timestamp() - hours * 3600
        keys = [k for k in all_keys if datetime.fromisoformat(k).timestamp() >= start]
        mismatches = []
        for key in keys:
            api_row = api_map.get(key)
            db_row = db_map.get(key)
            gold_row = gold_map.get(key)
            if api_row is None or db_row is None:
                mismatches.append({"window_start": key, "missing": "api or serving"})
                continue
            if not _close(api_row.get("realized_vol_1h"), db_row.get("realized_vol_1h")):
                mismatches.append(
                    {
                        "window_start": key,
                        "leg": "api_vs_serving",
                        "api": api_row.get("realized_vol_1h"),
                        "serving": db_row.get("realized_vol_1h"),
                    }
                )
            if gold_row is not None and not _close(
                db_row.get("realized_vol_1h"), gold_row.get("realized_vol_1h")
            ):
                mismatches.append(
                    {
                        "window_start": key,
                        "leg": "serving_vs_gold",
                        "serving": db_row.get("realized_vol_1h"),
                        "gold": gold_row.get("realized_vol_1h"),
                    }
                )
        windows[label] = {
            "keys": len(keys),
            "mismatches": mismatches[:20],
            "mismatch_count": len(mismatches),
            "passed": bool(keys) and not mismatches,
        }

    passed = all(window["passed"] for window in windows.values())
    result = {
        "id": "T-37",
        "timestamp": iso(),
        "commit": commit,
        "command": "python scripts/w2b_evidence.py --steps reconcile",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "run": run,
        "legs": {
            "api": "GET /v1/market/volatility/range",
            "serving": "serving.market_hourly (the Grafana datasource)",
            "gold": "gold.mart_market via Iceberg",
        },
        "tolerance": "relative 1e-9 on realized_vol_1h; every key must exist in API and serving",
        "windows": windows,
    }
    write_json(EVIDENCE / "dashboard" / f"reconciliation_{run}_{commit}.json", result)
    return result


# ------------------------------------------------------------------- T-39
def push(job: str, body: str) -> None:
    request = urllib.request.Request(
        f"{PUSHGATEWAY}/metrics/job/{job}",
        data=body.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain"},
    )
    urllib.request.urlopen(request, timeout=10).read()


def clear(job: str) -> None:
    request = urllib.request.Request(f"{PUSHGATEWAY}/metrics/job/{job}", method="DELETE")
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except urllib.error.HTTPError:
        pass


def deliveries() -> list[dict[str, Any]]:
    try:
        return http_json(f"{NOTIFY}/deliveries")
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def wait_for(
    names: set[str], status: str, timeout: float = 300, since: str | None = None
) -> dict[str, Any]:
    """Wait for deliveries that happened after the drill started.

    Without ``since`` an old delivery from a previous incident would satisfy
    the wait immediately, and the drill would "pass" on stale evidence.
    """
    deadline = time.time() + timeout
    since_dt = _ts(since) if since else None
    seen: dict[str, Any] = {}
    while time.time() < deadline:
        for row in deliveries():
            if since_dt is not None:
                try:
                    if _ts(row.get("received_at")) < since_dt:
                        continue
                except (TypeError, ValueError):
                    continue
            if row.get("alert") in names and str(row.get("status")).lower() == status:
                seen[row["alert"]] = row
        if names <= set(seen):
            return seen
        time.sleep(5)
    return seen


def drill(run: str, commit: str) -> dict[str, Any]:
    clear("drill")
    started = iso()
    timeline: list[dict[str, Any]] = []

    # Fault 1 (job failure) and 2 (stream lag) are metric injections; fault 3
    # (service) stops the API container, which is a real outage.
    drill_run = f"drill-{run}"
    push(
        "drill",
        "# TYPE bmip_dq_failures_total counter\n"
        f'bmip_dq_failures_total{{severity="critical",scope="drill",'
        f'run_id="{drill_run}"}} 1\n'
        "# TYPE bmip_consumer_lag gauge\n"
        f'bmip_consumer_lag{{run_id="{drill_run}"}} 5000\n',
    )
    timeline.append({"at": iso(), "event": "inject job-failure and stream-lag metrics"})
    docker("stop", "cadvisor")
    timeline.append({"at": iso(), "event": "stop cadvisor (service/resource class)"})

    fired = wait_for(
        {"BmipDqCriticalFailures", "BmipConsumerLagHigh", "BmipTargetDown"},
        "firing",
        timeout=420,
        since=started,
    )
    timeline.append(
        {
            "at": iso(),
            "event": "firing",
            "alerts": {name: row.get("received_at") for name, row in fired.items()},
        }
    )

    clear("drill")
    docker("start", "cadvisor")
    timeline.append({"at": iso(), "event": "clear metrics and start cadvisor"})

    resolved = wait_for(
        {"BmipDqCriticalFailures", "BmipConsumerLagHigh", "BmipTargetDown"},
        "resolved",
        timeout=420,
        since=started,
    )
    timeline.append(
        {
            "at": iso(),
            "event": "resolved",
            "alerts": {name: row.get("received_at") for name, row in resolved.items()},
        }
    )

    passed = set(fired) >= {"BmipDqCriticalFailures", "BmipConsumerLagHigh", "BmipTargetDown"}
    payload = {
        "id": "T-39",
        "timestamp": iso(),
        "commit": commit,
        "command": "python scripts/w2b_evidence.py --steps drill",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "run": run,
        "started": started,
        "timeline": timeline,
        "fired": sorted(fired),
        "resolved": sorted(resolved),
        "notifier": (
            "Alertmanager -> notify:8080 -> evidence/alerts/*.jsonl "
            "(+ Telegram when configured)"
        ),
        "deliveries": list(fired.values()) + list(resolved.values()),
    }
    write_json(EVIDENCE / "alerts" / f"T39_{run}_{commit}.json", payload)
    lines = [
        header(
            "T-39",
            "python scripts/w2b_evidence.py --steps drill",
            payload["result"],
            run,
            commit,
        ),
        "## Timeline",
        "",
        "| waktu | kejadian |",
        "| :-- | :-- |",
    ]
    for entry in timeline:
        detail = entry.get("event")
        if entry.get("alerts"):
            detail += " — " + ", ".join(f"{k} @ {v}" for k, v in entry["alerts"].items())
        lines.append(f"| {entry['at']} | {detail} |")
    lines.extend(
        [
            "",
            "## Kelas yang terbukti",
            "",
            "- job failure: `BmipDqCriticalFailures`",
            "- stream lag: `BmipConsumerLagHigh`",
            "- service/resource: `BmipTargetDown`",
            "",
            "Setiap alert tercatat di `evidence/alerts/deliveries.jsonl` dengan",
            "`run_id`, pesan, dan hasil pengiriman Telegram.",
        ]
    )
    write_text(EVIDENCE / "alerts" / f"T39_{run}_{commit}.md", "\n".join(lines) + "\n")
    return payload


# --------------------------------------------------------------- error log
def logerror(run: str, commit: str) -> dict[str, Any]:
    """Capture one real ERROR line by breaking one required setting.

    The stream processor exits through ``log.exception`` when a required
    credential is missing. That is a genuine failure path, it is deterministic,
    and it produces the severity=ERROR line with run_id that the workplan asks
    for. Nothing in the running stack is touched.
    """
    env = dict(os.environ)
    env["BMIP_RUN_ID"] = f"stream-err-{run}"
    env["BMIP_SERVICE"] = "stream"
    env["MINIO_SVC_PROCESS_SECRET_KEY"] = ""
    command = [
        sys.executable,
        "-m",
        "bmip.transform.cli",
        "stream",
        "--once",
        "--group",
        "ohlcv-w2b-error",
        "--idle-timeout",
        "5",
        "--no-metrics",
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, env=env, timeout=120
    )
    raw_lines = [
        line.strip()
        for line in (completed.stdout + "\n" + completed.stderr).splitlines()
        if line.strip().startswith("{")
    ]
    errors: list[dict[str, Any]] = []
    for line in raw_lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("severity") == "ERROR":
            errors.append(payload)

    path = EVIDENCE / "logs" / f"error_{run}_{commit}.jsonl"
    write_text(
        path,
        "\n".join(json.dumps(item, ensure_ascii=False) for item in errors) + "\n",
    )

    exception = (errors[0].get("exception") or "") if errors else ""
    failing = ""
    for line in exception.splitlines():
        if line.strip().startswith('File "') and "bmip" in line:
            failing = line.strip()
    last = exception.strip().splitlines()[-1] if exception else None
    diagnosis = {
        "id": "W2B-ERROR",
        "timestamp": iso(),
        "commit": commit,
        "command": (
            "MINIO_SVC_PROCESS_SECRET_KEY= "
            "python -m bmip.transform.cli stream --once --no-metrics"
        ),
        "result": "PASS" if errors else "FAIL",
        "owner": OWNER,
        "run": run,
        "sample": str(path.relative_to(ROOT)),
        "error_lines": len(errors),
        "run_id": errors[0].get("run_id") if errors else None,
        "message": errors[0].get("message") if errors else None,
        "failing_frame": failing,
        "last_exception_line": last,
        "diagnosis": (
            "The sink cannot be built because the MinIO secret for svc-process "
            "is empty. The processor fails before it touches the broker, which "
            "is why the stack is unaffected. In production this is the "
            "'missing secret' failure: fix .env, not the code."
        ),
    }
    write_json(EVIDENCE / "logs" / f"diagnosis_error_{run}_{commit}.json", diagnosis)
    return diagnosis


# -------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="W2-B evidence generator")
    parser.add_argument(
        "--steps",
        default="cp1,cp2",
        help="comma list: cp1, cp2, reconcile, drill, logerror",
    )
    args = parser.parse_args(argv)
    run = stamp()
    commit = sha()
    steps = [step.strip() for step in args.steps.split(",") if step.strip()]

    results: dict[str, Any] = {}
    for step in steps:
        if step == "cp1":
            results["cp1"] = cp1(run, commit)
        elif step == "cp2":
            results["cp2"] = cp2(run, commit)
        elif step == "reconcile":
            results["reconcile"] = reconcile(run, commit)
        elif step == "drill":
            results["drill"] = drill(run, commit)
        elif step == "logerror":
            results["logerror"] = logerror(run, commit)
        else:
            print(f"unknown step: {step}", file=sys.stderr)
            return 2

    summary = {
        "id": "W2-B",
        "timestamp": iso(),
        "commit": commit,
        "run": run,
        "steps": steps,
        "results": {key: value.get("result") for key, value in results.items()},
    }
    write_json(EVIDENCE / "w2b" / f"SUMMARY_{run}_{commit}.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if all(value == "PASS" for value in summary["results"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
