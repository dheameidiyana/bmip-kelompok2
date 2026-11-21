#!/usr/bin/env python3
"""Seed ops.dataset_registry from catalog/datasets.yml (idempotent)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]

FIELDS = (
    "id",
    "name",
    "layer",
    "domain",
    "kind",
    "location",
    "description",
    "owner",
    "classification",
    "retention_days",
    "refresh_schedule",
    "sla",
    "license",
    "contains_pii",
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    from bmip.common.config import get_settings
    from bmip.serving.registry import DEFAULT_PATH, parse_registry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", default=str(DEFAULT_PATH))
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)

    import yaml

    payload = yaml.safe_load(Path(args.yaml).read_text(encoding="utf-8")) or {}
    datasets = parse_registry(payload)
    dsn = args.dsn or get_settings().postgres_dsn
    with psycopg.connect(
        dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
    ) as connection:
        with connection.cursor() as cursor:
            for dataset in datasets:
                row = dataset.row()
                cursor.execute(
                    """
                    INSERT INTO ops.dataset_registry
                        (id, name, layer, domain, kind, location, description,
                         owner, classification, retention_days, refresh_schedule,
                         sla, license, contains_pii, tags, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        layer = EXCLUDED.layer,
                        domain = EXCLUDED.domain,
                        kind = EXCLUDED.kind,
                        location = EXCLUDED.location,
                        description = EXCLUDED.description,
                        owner = EXCLUDED.owner,
                        classification = EXCLUDED.classification,
                        retention_days = EXCLUDED.retention_days,
                        refresh_schedule = EXCLUDED.refresh_schedule,
                        sla = EXCLUDED.sla,
                        license = EXCLUDED.license,
                        contains_pii = EXCLUDED.contains_pii,
                        tags = EXCLUDED.tags,
                        updated_at = now()
                    """,
                    tuple(row.get(field) for field in FIELDS)
                    + (list(row.get("tags") or ()),),
                )
            count = cursor.execute(
                "SELECT count(*) AS n FROM ops.dataset_registry"
            ).fetchone()["n"]
    print(f"seeded {len(datasets)} datasets; registry now has {count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
