#!/usr/bin/env python3
"""Seed the three RBAC keys into ops.api_keys (W2-C).

The plaintext keys live in ``.env`` (gitignored) and are shown once. Existing
keys are reused so a restart does not invalidate the dashboard; pass ``--rotate``
to mint a new secret for every role.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
ROLES = {
    "viewer": ("BMIP_VIEWER_KEY", "demo-viewer"),
    "operator": ("BMIP_OPERATOR_KEY", "demo-operator"),
    "admin": ("BMIP_ADMIN_KEY", "demo-admin"),
}


def _set_env(name: str, value: str) -> None:
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(f"{name}="):
            lines[index] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ENV)
    from bmip.api.keys import hash_secret, new_key, parse_key
    from bmip.common.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rotate", action="store_true")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    salt = settings.api_key_salt
    dsn = args.dsn or settings.postgres_dsn
    values: dict[str, str] = {}
    with psycopg.connect(
        dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
    ) as connection:
        for role, (env_name, owner) in ROLES.items():
            raw = os.getenv(env_name, "")
            if args.rotate or not raw or not parse_key(raw):
                raw, _identity, _hashed = new_key(role, owner)
                _set_env(env_name, raw)
            secret = parse_key(raw)
            if secret is None:
                print(f"{env_name} is not in bmip_<id>_<secret> format", file=sys.stderr)
                return 1
            key_id, secret_value = secret
            connection.execute(
                """
                INSERT INTO ops.api_keys (key_id, key_hash, role, owner)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (key_id) DO UPDATE SET
                    key_hash = EXCLUDED.key_hash,
                    role = EXCLUDED.role,
                    owner = EXCLUDED.owner,
                    revoked_at = NULL,
                    created_at = now()
                """,
                (key_id, hash_secret(secret_value, salt), role, owner),
            )
            values[role] = raw
    if not args.quiet:
        for role, raw in values.items():
            print(f"{role}: {raw}")
    print(f"seeded {len(values)} api keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
