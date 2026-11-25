"""API key hashing and role resolution (W2-C).

Keys are formatted ``bmip_<key_id>_<secret>`` so the API can look up one row
without scanning every hash. Only an Argon2 hash is stored; the plaintext is
shown once when the key is seeded or rotated.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

PREFIX = "bmip_"
ROLES = ("viewer", "operator", "admin")
ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}

_hasher = PasswordHasher()


@dataclass(frozen=True)
class ApiKey:
    key_id: str
    role: str
    owner: str


def _pepper(secret: str, salt: str) -> str:
    return f"{secret}{salt}"


def hash_secret(secret: str, salt: str = "") -> str:
    return _hasher.hash(_pepper(secret, salt))


def verify_secret(secret: str, key_hash: str, salt: str = "") -> bool:
    try:
        return _hasher.verify(key_hash, _pepper(secret, salt))
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_key(
    role: str,
    owner: str,
    key_id: str | None = None,
    *,
    salt: str = "",
) -> tuple[str, ApiKey, str]:
    """Return (plaintext, identity, hash). The plaintext is never stored."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    identifier = key_id or secrets.token_hex(4)
    secret = secrets.token_urlsafe(24)
    plaintext = f"{PREFIX}{identifier}_{secret}"
    return plaintext, ApiKey(identifier, role, owner), hash_secret(secret, salt)


def parse_key(raw: str) -> tuple[str, str] | None:
    if not raw or not raw.startswith(PREFIX):
        return None
    remainder = raw[len(PREFIX) :]
    key_id, separator, secret = remainder.partition("_")
    if not separator or not key_id or not secret:
        return None
    return key_id, secret


def resolve_key(
    connection: Any,
    raw: str,
    *,
    salt: str = "",
) -> ApiKey | None:
    parsed = parse_key(raw)
    if parsed is None:
        return None
    key_id, secret = parsed
    row = connection.execute(
        """
        SELECT key_id, key_hash, role, owner
        FROM ops.api_keys
        WHERE key_id = %s AND revoked_at IS NULL
        """,
        (key_id,),
    ).fetchone()
    if row is None:
        return None
    if not verify_secret(secret, str(row["key_hash"]), salt):
        return None
    try:
        connection.execute(
            "UPDATE ops.api_keys SET last_used_at = now() WHERE key_id = %s",
            (key_id,),
        )
        connection.commit()
    except Exception:  # noqa: BLE001 - read-only replica may not have UPDATE
        try:
            connection.rollback()
        except Exception:  # noqa: BLE001 - keep auth working even if rollback fails
            pass
    return ApiKey(str(row["key_id"]), str(row["role"]), str(row["owner"]))
