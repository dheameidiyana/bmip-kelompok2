#!/usr/bin/env python3
"""Apply the C3-C catalog search and governance migration (idempotent).

The W2-C init script only runs on a fresh postgres-core volume. This script is
the upgrade path for the running demo volume: extension, governance columns,
the generated tsvector, and the trigram indexes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

STATEMENTS = [
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # Business registry (source of truth).
    """
    ALTER TABLE ops.dataset_registry
        ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active',
        ADD COLUMN IF NOT EXISTS deprecated_at timestamptz,
        ADD COLUMN IF NOT EXISTS removal_date date,
        ADD COLUMN IF NOT EXISTS contract_version text,
        ADD COLUMN IF NOT EXISTS change_note text
    """,
    # Serving copy read by the API and the catalog portal.
    """
    ALTER TABLE serving.catalog_datasets
        ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active',
        ADD COLUMN IF NOT EXISTS deprecated_at timestamptz,
        ADD COLUMN IF NOT EXISTS removal_date date,
        ADD COLUMN IF NOT EXISTS contract_version text
    """,
    """
    ALTER TABLE serving.catalog_datasets
        ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (
            to_tsvector(
                'simple',
                coalesce(id, '') || ' ' || coalesce(name, '') || ' ' ||
                coalesce(description, '') || ' ' || coalesce(owner, '')
            )
        ) STORED
    """,
    (
        "CREATE INDEX IF NOT EXISTS catalog_datasets_search_idx "
        "ON serving.catalog_datasets USING GIN (search_vector)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS catalog_datasets_name_trgm_idx "
        "ON serving.catalog_datasets USING GIN (name gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS catalog_datasets_description_trgm_idx "
        "ON serving.catalog_datasets USING GIN (description gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS catalog_datasets_owner_trgm_idx "
        "ON serving.catalog_datasets USING GIN (owner gin_trgm_ops)"
    ),
    (
        "CREATE INDEX IF NOT EXISTS dataset_registry_status_idx "
        "ON ops.dataset_registry (status, layer)"
    ),
]


def _sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return os.getenv("BMIP_COMMIT", "nogit")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)

    from bmip.common.config import get_settings

    dsn = args.dsn or get_settings().postgres_dsn
    pending_serving = False
    with psycopg.connect(dsn, autocommit=True) as connection:
        has_serving = bool(
            connection.execute("SELECT to_regclass('serving.catalog_datasets')").fetchone()[0]
        )
        for statement in STATEMENTS:
            if "serving.catalog_datasets" in statement and not has_serving:
                pending_serving = True
                continue
            connection.execute(statement)
        extension = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'"
        ).fetchone()
        columns = connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'serving' AND table_name = 'catalog_datasets'
              AND column_name IN ('status', 'search_vector', 'removal_date')
            ORDER BY column_name
            """
        ).fetchall()
        indexes = connection.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE schemaname IN ('serving', 'ops')
              AND (indexname LIKE 'catalog_datasets_%' OR indexname LIKE 'dataset_registry_%')
            ORDER BY indexname
            """
        ).fetchall()

    result = {
        "id": "C3C-migrate",
        "commit": _sha(),
        "dsn_schema": "postgres-core",
        "pg_trgm": extension[0] if extension else None,
        "catalog_columns": [row[0] for row in columns],
        "indexes": [row[0] for row in indexes],
        "serving_pending": pending_serving,
        "result": "PASS" if extension and columns else "FAIL",
    }
    evidence = ROOT / "evidence" / "catalog"
    evidence.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = evidence / f"migration_{stamp}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "evidence": str(path.relative_to(ROOT))}, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
