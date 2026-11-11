"""Pure acceptance helpers for the W1-A end-to-end smoke gate."""

from __future__ import annotations

from typing import Any

INGEST_OK = {"succeeded", "skipped_identical"}


def accepted_statuses(first: str | None, second: str | None) -> bool:
    return first in INGEST_OK and second == "skipped_identical"


def counts_match(
    before: dict[str, int],
    after: dict[str, int],
    minimums: dict[str, int],
) -> bool:
    return before == after and all(
        after.get(table, 0) >= minimum for table, minimum in minimums.items()
    )


def ledger_rows_ok(rows: list[dict[str, Any]], expected_ids: set[str]) -> bool:
    present = {str(row.get("batch_id")) for row in rows}
    return bool(expected_ids) and expected_ids <= present and all(
        bool(row.get("checksum"))
        and int(row.get("row_count") or 0) > 0
        and row.get("status") in INGEST_OK
        for row in rows
    )
