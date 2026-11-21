"""Column-name heuristics for the catalog's suggested classification.

The declared classification in ``ops.dataset_registry`` stays authoritative;
this module produces a second opinion so governance can spot a table whose
schema looks more sensitive than its label (Should item, workplan W2-C).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

PII_COLUMNS = {
    "did",
    "author_did",
    "handle",
    "author_handle",
    "display_name",
    "avatar",
    "email",
    "phone",
    "phone_number",
    "address",
    "ip",
    "ip_address",
    "post_text",
    "raw_text",
}

RESTRICTED_COLUMNS = {
    "uri",
    "raw_uri",
    "url",
    "raw_payload",
    "payload",
    "raw",
}

SENSITIVITY = ("public", "internal", "confidential", "restricted", "pii")


def _names(columns: Iterable[Any]) -> set[str]:
    names: set[str] = set()
    for column in columns or ():
        if isinstance(column, dict):
            value = column.get("name") or column.get("column_name")
        else:
            value = column
        if value:
            names.add(str(value).lower())
    return names


def suggest_classification(columns: Iterable[Any]) -> str:
    names = _names(columns)
    if names & PII_COLUMNS:
        return "pii"
    if names & RESTRICTED_COLUMNS:
        return "restricted"
    return "internal"


def reasons(columns: Iterable[Any]) -> list[str]:
    names = _names(columns)
    hits = sorted((names & PII_COLUMNS) | (names & RESTRICTED_COLUMNS))
    return [f"column {name!r} suggests sensitive data" for name in hits]
