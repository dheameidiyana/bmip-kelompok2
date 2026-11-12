#!/usr/bin/env python3
"""Generate a local .env from .env.example with random secrets.

The file is written once. Existing .env files are never overwritten unless
--force is passed, so local passwords survive a `make reset`.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"

RANDOM_KEYS = {
    "MINIO_ROOT_PASSWORD",
    "LAKEKEEPER_DB_PASSWORD",
    "LAKEKEEPER_PG_ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "PII_HASH_SALT",
    "BMIP_API_KEY_HASH_SALT",
}


def _is_random_key(key: str) -> bool:
    return key in RANDOM_KEYS or key.endswith("_SECRET_KEY")


def _new_value(key: str) -> str:
    if key == "LAKEKEEPER_PG_ENCRYPTION_KEY":
        return secrets.token_urlsafe(32)
    return secrets.token_urlsafe(24)


def render(source: str) -> str:
    values: dict[str, str] = {}
    lines: list[str] = []

    for raw in source.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            lines.append(raw)
            continue

        key, value = raw.split("=", 1)
        if _is_random_key(key):
            value = _new_value(key)
        values[key] = value
        lines.append(f"{key}={value}")

    password = values.get("POSTGRES_PASSWORD")
    if password:
        for index, line in enumerate(lines):
            if line.startswith("POSTGRES_CORE_DSN="):
                lines[index] = line.replace("change-me", password, 1)

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite an existing .env")
    args = parser.parse_args()

    if TARGET.exists() and not args.force:
        print(f"{TARGET.name} already exists; keeping it (use --force to regenerate)")
        return 0

    TARGET.write_text(render(EXAMPLE.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.name} with random local secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
