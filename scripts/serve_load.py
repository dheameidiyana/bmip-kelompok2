#!/usr/bin/env python3
"""Publish gold marts into the serving schema (W1-D).

Usage:
    python scripts/serve_load.py
    python scripts/serve_load.py --start 2026-11-10T00:00:00Z --end 2026-11-11T00:00:00Z
    python scripts/serve_load.py --skip-registry --skip-quality
    python scripts/serve_load.py --counts

The loader is idempotent; running it twice publishes the same logical rows and
prints the same ``logical_hash``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load gold into serving")
    parser.add_argument("--start", help="ISO-8601 window_start lower bound")
    parser.add_argument("--end", help="ISO-8601 window_start upper bound")
    parser.add_argument("--skip-registry", action="store_true")
    parser.add_argument("--skip-quality", action="store_true")
    parser.add_argument("--counts", action="store_true", help="Only print table counts")
    parser.add_argument("--prune", type=int, metavar="DAYS", help="Trim serving rows")
    args = parser.parse_args(argv)

    from bmip.common.config import get_settings
    from bmip.serving.loader import load_serving, prune_serving
    from bmip.serving.repository import ServingRepository

    settings = get_settings()
    if args.prune is not None:
        print(json.dumps(prune_serving(settings, days=args.prune), indent=2))
        return 0
    if args.counts:
        repository = ServingRepository(settings)
        try:
            print(json.dumps(repository.counts(), indent=2))
        finally:
            repository.close()
        return 0

    result = load_serving(
        settings,
        start=_parse_ts(args.start),
        end=_parse_ts(args.end),
        with_registry=not args.skip_registry,
        with_quality=not args.skip_quality,
    )
    print(json.dumps(result.as_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
