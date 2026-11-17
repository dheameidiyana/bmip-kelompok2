#!/usr/bin/env python3
"""M1 gate: one trade and one post from bronze to API to dashboard (W1-D).

Prints a table and writes evidence/e2e/M1_<ts>.txt. Fails when a layer is
missing or the API/dashboard cannot serve it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

OWNER = "anin"
EVIDENCE = ROOT / "evidence"
API = "http://localhost:8000"
DASHBOARD = "http://localhost:8501"
TRAEFIK = "http://localhost:8080"


def _iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M")


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


def _http(
    url: str, *, key: str | None = None, timeout: float = 10.0
) -> tuple[int, str, dict[str, str]]:
    headers = {"X-API-Key": key} if key else {}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace"), dict(
                response.headers
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace"), dict(exc.headers)
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc), {}


def _json(url: str, key: str | None) -> tuple[int, Any, dict[str, str]]:
    status, body, headers = _http(url, key=key)
    try:
        return status, json.loads(body), headers
    except json.JSONDecodeError:
        return status, body, headers


def _counts(service: str, tables: tuple[str, ...]) -> dict[str, int]:
    from bmip.common.config import get_settings
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    settings = get_settings()
    catalog = load_rest_catalog(settings, service)
    counts: dict[str, int] = {}
    for identifier in tables:
        try:
            table = table_with_host_io(catalog, settings, identifier, service)
            counts[identifier] = int(table.scan().to_arrow().num_rows)
        except Exception as exc:  # noqa: BLE001 - a missing layer is a failed check
            counts[identifier] = -1
            print(f"count failed for {identifier}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return counts


def _serving_counts() -> dict[str, int]:
    from bmip.common.config import get_settings
    from bmip.serving.repository import ServingRepository

    repository = ServingRepository(get_settings())
    try:
        return repository.counts()
    finally:
        repository.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M1 end-to-end gate")
    parser.add_argument("--api-key", default=os.getenv("BMIP_API_KEY", ""))
    parser.add_argument("--api", default=API)
    parser.add_argument("--dashboard", default=DASHBOARD)
    args = parser.parse_args(argv)

    checks: list[tuple[str, bool, str]] = []
    raw: dict[str, Any] = {}

    status, body, _ = _http(f"{args.api}/health/ready")
    checks.append(("api/health-ready", status == 200, f"HTTP {status} {body[:120]}"))

    status, payload, headers = _json(f"{args.api}/v1/market/latest", args.api_key)
    market = payload.get("data") if isinstance(payload, dict) else None
    checks.append(
        (
            "api/market-latest",
            status == 200 and bool(market) and float((market or {}).get("close") or 0) > 0,
            f"HTTP {status} close={(market or {}).get('close')}",
        )
    )
    raw["market_latest"] = payload

    status, payload, _ = _json(f"{args.api}/v1/sentiment/latest", args.api_key)
    sentiment = payload.get("data") if isinstance(payload, dict) else None
    checks.append(
        (
            "api/sentiment-latest",
            status == 200,
            f"HTTP {status} posts={(sentiment or {}).get('post_count')}",
        )
    )
    raw["sentiment_latest"] = payload

    status, payload, _ = _json(f"{args.api}/v1/freshness", args.api_key)
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    metrics = {row["metric"] for row in rows}
    checks.append(
        (
            "api/freshness",
            status == 200 and {"market", "sentiment"} <= metrics,
            f"{sorted(metrics)}",
        )
    )
    raw["freshness"] = payload

    status, payload, _ = _json(f"{args.api}/v1/quality/status", args.api_key)
    data = payload.get("data") if isinstance(payload, dict) else None
    quality_status = (data or {}).get("status")
    checks.append(
        (
            "api/quality-status",
            status == 200 and quality_status in {"pass", "fail"},
            str(quality_status),
        )
    )
    raw["quality"] = payload

    status, payload, _ = _json(f"{args.api}/v1/model/latest", args.api_key)
    model_status = payload.get("status") if isinstance(payload, dict) else None
    checks.append(
        (
            "api/model-latest",
            status == 200 and model_status in {"available", "not_available"},
            str(model_status),
        )
    )
    raw["model"] = payload

    status, _, _ = _http(f"{args.dashboard}/_stcore/health")
    checks.append(("dashboard/health", status == 200, f"HTTP {status}"))
    status, page, _ = _http(f"{args.dashboard}/")
    checks.append(
        (
            "dashboard/page",
            status == 200 and "streamlit" in page.lower(),
            f"HTTP {status} bytes={len(page)}",
        )
    )
    status, page, _ = _http(f"{TRAEFIK}/api")
    checks.append(("traefik/api-route", status == 200, f"HTTP {status}"))

    bronze = _counts("process", ("bronze.market_trade_raw", "bronze.social_post_raw"))
    silver = _counts("process", ("silver.market_ohlcv_1m", "silver.social_post"))
    gold = _counts("api", ("gold.mart_market", "gold.mart_sentiment", "gold.mart_ml"))
    serving = _serving_counts()
    raw["counts"] = {"bronze": bronze, "silver": silver, "gold": gold, "serving": serving}

    checks.append(("bronze/market", bronze.get("bronze.market_trade_raw", 0) > 0, str(bronze)))
    checks.append(("bronze/social", bronze.get("bronze.social_post_raw", 0) > 0, str(bronze)))
    checks.append(("silver/market", silver.get("silver.market_ohlcv_1m", 0) > 0, str(silver)))
    checks.append(("silver/social", silver.get("silver.social_post", 0) > 0, str(silver)))
    checks.append(("gold/market", gold.get("gold.mart_market", 0) > 0, str(gold)))
    checks.append(("serving/market", serving.get("serving.market_hourly", 0) > 0, str(serving)))
    checks.append(
        ("serving/sentiment", serving.get("serving.sentiment_hourly", 0) > 0, str(serving))
    )

    passed = all(ok for _, ok, _ in checks)
    lines = [
        "id        : M1",
        f"timestamp : {_iso()}",
        f"commit    : {_commit()}",
        "command   : python scripts/m1_smoke.py",
        f"result    : {'PASS' if passed else 'FAIL'}",
        f"owner     : {OWNER}",
        "",
        "Gate M1: bronze -> silver -> gold -> serving -> API -> dashboard.",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    lines += [
        f"| `{name}` | {'PASS' if ok else 'FAIL'} | {detail} |"
        for name, ok, detail in checks
    ]
    lines += ["", "## payloads", json.dumps(raw, indent=2, default=str)[:20000]]
    target = EVIDENCE / f"e2e/M1_{_stamp()}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": "PASS" if passed else "FAIL",
                "evidence": str(target.relative_to(ROOT)),
                "checks": [
                    {"name": name, "status": "PASS" if ok else "FAIL", "detail": detail}
                    for name, ok, detail in checks
                ],
            },
            indent=2,
            default=str,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
