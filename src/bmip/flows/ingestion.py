"""Scheduled ingestion and transformation flows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from prefect import flow, task

from bmip.common.config import get_settings
from bmip.common.logging import configure_logging
from bmip.ingestion.feeds import (
    iter_bluesky_search,
    iter_static_social,
    watermark_since,
)
from bmip.ingestion.ledger import get_watermark
from bmip.ingestion.pipeline import run_social_batch

ROOT = Path(__file__).resolve().parents[3]


@task(
    name="harvest-social",
    retries=3,
    retry_delay_seconds=[60, 300, 900],
)
def harvest_social_task(max_pages: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    if settings.social_feed == "replay":
        items = list(iter_static_social(Path(settings.social_replay_file)))
    else:
        watermark = get_watermark(settings.postgres_dsn, "bluesky")
        items = list(
            iter_bluesky_search(
                settings.social_query,
                limit=100,
                max_pages=max_pages or settings.social_max_pages,
                since=watermark_since(watermark),
                base_url=settings.bluesky_base_url,
                cache_dir=Path("data/cache/bluesky"),
            )
        )
    result = run_social_batch(settings, items)
    return result.as_dict()


@task(
    name="dbt-build",
    retries=2,
    retry_delay_seconds=[30, 120],
)
def transform_silver_task(select: str | None = None) -> dict[str, Any]:
    load_dotenv(ROOT / ".env")
    target = ROOT / "dbt" / "target"
    target.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DBT_DUCKDB_PATH", str(target / "bmip.duckdb"))

    from dbt.cli.main import dbtRunner

    command = [
        "build",
        "--project-dir",
        str(ROOT / "dbt"),
        "--profiles-dir",
        str(ROOT / "dbt"),
    ]
    if select:
        command.extend(["--select", select])
    result = dbtRunner().invoke(command)
    if not result.success:
        detail = str(result.exception) if result.exception is not None else "dbt build failed"
        raise RuntimeError(detail)
    return {"success": True, "select": select}


@flow(name="harvest-social", log_prints=True)
def harvest_social_flow(max_pages: int | None = None) -> dict[str, Any]:
    configure_logging()
    return harvest_social_task(max_pages=max_pages)


@flow(name="transform-silver", log_prints=True)
def transform_silver_flow(select: str | None = None) -> dict[str, Any]:
    configure_logging()
    return transform_silver_task(select=select)
