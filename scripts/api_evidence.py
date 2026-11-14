#!/usr/bin/env python3
"""Generate the W1-D evidence files (smoke, routes, T-13, T-14, T-15, T-34, T-36).

Every file is produced by calling the running API and the real database; none
are hand-written. ``--with-faults`` stops MinIO to prove the stale fallback and
runs the 1,000-row pagination check on the serving path, then restarts it.

Usage:
    python scripts/api_evidence.py --steps smoke,routes,auth,invalid,predict
    python scripts/api_evidence.py --steps pagination,stale,idempotence,reconcile --with-faults
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OWNER = "anin"
EVIDENCE = ROOT / "evidence"
BASE_URL = "http://localhost:8000"
DEFAULT_KEY = __import__("os").getenv("BMIP_API_KEY", "")
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
REQUIRED_STEPS = ("smoke", "routes", "auth", "invalid", "predict")
ALL_STEPS = (
    "smoke",
    "routes",
    "auth",
    "invalid",
    "predict",
    "pagination",
    "idempotence",
    "reconcile",
    "stale",
)


class StepFailed(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp() -> str:
    return _now().strftime("%Y%m%dT%H%M")


def _iso() -> str:
    return _now().isoformat(timespec="seconds").replace("+00:00", "Z")


def _commit() -> str:
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


def _write(relative: str, text: str) -> Path:
    path = EVIDENCE / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _write_json(relative: str, payload: Any) -> Path:
    return _write(relative, json.dumps(payload, indent=2, default=str) + "\n")


def _header(identifier: str, command: str, result: str, *, sha: str | None = None) -> str:
    return (
        f"id        : {identifier}\n"
        f"timestamp : {_iso()}\n"
        f"commit    : {sha or _commit()}\n"
        f"command   : {command}\n"
        f"result    : {result}\n"
        f"owner     : {OWNER}\n\n"
    )


def request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    key: str | None = DEFAULT_KEY,
    base_url: str = BASE_URL,
    timeout: float = 20.0,
) -> tuple[int, dict[str, str], Any, str]:
    query = ""
    if params:
        pairs = [
            f"{name}={urllib.parse.quote(str(value), safe='')}"
            for name, value in params.items()
            if value is not None
        ]
        if pairs:
            query = "?" + "&".join(pairs)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if key:
        headers["X-API-Key"] = key
    request_obj = urllib.request.Request(
        f"{base_url}{path}{query}", data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, _headers(response), _maybe_json(raw), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, _headers(exc), _maybe_json(raw), raw


def _headers(response) -> dict[str, str]:
    """Header names are case-insensitive; h11 delivers them lowercase."""
    return {name.lower(): value for name, value in response.headers.items()}


def _maybe_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail)


def step_smoke(ctx: dict[str, Any]) -> dict[str, Any]:
    checks: list[tuple[str, bool, str]] = []
    for name, path in (
        ("health/live", "/health/live"),
        ("health/ready", "/health/ready"),
        ("v1/meta/instance", "/v1/meta/instance"),
        ("v1/market/latest", "/v1/market/latest"),
        ("v1/market/volatility/latest", "/v1/market/volatility/latest"),
        ("v1/sentiment/latest", "/v1/sentiment/latest"),
        ("v1/freshness", "/v1/freshness"),
        ("v1/quality/status", "/v1/quality/status"),
        ("v1/model/latest", "/v1/model/latest"),
        ("v1/dataset", "/v1/dataset"),
    ):
        status, _, payload, raw = request("GET", path)
        ok = status == 200
        checks.append(_check(name, ok, f"HTTP {status}"))
        if not ok:
            ctx.setdefault("failures", []).append(f"{name}: HTTP {status} {raw[:200]}")

    status, headers, payload, _ = request("GET", "/v1/market/latest")
    if status == 200:
        data = payload.get("data")
        checks.append(
            _check("market/data", bool(data), "row present" if data else "no market row")
        )
        checks.append(
            _check(
                "market/freshness",
                bool(payload.get("meta", {}).get("freshness")),
                json.dumps(payload.get("meta", {}).get("freshness"), default=str),
            )
        )
        checks.append(
            _check(
                "market/request-id",
                headers.get("x-request-id", "").startswith("req-"),
                headers.get("x-request-id", ""),
            )
        )

    status, _, payload, _ = request("GET", "/v1/freshness")
    metrics = {row["metric"] for row in payload.get("data", [])} if status == 200 else set()
    checks.append(
        _check(
            "freshness/metrics",
            {"market", "sentiment"} <= metrics,
            f"metrics={sorted(metrics)}",
        )
    )

    passed = all(ok for _, ok, _ in checks)
    lines = [
        _header(
            "CP1-API",
            "python scripts/api_evidence.py --steps smoke",
            "PASS" if passed else "FAIL",
        ),
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    lines += [
        f"| `{name}` | {'PASS' if ok else 'FAIL'} | {detail} |"
        for name, ok, detail in checks
    ]
    path = _write(f"api/smoke_{_stamp()}.txt", "\n".join(lines) + "\n")
    return {"step": "smoke", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def step_routes(ctx: dict[str, Any]) -> dict[str, Any]:
    status, _, spec, _ = request("GET", "/openapi.json")
    if status != 200 or not isinstance(spec, dict):
        raise StepFailed(f"openapi.json returned HTTP {status}")
    canonical = [path for path in spec["paths"] if path.startswith("/v1/")]
    data_routes = [
        path
        for path in canonical
        if path
        not in {
            "/v1/market/ohlcv",
            "/v1/market/volatility",
            "/v1/sentiment/timeseries",
            "/v1/dq/results",
            "/v1/catalog/search",
        }
    ]
    (ROOT / "contracts" / "openapi.json").write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        _header(
            "API-ROUTES",
            "python scripts/api_evidence.py --steps routes",
            "PASS" if len(data_routes) >= 14 else "FAIL",
        ),
        f"Canonical /v1 routes: {len(data_routes)}",
        f"Alias routes: {len(canonical) - len(data_routes)}",
        "",
        "| Method | Path | Summary |",
        "|---|---|---|",
    ]
    for path in sorted(canonical):
        for method, operation in sorted(spec["paths"][path].items()):
            summary = operation.get("summary") or ""
            lines.append(f"| {method.upper()} | `{path}` | {summary} |")
    lines += ["", "openapi.json written to contracts/openapi.json"]
    path = _write(f"api/routes_{_stamp()}.txt", "\n".join(lines) + "\n")
    return {
        "step": "routes",
        "passed": len(data_routes) >= 14,
        "routes": len(data_routes),
        "aliases": len(canonical) - len(data_routes),
        "evidence": str(path.relative_to(ROOT)),
    }


def step_auth(ctx: dict[str, Any]) -> dict[str, Any]:
    cases = []
    status, headers, payload, _ = request("GET", "/v1/market/latest", key=None)
    cases.append(
        {
            "case": "no key",
            "path": "/v1/market/latest",
            "status": status,
            "content_type": headers.get("content-type", ""),
            "problem_type": payload.get("type") if isinstance(payload, dict) else None,
            "request_id": payload.get("request_id") if isinstance(payload, dict) else None,
            "pass": status == 401
            and str(headers.get("content-type", "")).startswith("application/problem+json"),
        }
    )
    status, _, payload, _ = request("GET", "/v1/market/latest", key="not-the-key")
    cases.append(
        {
            "case": "wrong key",
            "path": "/v1/market/latest",
            "status": status,
            "pass": status == 401,
        }
    )
    status, _, _, _ = request("POST", "/v1/predict", key=None, body={"symbol": "BTCUSDT"})
    cases.append(
        {
            "case": "no key on predict",
            "path": "/v1/predict",
            "status": status,
            "pass": status == 401,
        }
    )
    status, _, _, _ = request("GET", "/api", key=None)
    cases.append(
        {
            "case": "public discovery stays open",
            "path": "/api",
            "status": status,
            "pass": status == 200,
        }
    )
    passed = all(case["pass"] for case in cases)
    text = [
        _header(
            "T-13",
            "python scripts/api_evidence.py --steps auth",
            "PASS" if passed else "FAIL",
        ),
        "| Case | Path | HTTP | Pass |",
        "|---|---|---|---|",
    ]
    text += [
        f"| {case['case']} | `{case['path']}` | {case['status']} | {case['pass']} |"
        for case in cases
    ]
    text += ["", "Raw responses:", json.dumps(cases, indent=2)]
    path = _write("security/api-401.txt", "\n".join(text) + "\n")
    return {"step": "auth", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def step_invalid(ctx: dict[str, Any]) -> dict[str, Any]:
    cases = [
        ("unknown symbol", "/v1/market/latest", {"symbol": "ETHUSDT"}),
        (
            "from after to",
            "/v1/market/ohlc",
            {"symbol": "BTCUSDT", "from": "2026-11-16T00:00:00Z", "to": "2026-11-15T00:00:00Z"},
        ),
        ("limit zero", "/v1/market/ohlc", {"symbol": "BTCUSDT", "limit": 0}),
        ("limit over cap", "/v1/market/ohlc", {"symbol": "BTCUSDT", "limit": 5000}),
        ("broken cursor", "/v1/market/ohlc", {"symbol": "BTCUSDT", "cursor": "broken"}),
        ("bad datetime", "/v1/market/ohlc", {"symbol": "BTCUSDT", "from": "yesterday"}),
        ("range without bounds", "/v1/sentiment/range", {}),
    ]
    results = []
    for name, path, params in cases:
        status, headers, payload, _ = request("GET", path, params=params)
        results.append(
            {
                "case": name,
                "path": path,
                "params": params,
                "status": status,
                "content_type": headers.get("content-type", ""),
                "type": payload.get("type") if isinstance(payload, dict) else None,
                "request_id": payload.get("request_id") if isinstance(payload, dict) else None,
                "pass": status in (400, 422)
                and str(headers.get("content-type", "")).startswith("application/problem+json")
                and bool((payload or {}).get("request_id")),
            }
        )
    passed = all(item["pass"] for item in results)
    payload = {
        "id": "T-34",
        "timestamp": _iso(),
        "commit": _commit(),
        "command": "python scripts/api_evidence.py --steps invalid",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "cases": results,
    }
    path = _write_json("api/T34.json", payload)
    return {"step": "invalid", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def step_predict(ctx: dict[str, Any]) -> dict[str, Any]:
    cases = []
    status, headers, payload, _ = request(
        "POST",
        "/v1/predict",
        body={"symbol": "BTCUSDT", "features": {"rv_60m": "nan-ish"}},
    )
    cases.append(
        {
            "case": "malformed feature",
            "status": status,
            "content_type": headers.get("content-type", ""),
            "type": payload.get("type") if isinstance(payload, dict) else None,
            "pass": status == 422,
        }
    )
    status, _, payload, _ = request(
        "POST", "/v1/predict", body={"symbol": "BTCUSDT", "features": {"rv_60m": -1}}
    )
    cases.append(
        {
            "case": "out-of-range feature",
            "status": status,
            "status_field": payload.get("status") if isinstance(payload, dict) else None,
            "pass": status == 200
            and isinstance(payload, dict)
            and payload.get("status") == "error",
        }
    )
    status, _, payload, _ = request("POST", "/v1/predict", body={"symbol": "BTCUSDT"})
    cases.append(
        {
            "case": "valid payload, no champion",
            "status": status,
            "status_field": payload.get("status") if isinstance(payload, dict) else None,
            "detail": payload.get("detail") if isinstance(payload, dict) else None,
            "pass": status == 200
            and isinstance(payload, dict)
            and payload.get("status") in {"ok", "not_available"},
        }
    )
    passed = all(item["pass"] for item in cases)
    path = _write_json(
        "ml/T36.json",
        {
            "id": "T-36",
            "scope": "W1-D validation (final scoring is W2-A)",
            "timestamp": _iso(),
            "commit": _commit(),
            "command": "python scripts/api_evidence.py --steps predict",
            "result": "PASS" if passed else "FAIL",
            "owner": OWNER,
            "cases": cases,
        },
    )
    return {"step": "predict", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def step_pagination(ctx: dict[str, Any]) -> dict[str, Any]:
    """T-14: walk pages, prove no duplicates and no gaps.

    Real gold has only a handful of hourly rows, so the 1,000-row requirement
    is exercised on the serving path with a clearly labelled fixture that is
    deleted at the end. The real rows are always paged first.
    """
    for _ in range(3):
        status, headers, _, _ = request(
            "GET", "/v1/market/ohlc", params={"symbol": "BTCUSDT", "limit": 1}
        )
        if status == 200 and headers.get("x-data-source") == "lake":
            break
        time.sleep(1)

    live = _walk("/v1/market/ohlc", {"symbol": "BTCUSDT"}, limit=1)
    results = [{"mode": "live rows, limit=1", **live}]

    if ctx.get("with_faults"):
        fixture_rows = _insert_fixture(1000)
        try:
            _compose("stop", "minio")
            _wait_lake_down()
            serving = _walk(
                "/v1/market/ohlc",
                {"symbol": "BTCUSDT"},
                limit=100,
            )
            serving["expectation"] = {"min_rows": 1000, "min_pages": 10}
            serving["pass"] = (
                bool(serving.get("pass"))
                and serving["rows"] >= 1000
                and serving["pages"] >= 10
            )
            results.append({"mode": "1000-row fixture, limit=100", **serving})
        finally:
            _compose("start", "minio")
            _wait_minio_up()
            _delete_fixture()
        del fixture_rows

    passed = all(item["pass"] for item in results)
    lines = [
        _header(
            "T-14",
            "python scripts/api_evidence.py --steps pagination",
            "PASS" if passed else "FAIL",
        ),
        "Keyset pagination: every page is strictly older than the previous cursor.",
        "",
    ]
    for item in results:
        lines += [
            f"## {item['mode']}",
            f"pages        : {item['pages']}",
            f"rows         : {item['rows']}",
            f"unique rows  : {item['unique']}",
            f"duplicates   : {item['duplicates']}",
            f"cursor stable: {item['stable']}",
            f"result       : {'PASS' if item['pass'] else 'FAIL'}",
            "",
        ]
    live_files = [item["pages_detail"] for item in results]
    lines += ["## page detail", json.dumps(live_files, indent=2, default=str)]
    path = _write("tests/T14.txt", "\n".join(lines) + "\n")
    return {"step": "pagination", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def _walk(
    path: str,
    params: dict[str, Any],
    *,
    limit: int,
    key: str = "window_start",
) -> dict[str, Any]:
    seen: list[str] = []
    pages = 0
    detail: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        status, headers, payload, raw = request(
            "GET", path, params={**params, "limit": limit, "cursor": cursor}
        )
        if status != 200 or not isinstance(payload, dict):
            return {
                "pages": pages,
                "rows": len(seen),
                "unique": len(set(seen)),
                "duplicates": len(seen) - len(set(seen)),
                "stable": False,
                "pass": False,
                "error": f"HTTP {status}: {raw[:300]}",
                "pages_detail": detail,
            }
        rows = payload.get("data") or []
        seen.extend(str(row.get(key)) for row in rows)
        pages += 1
        cursor = (payload.get("meta") or {}).get("next_cursor")
        detail.append(
            {
                "page": pages,
                "rows": len(rows),
                "next_cursor": cursor,
                "first": rows[0].get(key) if rows else None,
                "last": rows[-1].get(key) if rows else None,
            }
        )
        if not cursor:
            break
        if pages > 200:
            break
    duplicates = len(seen) - len(set(seen))
    descending = all(left > right for left, right in zip(seen, seen[1:], strict=False))
    return {
        "pages": pages,
        "rows": len(seen),
        "unique": len(set(seen)),
        "duplicates": duplicates,
        "stable": descending and duplicates == 0,
        "pass": duplicates == 0 and descending and bool(seen),
        "pages_detail": detail,
    }


def _insert_fixture(count: int) -> int:
    from bmip.common.config import get_settings
    from bmip.serving.repository import connect

    start = datetime(2020, 1, 1, tzinfo=UTC)
    rows = [
        {
            "symbol": "BTCUSDT",
            "window_start": start + timedelta(hours=index),
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
            "quote_volume": 1,
            "trade_count": 1,
            "vwap": 1,
            "log_return_1h": 0.0,
            "realized_vol_1h": 0.0,
            "rv_ewma_24h": 0.0,
            "source": "t14_fixture",
            "event_date": (start + timedelta(hours=index)).date(),
            "updated_at": start,
        }
        for index in range(count)
    ]
    with connect(get_settings()) as connection:
        from bmip.serving.repository import ServingRepository

        ServingRepository(get_settings(), connection=connection).upsert_market_hourly(rows)
        stored = connection.execute(
            "SELECT count(*) AS n FROM serving.market_hourly WHERE source = 't14_fixture'"
        ).fetchone()
    return int(stored["n"])


def _delete_fixture() -> int:
    from bmip.common.config import get_settings
    from bmip.serving.repository import connect

    with connect(get_settings()) as connection:
        cursor = connection.execute(
            "DELETE FROM serving.market_hourly WHERE source = 't14_fixture'"
        )
        connection.commit()
    return cursor.rowcount or 0


def _compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], cwd=ROOT, check=True, timeout=180)


def _wait_minio_up(timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                "http://localhost:9000/minio/health/live", timeout=2
            ) as response:
                if response.status == 200:
                    time.sleep(2)
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    raise StepFailed("minio did not become healthy again")


def _wait_lake_down(timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _, payload, _ = request("GET", "/health/ready")
        if status == 200 and isinstance(payload, dict):
            if not payload.get("checks", {}).get("lake", True):
                return
        time.sleep(2)
    raise StepFailed("api did not report the lake path as down")


def step_stale(ctx: dict[str, Any]) -> dict[str, Any]:
    if not ctx.get("with_faults"):
        raise StepFailed("T-15 needs --with-faults because it stops MinIO")
    checks: list[dict[str, Any]] = []
    _compose("stop", "minio")
    try:
        _wait_lake_down()
        for path, params in (
            ("/v1/market/volatility/range", {"symbol": "BTCUSDT", "limit": 5}),
            ("/v1/sentiment/hourly", {"limit": 5}),
            ("/v1/market/ohlc", {"symbol": "BTCUSDT", "limit": 5}),
        ):
            status, headers, payload, raw = request("GET", path, params=params)
            checks.append(
                {
                    "path": path,
                    "status": status,
                    "x_data_stale": headers.get("x-data-stale"),
                    "x_data_source": headers.get("x-data-source"),
                    "meta_source": (payload.get("meta") or {}).get("source")
                    if isinstance(payload, dict)
                    else None,
                    "rows": len(payload.get("data") or []) if isinstance(payload, dict) else 0,
                    "pass": status == 200
                    and headers.get("x-data-stale") == "true"
                    and (payload.get("meta") or {}).get("source") == "serving",
                    "error": raw[:200] if status != 200 else None,
                }
            )
    finally:
        _compose("start", "minio")
        _wait_minio_up()
    recovery = {"path": "/v1/market/ohlc (after recovery)", "pass": False}
    for _ in range(6):
        status, headers, _, _ = request(
            "GET", "/v1/market/ohlc", params={"symbol": "BTCUSDT"}
        )
        recovery.update(
            {
                "status": status,
                "x_data_stale": headers.get("x-data-stale"),
                "x_data_source": headers.get("x-data-source"),
            }
        )
        if status == 200 and headers.get("x-data-stale") == "false":
            recovery["pass"] = True
            break
        time.sleep(3)
    checks.append(recovery)
    passed = all(check["pass"] for check in checks)
    lines = [
        _header(
            "T-15",
            "python scripts/api_evidence.py --steps stale --with-faults",
            "PASS" if passed else "FAIL",
        ),
        "Fault: MinIO stopped, range queries must answer 200 from PostgreSQL",
        "with X-Data-Stale: true and meta.source = serving.",
        "",
        "| Path | HTTP | X-Data-Stale | meta.source | Rows | Pass |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| `{check['path']}` | {check['status']} | {check.get('x_data_stale')} | "
        f"{check.get('meta_source')} | {check.get('rows', '')} | {check['pass']} |"
        for check in checks
    ]
    lines += ["", json.dumps(checks, indent=2, default=str)]
    path = _write("tests/T15.txt", "\n".join(lines) + "\n")
    return {"step": "stale", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def step_idempotence(ctx: dict[str, Any]) -> dict[str, Any]:
    first = _run_loader()
    second = _run_loader()
    counts_equal = first["counts"] == second["counts"]
    hash_equal = first["logical_hash"] == second["logical_hash"]
    passed = counts_equal and hash_equal and bool(first["logical_hash"])
    payload = {
        "id": "SERVING-IDEMPOTENCE",
        "timestamp": _iso(),
        "commit": _commit(),
        "command": "python scripts/serve_load.py (twice)",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "counts_equal": counts_equal,
        "hash_equal": hash_equal,
        "first": first,
        "second": second,
    }
    path = _write_json(f"serving/loader-idempotence_{_stamp()}.json", payload)
    return {"step": "idempotence", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def _run_loader() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "scripts/serve_load.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    if result.returncode != 0:
        raise StepFailed(f"serve_load failed: {result.stderr[-500:]}")
    return json.loads(result.stdout)


def step_reconcile(ctx: dict[str, Any]) -> dict[str, Any]:
    from bmip.common.config import get_settings
    from bmip.serving.repository import connect
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    settings = get_settings()
    status, _, payload, _ = request(
        "GET", "/v1/market/volatility/range", params={"symbol": "BTCUSDT", "limit": 1000}
    )
    api_rows = payload.get("data", []) if status == 200 else []
    api_map = {_key(row["window_start"]): row for row in api_rows}

    with connect(settings) as connection:
        db_rows = connection.execute(
            """
            SELECT window_start, realized_vol_1h, rv_ewma_24h
            FROM serving.market_hourly
            WHERE symbol = %s
            ORDER BY window_start DESC
            LIMIT 1000
            """,
            ("BTCUSDT",),
        ).fetchall()
    db_map = {_key(row["window_start"]): row for row in db_rows}

    catalog = load_rest_catalog(settings, "api")
    table = table_with_host_io(catalog, settings, "gold.mart_market", "api")
    gold_rows = table.scan().to_arrow().to_pylist()
    gold_map = {
        _key(row["window_start"]): row
        for row in gold_rows
        if row["symbol"] == "BTCUSDT"
    }

    common = sorted(set(api_map) & set(db_map), reverse=True)
    mismatches = [
        {
            "window_start": key,
            "api": api_map[key].get("realized_vol_1h"),
            "serving": db_map[key].get("realized_vol_1h"),
        }
        for key in common
        if not _close(api_map[key].get("realized_vol_1h"), db_map[key].get("realized_vol_1h"))
    ]
    gold_common = sorted(set(db_map) & set(gold_map), reverse=True)
    gold_mismatch = [
        {
            "window_start": key,
            "serving": db_map[key].get("realized_vol_1h"),
            "gold": gold_map[key].get("realized_vol_1h"),
        }
        for key in gold_common
        if not _close(db_map[key].get("realized_vol_1h"), gold_map[key].get("realized_vol_1h"))
    ]
    passed = bool(common) and not mismatches and not gold_mismatch
    result = {
        "id": "T-37-W1D",
        "scope": "draft (final in W2-B)",
        "timestamp": _iso(),
        "commit": _commit(),
        "command": "python scripts/api_evidence.py --steps reconcile",
        "result": "PASS" if passed else "FAIL",
        "owner": OWNER,
        "range": {
            "window_start_min": common[-1] if common else None,
            "window_start_max": common[0] if common else None,
        },
        "counts": {
            "api": len(api_map),
            "serving": len(db_map),
            "gold": len(gold_map),
            "common_api_serving": len(common),
            "common_serving_gold": len(gold_common),
        },
        "mismatches_api_vs_serving": mismatches[:20],
        "mismatches_serving_vs_gold": gold_mismatch[:20],
        "tolerance": "relative 1e-9",
        "dashboard_note": (
            "The Streamlit page renders these same API payloads; the screenshot "
            "is evidence/dashboards/streamlit_<ts>.png."
        ),
    }
    path = _write_json("dashboard/reconciliation-draft.json", result)
    return {"step": "reconcile", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def _key(value: Any) -> str:
    """Normalise a timestamp so API strings and psycopg datetimes compare."""
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
        left_f = float(left)
        right_f = float(right)
    except (TypeError, ValueError):
        return left == right
    scale = max(abs(left_f), abs(right_f), 1.0)
    return abs(left_f - right_f) / scale <= tolerance


def main(argv: list[str] | None = None) -> int:
    global BASE_URL, DEFAULT_KEY

    parser = argparse.ArgumentParser(description="Generate W1-D API evidence")
    parser.add_argument("--steps", default=",".join(REQUIRED_STEPS))
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_KEY)
    parser.add_argument("--with-faults", action="store_true")
    args = parser.parse_args(argv)

    BASE_URL = args.base_url.rstrip("/")
    DEFAULT_KEY = args.api_key

    steps = [step.strip() for step in args.steps.split(",") if step.strip()]
    unknown = [step for step in steps if step not in ALL_STEPS]
    if unknown:
        parser.error(f"unknown steps: {unknown}")

    ctx: dict[str, Any] = {"with_faults": args.with_faults, "failures": []}
    handlers = {
        "smoke": step_smoke,
        "routes": step_routes,
        "auth": step_auth,
        "invalid": step_invalid,
        "predict": step_predict,
        "pagination": step_pagination,
        "stale": step_stale,
        "idempotence": step_idempotence,
        "reconcile": step_reconcile,
    }
    results: list[dict[str, Any]] = []
    for step in steps:
        started = time.time()
        try:
            outcome = handlers[step](ctx)
            outcome["duration_seconds"] = round(time.time() - started, 2)
        except Exception as exc:  # noqa: BLE001 - evidence must record a failure
            outcome = {
                "step": step,
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_seconds": round(time.time() - started, 2),
            }
        results.append(outcome)
        print(json.dumps(outcome, default=str))

    passed = all(result.get("passed") for result in results)
    print(
        json.dumps(
            {"result": "PASS" if passed else "FAIL", "steps": results},
            indent=2,
            default=str,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
