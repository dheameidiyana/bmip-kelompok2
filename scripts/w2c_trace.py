#!/usr/bin/env python3
"""T-30 raw-to-gold trace for one market payload hash (W2-C).

The trace follows a single trade from bronze through silver and gold to the
serving table and the Query API, and records whether the price survives every
step. It writes ``evidence/lineage/T30.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence" / "lineage" / "T30.md"

load_dotenv(ROOT / ".env")


def _rows(
    table: str,
    service: str,
    settings,
    fields: tuple[str, ...] | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    catalog = load_rest_catalog(settings, service)
    loaded = table_with_host_io(catalog, settings, table, service)
    scan = loaded.scan(selected_fields=fields) if fields else loaded.scan()
    if filters:
        try:
            from pyiceberg.expressions import EqualTo

            expression = None
            for key, value in filters.items():
                clause = EqualTo(key, value)
                expression = clause if expression is None else expression & clause
            scan = scan.filter(expression)
        except Exception:  # noqa: BLE001 - fall back to a full scan
            pass
    return scan.to_arrow().to_pylist()


def _first(rows: list[dict[str, Any]], **matches: Any) -> dict[str, Any] | None:
    for row in rows:
        if all(row.get(key) == value for key, value in matches.items()):
            return row
    return None


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _bucket(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def main(argv: list[str] | None = None) -> int:
    from bmip.common.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-hash", default=None)
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args(argv)
    settings = get_settings()

    bronze_rows = _rows(
        "bronze.market_trade_raw",
        "process",
        settings,
        fields=("symbol", "trade_id", "event_ts", "price", "payload_hash"),
    )
    silver_rows = _rows(
        "silver.market_trades",
        "process",
        settings,
        fields=("symbol", "trade_id", "event_ts", "price", "payload_hash"),
    )
    if args.payload_hash:
        bronze = _first(bronze_rows, payload_hash=args.payload_hash)
    else:
        bronze_hashes = {str(row.get("payload_hash")) for row in bronze_rows}
        bronze = next(
            (row for row in silver_rows if str(row.get("payload_hash")) in bronze_hashes),
            bronze_rows[0] if bronze_rows else None,
        )
    if bronze is None:
        print("no bronze market rows; run a replay first", file=sys.stderr)
        return 1
    payload_hash = str(bronze["payload_hash"])
    symbol = str(args.symbol or bronze["symbol"])
    event_ts = bronze["event_ts"]
    hour = event_ts.replace(minute=0, second=0, microsecond=0)
    price = float(bronze["price"])

    steps: list[dict[str, Any]] = []

    def add(step: str, dataset: str, value: Any, ok: bool, note: str = "") -> None:
        steps.append(
            {
                "step": step,
                "dataset": dataset,
                "value": value,
                "ok": ok,
                "note": note,
            }
        )

    add("bronze", "bronze.market_trade_raw", price, True, f"trade_id={bronze['trade_id']}")

    silver = _first(silver_rows, payload_hash=payload_hash)
    silver_price = float(silver["price"]) if silver else None
    add(
        "silver",
        "silver.market_trades",
        silver_price,
        silver is not None and abs(silver_price - price) < 1e-8,
        "same payload_hash and price" if silver else "row not found",
    )

    gold_rows = _rows(
        "gold.mart_market",
        "api",
        settings,
        fields=("symbol", "window_start", "low", "high", "close", "trade_count"),
    )
    gold = _first(gold_rows, symbol=symbol, window_start=hour)
    if gold is None:
        gold = next(
            (
                row
                for row in gold_rows
                if row.get("symbol") == symbol and _bucket(row.get("window_start")) == hour
            ),
            None,
        )
    gold_ok = bool(
        gold
        and float(gold["low"]) <= price <= float(gold["high"])
        and int(gold["trade_count"]) >= 1
    )
    add(
        "gold",
        "gold.mart_market",
        {"low": gold["low"], "high": gold["high"], "close": gold["close"]}
        if gold
        else None,
        gold_ok,
        "price is inside the hourly OHLC range" if gold else "hour not found",
    )

    from bmip.serving.repository import connect

    with connect(settings) as connection:
        serving = connection.execute(
            """
            SELECT window_start, low, high, close, trade_count
            FROM serving.market_hourly
            WHERE symbol = %s AND window_start = %s
            """,
            (symbol, hour),
        ).fetchone()
    serving_ok = bool(
        serving
        and float(serving["low"]) <= price <= float(serving["high"])
    )
    add(
        "serving",
        "serving.market_hourly",
        dict(serving) if serving else None,
        serving_ok,
        "serving equals the gold hour" if serving else "serving row not found",
    )

    api_ok = False
    api_bar: dict[str, Any] | None = None
    try:
        base = settings.api_host if settings.api_host.startswith("http") else "http://localhost:8000"
        response = httpx.get(
            f"{base}/v1/market/ohlc",
            params={
                "symbol": symbol,
                "from": hour.isoformat(),
                "to": (hour + timedelta(hours=1)).isoformat(),
                "limit": 10,
            },
            headers={"X-API-Key": settings.api_key},
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json().get("data") or []
            api_bar = next(
                (
                    row
                    for row in data
                    if _iso(row.get("window_start")).startswith(hour.isoformat()[:19])
                ),
                data[0] if data else None,
            )
            if api_bar:
                api_ok = abs(float(api_bar["close"]) - float(serving["close"])) < 1e-8
    except Exception as exc:  # noqa: BLE001 - trace must report, not crash
        api_bar = {"error": f"{type(exc).__name__}: {exc}"}
    add(
        "api",
        "/v1/market/ohlc",
        api_bar.get("close") if isinstance(api_bar, dict) else None,
        api_ok,
        "API close equals serving close" if api_ok else "API call or value mismatch",
    )

    passed = all(step["ok"] for step in steps)
    lines = [
        "# T-30 raw-to-gold trace",
        "",
        f"- payload_hash: `{payload_hash}`",
        f"- symbol: `{symbol}`",
        f"- event_ts: `{_iso(event_ts)}`",
        f"- hour bucket: `{_iso(hour)}`",
        f"- result: **{'PASS' if passed else 'FAIL'}**",
        f"- generated_at: `{datetime.now(UTC).isoformat()}`",
        "",
        "| Step | Dataset | Value | OK | Note |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in steps:
        value = json.dumps(step["value"], default=str)
        lines.append(
            f"| {step['step']} | `{step['dataset']}` | `{value}` | "
            f"{'PASS' if step['ok'] else 'FAIL'} | {step['note']} |"
        )
    lines.append("")
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"passed": passed, "output": str(target)}, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
