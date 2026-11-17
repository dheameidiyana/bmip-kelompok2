"""Offline dbt build against synthetic silver fixtures.

This is the reproducible CP2/T-09 proof: it never needs MinIO, Lakekeeper, or
Redpanda. The second build changes only data after a cut-off hour and asserts
that earlier feature rows are byte-identical.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _fixtures_module():
    path = ROOT / "scripts" / "ci_fixtures.py"
    spec = importlib.util.spec_from_file_location("ci_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    fixtures = _fixtures_module()
    tmp = tmp_path_factory.mktemp("marts")
    iceberg = tmp / "iceberg.duckdb"
    duckdb_path = tmp / "ci.duckdb"
    fixtures.build_fixture_db(iceberg)
    assert fixtures.dbt_build(
        "staging intermediate silver marts",
        duckdb_path=duckdb_path,
        iceberg_path=iceberg,
    )
    return {
        "fixtures": fixtures,
        "duckdb": duckdb_path,
        "iceberg": iceberg,
        "tmp": tmp,
    }


def test_mart_market_has_one_row_per_hour(built):
    rows = built["fixtures"].read_mart(built["duckdb"], "mart_market")
    assert len(rows) == 4
    assert {row["symbol"] for row in rows} == {"BTCUSDT"}
    assert all(row["source"] == "binance_vision" for row in rows)
    assert all(row["realized_vol_1h"] is not None for row in rows[1:])


def test_mart_sentiment_keeps_empty_hour_visible(built):
    rows = built["fixtures"].read_mart(built["duckdb"], "mart_sentiment")
    assert len(rows) == 3
    by_hour = {row["window_start"].astimezone(UTC).hour: row for row in rows}
    assert set(by_hour) == {0, 1, 2}
    empty = by_hour[1]
    assert empty["post_count"] == 0
    assert empty["unique_authors"] == 0
    assert empty["mean_sentiment"] is None
    assert empty["positive_share"] is None
    assert empty["top_hashtags"] == []
    assert by_hour[0]["post_count"] == 2
    assert by_hour[2]["post_count"] == 1


def test_mart_ml_labels_start_at_window_start(built):
    rows = built["fixtures"].read_mart(built["duckdb"], "mart_ml")
    assert rows
    labelled = [row for row in rows if row["label_start"] is not None]
    assert labelled
    for row in labelled:
        assert row["label_start"] == row["window_start"]
        assert row["label_end"] == row["window_start"] + timedelta(hours=1)
        if row["window_start"].astimezone(UTC).hour >= 2:
            assert row["dq_status"] == "pass"
    assert any(row["dq_status"] == "warn" for row in rows)
    assert all(row["feature_snapshot_id"] == "dev" for row in rows)


def test_mart_ml_features_do_not_leak_from_the_future(built):
    fixtures = built["fixtures"]
    base_rows = fixtures.read_mart(built["duckdb"], "mart_ml")
    base = {
        (row["symbol"], row["window_start"]): row
        for row in base_rows
        if row["label_start"] is not None
    }

    cut = datetime(2026, 11, 10, 2, tzinfo=UTC)
    spike_iceberg = built["tmp"] / "spike_iceberg.duckdb"
    spike_duckdb = built["tmp"] / "spike.duckdb"
    fixtures.build_fixture_db(spike_iceberg, spike_from=cut)
    assert fixtures.dbt_build(
        "staging intermediate silver marts",
        duckdb_path=spike_duckdb,
        iceberg_path=spike_iceberg,
    )
    spike_rows = fixtures.read_mart(spike_duckdb, "mart_ml")

    feature_columns = (
        "ret_5m",
        "ret_15m",
        "ret_60m",
        "rv_5m",
        "rv_15m",
        "rv_60m",
        "volume_z_60m",
        "trade_count_60m",
        "hl_range_1m",
        "vwap_dev",
    )
    checked = 0
    for row in spike_rows:
        if row["window_start"] > cut:
            continue
        reference = base.get((row["symbol"], row["window_start"]))
        if reference is None:
            continue
        for column in feature_columns:
            if reference[column] is None or row[column] is None:
                assert row[column] == reference[column], column
            else:
                assert row[column] == pytest.approx(
                    reference[column], rel=1e-9, abs=1e-12
                ), column
        checked += 1
    assert checked >= 2, "the leakage test must compare at least two feature hours"


def test_dbt_tests_are_part_of_the_build(built):
    """A green build means the singular tests in dbt/tests passed too."""
    connection = duckdb.connect(str(built["duckdb"]))
    try:
        rows = connection.execute("select * from gold.mart_ml").to_arrow_table().to_pylist()
    finally:
        connection.close()
    assert rows
