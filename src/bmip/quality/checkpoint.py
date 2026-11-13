"""Scope-aware checkpoint used by the CLI, the Prefect flow, and tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bmip.common.config import Settings
from bmip.quality.runner import CheckpointReport, run_checkpoint, to_frame
from bmip.quality.suites import load_suites

SILVER_DATASETS = (
    "silver.market_ohlcv_1m",
    "silver.market_trades",
    "silver.social_post",
    "silver.social_sentiment",
)
GOLD_DATASETS = ("gold.mart_market", "gold.mart_sentiment", "gold.mart_ml")
ALL_DATASETS = SILVER_DATASETS + GOLD_DATASETS

ROOT = Path(__file__).resolve().parents[3]


def suites_for(scope: str = "all", directory: Path | None = None):
    suites = load_suites(directory or ROOT / "gx" / "suites")
    if scope == "all":
        return suites
    return [suite for suite in suites if suite.dataset.startswith(f"{scope}.")]


def datasets_for(scope: str = "all") -> tuple[str, ...]:
    if scope == "silver":
        return SILVER_DATASETS
    if scope == "gold":
        # Gold suites compare against silver (lag rule), so load one reference.
        return GOLD_DATASETS + ("silver.market_ohlcv_1m",)
    return ALL_DATASETS


def load_dataset(settings: Settings, identifier: str):
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    catalog = load_rest_catalog(settings)
    table = table_with_host_io(catalog, settings, identifier)
    return to_frame(table.scan().to_arrow().to_pylist())


def load_gold_candidate(duckdb_path: str | Path, identifier: str):
    """Read a gold mart from the dbt DuckDB target before it is published."""
    import duckdb

    schema, table = identifier.split(".")
    connection = duckdb.connect(str(duckdb_path))
    try:
        arrow = connection.execute(f'select * from "{schema}"."{table}"').to_arrow_table()
    finally:
        connection.close()
    return to_frame(arrow.to_pylist())


def load_datasets(
    settings: Settings,
    scope: str = "all",
    *,
    duckdb_path: str | Path | None = None,
) -> dict[str, Any]:
    datasets: dict[str, Any] = {}
    for identifier in datasets_for(scope):
        try:
            if duckdb_path is not None and identifier.startswith("gold."):
                datasets[identifier] = load_gold_candidate(duckdb_path, identifier)
            else:
                datasets[identifier] = load_dataset(settings, identifier)
        except Exception:
            # A missing table is reported by the suite as a critical failure.
            continue
    return datasets


def run_scope(
    settings: Settings,
    *,
    scope: str = "all",
    warning_only: bool = False,
    commit: str = "nogit",
    owner: str = "vio",
    duckdb_path: str | Path | None = None,
) -> CheckpointReport:
    return run_checkpoint(
        load_datasets(settings, scope, duckdb_path=duckdb_path),
        suites_for(scope),
        commit=commit,
        owner=owner,
        warning_only=warning_only,
    )
