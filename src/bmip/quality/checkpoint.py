"""Scope-aware checkpoint used by the CLI, the Prefect flow, and tests."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.quality.runner import CheckpointReport, run_checkpoint, to_frame
from bmip.quality.suites import load_suites

log = get_logger(__name__)

SILVER_DATASETS = (
    "silver.market_ohlcv_1m",
    "silver.market_trades",
    "silver.social_post",
    "silver.social_sentiment",
)
GOLD_DATASETS = ("gold.mart_market", "gold.mart_sentiment", "gold.mart_ml")
ALL_DATASETS = SILVER_DATASETS + GOLD_DATASETS

PROJECTIONS: dict[str, tuple[str, ...]] = {
    "silver.market_trades": ("symbol", "trade_id"),
}

LOAD_ATTEMPTS = 3
LOAD_RETRY_SECONDS = 2.0

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
        return GOLD_DATASETS + ("silver.market_ohlcv_1m",)
    return ALL_DATASETS


def load_dataset(settings: Settings, identifier: str, columns: tuple[str, ...] | None = None):
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    catalog = load_rest_catalog(settings)
    table = table_with_host_io(catalog, settings, identifier)
    scan = table.scan(selected_fields=columns) if columns else table.scan()
    return to_frame(scan.to_arrow().to_pylist())


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
        for attempt in range(1, LOAD_ATTEMPTS + 1):
            try:
                if duckdb_path is not None and identifier.startswith("gold."):
                    datasets[identifier] = load_gold_candidate(duckdb_path, identifier)
                else:
                    datasets[identifier] = load_dataset(
                        settings, identifier, PROJECTIONS.get(identifier)
                    )
                break
            except Exception as exc:
                log.warning(
                    "dataset load failed",
                    extra={
                        "ctx_dataset": identifier,
                        "ctx_attempt": attempt,
                        "ctx_error": f"{type(exc).__name__}: {exc}",
                    },
                )
                if attempt == LOAD_ATTEMPTS:
                    break
                time.sleep(LOAD_RETRY_SECONDS)
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
