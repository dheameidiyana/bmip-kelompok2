#!/usr/bin/env python3
"""Write Traefik's users file from BMIP_UI_USERS.

Format: ``user:password,user2:password2``. Only SHA-1 hashes are written, so the
file can be mounted read-only and never contains a plaintext password.
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "deploy" / "traefik" / "users.htpasswd"


def main() -> int:
    load_dotenv(ROOT / ".env")
    raw = os.getenv("BMIP_UI_USERS", "").strip()
    if not raw:
        print("BMIP_UI_USERS is empty; leaving the users file untouched")
        return 0
    lines = []
    for item in raw.split(","):
        user, separator, password = item.partition(":")
        if not separator or not user or not password:
            continue
        digest = hashlib.sha1(password.encode("utf-8")).digest()
        lines.append(f"{user}:{{SHA}}{base64.b64encode(digest).decode('ascii')}")
    if not lines:
        print("BMIP_UI_USERS has no valid user:password entries")
        return 1
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)} with {len(lines)} user(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
