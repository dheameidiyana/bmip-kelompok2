"""Unit tests for the C3-C lifecycle helpers (no Iceberg service needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pyarrow as pa

from bmip.lifecycle import _split_location, apply_retention, retention_plan


class _FakeInspect:
    def __init__(self, table: _FakeTable) -> None:
        self.table = table

    def files(self):
        today = datetime.now(UTC).date()
        return pa.Table.from_pylist(
            [
                {
                    "content": 0,
                    "partition": {"event_date": today - timedelta(days=40)},
                    "record_count": 1,
                },
                {
                    "content": 0,
                    "partition": {"event_date": today - timedelta(days=1)},
                    "record_count": 2,
                },
            ]
        )


class _FakeTable:
    def __init__(self) -> None:
        today = datetime.now(UTC).date()
        self.arrow = pa.table(
            {
                "id": pa.array([1, 2, 3], type=pa.int64()),
                "event_date": pa.array(
                    [today - timedelta(days=40), today - timedelta(days=1), today],
                    type=pa.date32(),
                ),
            }
        )
        self.deleted = None
        self.inspect = _FakeInspect(self)

    def scan(self):
        return self

    def to_arrow(self):
        return self.arrow

    def delete(self, delete_filter):
        from pyiceberg.expressions import LessThan

        assert isinstance(delete_filter, LessThan)
        self.deleted = delete_filter
        today = datetime.now(UTC).date()
        cutoff = today - timedelta(days=14)
        mask = [value >= cutoff for value in self.arrow["event_date"].to_pylist()]
        self.arrow = self.arrow.filter(pa.array(mask))


def test_split_location() -> None:
    assert _split_location("s3://lakehouse/warehouse/gold.db/mart_ml") == (
        "lakehouse",
        "warehouse/gold.db/mart_ml",
    )


def test_retention_plan_counts_old_partitions() -> None:
    plan = retention_plan(_FakeTable(), days=14)
    assert plan["old_partitions"] == 1
    assert plan["old_rows"] == 1
    assert plan["cutoff"] == str(datetime.now(UTC).date() - timedelta(days=14))


def test_apply_retention_deletes_only_old_rows() -> None:
    table = _FakeTable()
    result = apply_retention(table, days=14)
    assert result["before_rows"] == 3
    assert result["after_rows"] == 2
    assert table.deleted is not None
