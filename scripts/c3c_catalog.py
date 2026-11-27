#!/usr/bin/env python3
"""Write catalog search and five-view evidence for C3-C CP2."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "catalog"
load_dotenv(ROOT / ".env")
BASE = os.getenv("BMIP_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CATALOG_URL = os.getenv("BMIP_CATALOG_URL", "http://127.0.0.1:8502")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = {}
    key = os.getenv("BMIP_API_KEY", "")
    if key:
        headers["X-API-Key"] = key
    response = httpx.get(f"{BASE}{path}", params=params, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def _screenshot(path: Path) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.goto(CATALOG_URL, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(path), full_page=True)
            browser.close()
        return str(path.relative_to(ROOT))
    except Exception as exc:  # noqa: BLE001 - screenshot is evidence, not a gate
        print(f"screenshot failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    queries = {
        "name-mart": {"q": "mart"},
        "name-sentiment": {"q": "sentiment"},
        "owner-vio": {"owner": "vio"},
        "tag-streaming": {"q": "streaming"},
        "description-prediction": {"q": "prediction"},
    }
    results: dict[str, Any] = {}
    failures: list[str] = []
    for name, params in queries.items():
        try:
            payload = _get("/v1/dataset", params)
            rows = payload.get("data", [])
            results[name] = {
                "params": params,
                "count": len(rows),
                "ids": [row["id"] for row in rows][:8],
            }
            if not rows:
                failures.append(f"{name}: no rows")
        except httpx.HTTPError as exc:
            results[name] = {"params": params, "error": f"{type(exc).__name__}: {exc}"}
            failures.append(f"{name}: request failed")

    try:
        all_rows = _get("/v1/dataset", {"limit": 100}).get("data", [])
        quality = _get("/v1/quality/status").get("data", {})
        freshness = _get("/v1/freshness").get("data", [])
    except httpx.HTTPError as exc:
        all_rows = []
        quality = {}
        freshness = []
        failures.append(f"catalog views: {type(exc).__name__}: {exc}")

    layers = sorted({row["layer"] for row in all_rows})
    statuses = sorted({row.get("status", "active") for row in all_rows})
    stamp = _stamp()
    search_path = EVIDENCE / f"search_{stamp}.txt"
    search_path.write_text(
        "\n".join(
            [
                "id        : CP2-catalog-search",
                f"timestamp : {datetime.now(UTC).isoformat()}",
                f"commit    : {_sha()}",
                "command   : python scripts/c3c_catalog.py",
                f"result    : {'PASS' if not failures else 'FAIL'}",
                "owner     : vio",
                "",
                f"api       : {BASE}",
                f"datasets  : {len(all_rows)}",
                f"layers    : {layers}",
                f"statuses  : {statuses}",
                "",
                "| query | params | count | ids |",
                "| --- | --- | --- | --- |",
                *[
                    f"| {name} | {json.dumps(value.get('params'), ensure_ascii=True)} | "
                    f"{value.get('count', 0)} | {', '.join(value.get('ids') or [])} |"
                    for name, value in results.items()
                ],
                "",
                "failures: " + (json.dumps(failures) if failures else "none"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    views = {
        "search": {"datasets": len(all_rows), "queries": len(results)},
        "detail": {"datasets": len(all_rows), "schemas_endpoint": "/v1/dataset/{id}/schema"},
        "lineage": {"datasets": len(all_rows), "lineage_endpoint": "/v1/lineage/{id}"},
        "quality": {
            "status": quality.get("status"),
            "failures": len(quality.get("failures") or []),
        },
        "governance": {
            "datasets": len(all_rows),
            "missing_owner": sum(1 for row in all_rows if not row.get("owner")),
            "missing_description": sum(1 for row in all_rows if not row.get("description")),
            "deprecated": sum(1 for row in all_rows if row.get("status") not in (None, "active")),
        },
    }
    document = {
        "id": "CP2-catalog-views",
        "timestamp": datetime.now(UTC).isoformat(),
        "commit": _sha(),
        "command": "python scripts/c3c_catalog.py",
        "result": "PASS" if not failures and len(all_rows) >= 11 else "FAIL",
        "owner": "vio",
        "views": views,
        "freshness_rows": len(freshness),
        "search_evidence": str(search_path.relative_to(ROOT)),
        "failures": failures,
    }
    views_path = EVIDENCE / f"views_{stamp}.json"
    views_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    shot = _screenshot(EVIDENCE / f"views_{stamp}.png")
    document["screenshot"] = shot
    if shot:
        views_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "result": document["result"],
                "views": views,
                "search_evidence": str(search_path.relative_to(ROOT)),
                "views_evidence": str(views_path.relative_to(ROOT)),
                "screenshot": shot,
                "failures": failures,
            },
            indent=2,
        )
    )
    return 0 if document["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
