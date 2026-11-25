#!/usr/bin/env python3
"""Create the read-only API replica role for C3-A.

The replica may read every business table and append auth/audit telemetry, but
it must not write serving predictions, registry rows, or admin requests. The
read/write router split in Traefik keeps POST endpoints on the primary.
"""

from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from bmip.common.config import get_settings

DEFAULT_ROLE = "bmip_api_ro"


def _password() -> str:
    value = os.getenv("POSTGRES_API_RO_PASSWORD")
    if not value:
        raise SystemExit("POSTGRES_API_RO_PASSWORD is not set in .env")
    return value


def main() -> int:
    load_dotenv()
    settings = get_settings()
    role = os.getenv("POSTGRES_API_RO_USER", DEFAULT_ROLE)
    password = _password()
    database = os.getenv("POSTGRES_DB", "bmip")

    with psycopg.connect(settings.postgres_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if exists:
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        else:
            conn.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )

        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(role)
            )
        )
        for schema in ("serving", "ops"):
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(role)
                )
            )
            conn.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} GRANT SELECT ON TABLES TO {}"
                ).format(sql.Identifier(schema), sql.Identifier(role))
            )
            conn.execute(
                sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                    sql.Identifier(schema), sql.Identifier(role)
                )
            )

        # Auth and audit are append-only side effects. Kept narrow on purpose.
        conn.execute(
            sql.SQL("GRANT INSERT, SELECT ON ops.audit_log TO {}").format(sql.Identifier(role))
        )
        conn.execute(
            sql.SQL("GRANT UPDATE (last_used_at) ON ops.api_keys TO {}").format(
                sql.Identifier(role)
            )
        )

        # Fail loudly if a future table is created outside the default privileges.
        summary = conn.execute(
            """
            SELECT
                has_schema_privilege(%s, 'serving', 'USAGE') AS serving_usage,
                has_schema_privilege(%s, 'ops', 'USAGE') AS ops_usage,
                has_table_privilege(%s, 'serving.market_hourly', 'SELECT') AS market_read,
                has_table_privilege(%s, 'ops.dataset_registry', 'SELECT') AS registry_read,
                has_table_privilege(%s, 'ops.audit_log', 'INSERT') AS audit_insert,
                has_table_privilege(%s, 'serving.predictions', 'INSERT') AS prediction_insert
            """,
            (role, role, role, role, role, role),
        ).fetchone()

    print(
        {
            "role": role,
            "database": database,
            "serving_usage": summary[0],
            "ops_usage": summary[1],
            "market_read": summary[2],
            "registry_read": summary[3],
            "audit_insert": summary[4],
            "prediction_insert": summary[5],
        }
    )
    if not all(summary[:5]) or summary[5]:
        raise SystemExit("role grants are not in the expected state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
