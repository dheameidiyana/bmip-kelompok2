"""Tests for the W1-A smoke acceptance helpers."""

from __future__ import annotations

from bmip.ingestion.smoke import accepted_statuses, counts_match, ledger_rows_ok


def test_accepted_statuses() -> None:
    assert accepted_statuses("succeeded", "skipped_identical")
    assert accepted_statuses("skipped_identical", "skipped_identical")
    assert not accepted_statuses("succeeded", "succeeded")
    assert not accepted_statuses("failed", "skipped_identical")
    assert not accepted_statuses(None, "skipped_identical")


def test_counts_match() -> None:
    minimums = {"market": 3, "social": 2}
    assert counts_match({"market": 3, "social": 2}, {"market": 3, "social": 2}, minimums)
    assert not counts_match({"market": 3, "social": 2}, {"market": 4, "social": 2}, minimums)
    assert not counts_match({"market": 2, "social": 2}, {"market": 2, "social": 2}, minimums)


def test_ledger_rows_ok() -> None:
    expected = {"batch-a", "batch-b"}
    rows = [
        {"batch_id": "batch-a", "checksum": "a" * 64, "row_count": 3, "status": "succeeded"},
        {
            "batch_id": "batch-b",
            "checksum": "b" * 64,
            "row_count": 2,
            "status": "skipped_identical",
        },
    ]
    assert ledger_rows_ok(rows, expected)
    assert not ledger_rows_ok(rows[:1], expected)
    assert not ledger_rows_ok([], set())
    bad = [dict(rows[0], checksum=""), dict(rows[1])]
    assert not ledger_rows_ok(bad, expected)
