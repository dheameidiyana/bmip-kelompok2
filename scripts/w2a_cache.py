"""Refresh the API latest-feature cache without requiring a champion model."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from bmip.common.config import get_settings
from bmip.ml.batch import write_feature_cache
from bmip.ml.dataset import latest_feature_row

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    settings = get_settings()
    rows = {}
    for symbol in settings.market_symbols:
        row = latest_feature_row(settings, symbol)
        if row is not None:
            rows[symbol] = row
    if not rows:
        raise RuntimeError("no latest feature rows are available")
    write_feature_cache(rows)
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "symbols": sorted(rows),
                "feature_ts": {
                    symbol: str(row["window_start"])
                    for symbol, row in sorted(rows.items())
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
