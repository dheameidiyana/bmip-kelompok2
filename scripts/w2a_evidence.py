"""Generate the W2-A final T-36 evidence against the running API."""

from __future__ import annotations

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
BASE_URL = os.getenv("BMIP_API_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("BMIP_API_KEY", "")
EVIDENCE = ROOT / "evidence" / "ml" / "T36.json"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _post(body: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(
        f"{BASE_URL}/v1/predict",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            headers = {
                key.lower(): value for key, value in response.headers.items()
            }
            return response.status, json.loads(response.read()), headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        headers = {
            key.lower(): value for key, value in (exc.headers or {}).items()
        }
        return exc.code, payload, headers


def main() -> int:
    cases: list[dict[str, Any]] = []

    status, payload, _ = _post(
        {"symbol": "BTCUSDT", "features": {"rv_60m": "nan-ish"}}
    )
    cases.append(
        {
            "case": "malformed feature",
            "status": status,
            "type": payload.get("type"),
            "pass": status == 422,
        }
    )

    status, payload, _ = _post(
        {"symbol": "BTCUSDT", "features": {"rv_60m": -1}}
    )
    cases.append(
        {
            "case": "out-of-range feature",
            "status": status,
            "status_field": payload.get("status"),
            "pass": status == 200 and payload.get("status") == "error",
        }
    )

    valid: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        status, payload, headers = _post({"symbol": symbol})
        row = {
            "symbol": symbol,
            "status": status,
            "status_field": payload.get("status"),
            "model_name": payload.get("model_name"),
            "model_version": payload.get("model_version"),
            "predicted_rv_next_1h": payload.get("predicted_rv_next_1h"),
            "feature_ts": payload.get("feature_ts"),
            "stale": (payload.get("meta") or {}).get("stale"),
            "stale_header": headers.get("x-data-stale"),
            "pass": (
                status == 200
                and payload.get("status") == "ok"
                and payload.get("feature_ts") is not None
                and headers.get("x-data-stale") in {"true", "false"}
            ),
        }
        valid.append(row)
        cases.append(
            {
                "case": f"valid payload {symbol}",
                **{key: value for key, value in row.items() if key != "symbol"},
                "symbol": symbol,
            }
        )

    passed = all(item["pass"] for item in cases)
    evidence = {
        "id": "T-36",
        "scope": "W2-A final: champion volatility_model v2",
        "timestamp": _now(),
        "commit": _commit(),
        "command": "python scripts/w2a_evidence.py",
        "result": "PASS" if passed else "FAIL",
        "owner": "dhea",
        "notes": (
            "The W1-D no-champion case was a W1-D placeholder. This final run "
            "replaces it with valid five-symbol payloads, malformed input, and "
            "an out-of-range feature while champion v2 is registered."
        ),
        "cases": cases,
    }
    EVIDENCE.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
