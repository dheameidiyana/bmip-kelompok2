#!/usr/bin/env python3
"""Apply the W2-C SQL migration to postgres-core (idempotent)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "deploy" / "postgres" / "init" / "02_w2c.sql"


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    from bmip.common.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=None, help="override POSTGRES_CORE_DSN")
    args = parser.parse_args(argv)
    dsn = args.dsn or get_settings().postgres_dsn
    sql = MIGRATION.read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
    print(f"applied {MIGRATION.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - surface a clean message
        print(f"migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
