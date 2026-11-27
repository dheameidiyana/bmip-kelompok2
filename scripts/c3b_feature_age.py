"""Snapshot the Feast online feature age for every configured symbol."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bmip.common.config import get_settings
from bmip.ml.features import latest_features

ROOT = Path(__file__).resolve().parents[1]
MAX_AGE_SECONDS = 7200


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="")
    args = parser.parse_args()
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00")).astimezone(UTC)
        if args.as_of
        else datetime.now(UTC)
    )
    settings = get_settings()
    rows = []
    for symbol in settings.market_symbols:
        latest = latest_features(settings, symbol, at=as_of)
        if latest is None:
            rows.append({"symbol": symbol, "status": "missing"})
            continue
        feature_ts = latest["window_start"]
        age = max(0.0, (as_of - feature_ts).total_seconds())
        rows.append(
            {
                "symbol": symbol,
                "feature_ts": feature_ts.isoformat(),
                "age_seconds": age,
                "status": "error" if age > MAX_AGE_SECONDS else "ok",
            }
        )
    payload = {
        "id": "C3-B-feature-age",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "feature_source": settings.feature_source,
        "max_age_seconds": MAX_AGE_SECONDS,
        "symbols": rows,
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "evidence" / "ml" / f"feature-age_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
