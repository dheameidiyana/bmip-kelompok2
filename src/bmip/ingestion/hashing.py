"""Deterministic hashing helpers used by contracts, bronze, and the ledger."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def canonical_json(value: Any) -> str:
    """Return a stable JSON representation with sorted keys and no whitespace."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def payload_hash(value: Any) -> str:
    """SHA-256 of the canonical source payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def records_checksum(payload_hashes: Iterable[str]) -> str:
    """Order-independent checksum over the payload hashes in a batch."""
    ordered = "\n".join(sorted(payload_hashes))
    return hashlib.sha256(ordered.encode("utf-8")).hexdigest()
