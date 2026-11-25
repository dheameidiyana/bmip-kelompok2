#!/usr/bin/env python3
"""CP1/CP2 evidence for W2-C: Marquez event, catalogue rows, summary."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "nogit"


def _write(area: str, name: str, text: str) -> Path:
    path = ROOT / "evidence" / area / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _header(identity: str, command: str, result: str) -> str:
    return "\n".join(
        [
            f"id        : {identity}",
            f"timestamp : {datetime.now(UTC).isoformat()}",
            f"commit    : {_sha()}",
            f"command   : {command}",
            f"result    : {result}",
            "owner     : anin",
            "",
        ]
    )


def _spool_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted((ROOT / "evidence" / "lineage" / "spool").glob("events_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _marquez_health() -> dict[str, Any]:
    base = (os.getenv("MARQUEZ_URL") or "http://localhost:5002").rstrip("/")
    for path in ("/api/v1/health", "/healthcheck", "/api/v1/namespaces"):
        try:
            response = httpx.get(f"{base}{path}", timeout=5)
            if response.status_code == 200:
                return {"url": f"{base}{path}", "status": response.status_code}
            last = f"{path} -> {response.status_code}"
        except httpx.HTTPError as exc:
            last = f"{type(exc).__name__}: {exc}"
    return {"url": base, "status": 0, "error": locals().get("last", "unreachable")}


def _screenshot(path: Path, url: str = "http://127.0.0.1:3002") -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(path), full_page=True)
            browser.close()
        return str(path.relative_to(ROOT))
    except Exception as exc:  # noqa: BLE001 - screenshot is evidence, not a gate
        print(f"screenshot failed: {exc}", file=sys.stderr)
        return None


def cp1() -> dict[str, Any]:
    stamp = _stamp()
    events = _spool_events()
    dbt = [
        event
        for event in events
        if str((event.get("job") or {}).get("name", "")).startswith("dbt_build")
    ]
    try:
        from bmip.lineage import cache_edges

        cached = sum(cache_edges(event) for event in events)
    except Exception:  # noqa: BLE001 - evidence still works without the cache
        cached = 0
    health = _marquez_health()
    raw = _write(
        "lineage",
        f"events_{stamp}.jsonl",
        "\n".join(json.dumps(event, ensure_ascii=True) for event in events) + "\n",
    )
    shot = _screenshot(ROOT / "evidence" / "lineage" / f"first-event_{stamp}.png")
    passed = bool(dbt) and health.get("status") == 200
    lines = [
        _header("CP1", "python scripts/w2c_evidence.py --steps cp1", "PASS" if passed else "FAIL"),
        f"Marquez health: {health}",
        f"dbt_build events: {len(dbt)}",
        f"lineage edges cached: {cached}",
        f"raw events: {raw.relative_to(ROOT)}",
        f"screenshot: {shot or 'unavailable'}",
        "",
    ]
    for event in dbt[-6:]:
        lines.append(
            f"- {event.get('eventType')} job={(event.get('job') or {}).get('name')} "
            f"run={(event.get('run') or {}).get('runId')} "
            f"inputs={len(event.get('inputs') or [])} outputs={len(event.get('outputs') or [])}"
        )
    path = _write("lineage", f"CP1_{stamp}.md", "\n".join(lines) + "\n")
    return {"step": "cp1", "passed": passed, "evidence": str(path.relative_to(ROOT))}


def cp2() -> dict[str, Any]:
    from bmip.common.config import get_settings

    stamp = _stamp()
    settings = get_settings()
    with psycopg.connect(settings.postgres_dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT id, name, layer, domain, owner, classification,
                   retention_days, refresh_schedule, sla, license,
                   contains_pii, auto_classification
            FROM ops.dataset_registry
            ORDER BY layer, id
            """
        ).fetchall()
        serving_count = connection.execute(
            "SELECT count(*) AS n FROM serving.catalog_datasets"
        ).fetchone()["n"]
    path = ROOT / "evidence" / "catalog" / f"registry_{stamp}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["id"])
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    complete = all(
        row["owner"] and row["classification"] and row["retention_days"] is not None
        for row in rows
    )
    shot = _screenshot(
        ROOT / "evidence" / "catalog" / f"catalog_{stamp}.png",
        "http://127.0.0.1:8502",
    )
    passed = len(rows) >= 11 and complete and serving_count >= 11
    lines = [
        _header("CP2", "python scripts/w2c_evidence.py --steps cp2", "PASS" if passed else "FAIL"),
        f"ops.dataset_registry rows: {len(rows)}",
        f"serving.catalog_datasets rows: {serving_count}",
        f"CSV: {path.relative_to(ROOT)}",
        f"screenshot: {shot or 'unavailable'}",
        "",
        "| id | owner | classification | auto | retention |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['id']} | {row['owner']} | {row['classification']} | "
            f"{row['auto_classification'] or '-'} | {row['retention_days']} |"
        )
    evidence = _write("catalog", f"CP2_{stamp}.md", "\n".join(lines) + "\n")
    return {
        "step": "cp2",
        "passed": passed,
        "rows": len(rows),
        "serving_rows": serving_count,
        "evidence": str(evidence.relative_to(ROOT)),
    }


def summary() -> dict[str, Any]:
    stamp = _stamp()
    payload = {
        "commit": _sha(),
        "generated_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "env": "dev",
        "files": sorted(
            str(path.relative_to(ROOT))
            for path in (ROOT / "evidence" / "lineage").glob("*")
            if path.is_file()
        ),
    }
    path = _write(
        "w2c",
        f"SUMMARY_{stamp}_{_sha()}.json",
        json.dumps(payload, indent=2) + "\n",
    )
    return {"step": "summary", "passed": True, "evidence": str(path.relative_to(ROOT))}


STEPS = {"cp1": cp1, "cp2": cp2, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", default="cp1,cp2,summary")
    args = parser.parse_args(argv)
    results = []
    for name in [part.strip() for part in args.steps.split(",") if part.strip()]:
        if name not in STEPS:
            print(f"unknown step: {name}", file=sys.stderr)
            return 2
        results.append(STEPS[name]())
    print(json.dumps(results, indent=2))
    return 0 if all(item.get("passed") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
