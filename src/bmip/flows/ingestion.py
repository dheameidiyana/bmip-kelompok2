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


@task(name="build-silver-social", retries=1, retry_delay_seconds=30)
def build_silver_social_task() -> dict[str, Any]:
    from bmip.transform.social_pipeline import build_silver_social

    return build_silver_social(get_settings())


@task(name="quality-silver", retries=0)
def quality_silver_task() -> dict[str, Any]:
    from bmip.quality.checkpoint import run_scope

    report = run_scope(get_settings(), scope="silver", warning_only=False)
    return {
        "status": report.status,
        "critical_failures": len(report.critical_failures),
        "suites": len(report.suites),
    }


@task(name="quality-gold", retries=0)
def quality_gold_task(duckdb_path: str | None = None) -> dict[str, Any]:
    from bmip.quality.checkpoint import run_scope

    path = Path(duckdb_path) if duckdb_path else ROOT / "dbt" / "target" / "bmip.duckdb"
    report = run_scope(
        get_settings(), scope="gold", warning_only=False, duckdb_path=path
    )
    return {
        "status": report.status,
        "critical_failures": len(report.critical_failures),
        "suites": len(report.suites),
    }


@task(name="publish-gold", retries=1, retry_delay_seconds=30)
def publish_gold_task(
    duckdb_path: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    from bmip.transform.gold import GoldWriter

    settings = get_settings()
    path = Path(duckdb_path) if duckdb_path else ROOT / "dbt" / "target" / "bmip.duckdb"
    writer = GoldWriter(settings)
    writer.ensure_tables()
    results = writer.publish_from_duckdb(
        path,
        start=_ts(start),
        end=_ts(end),
    )
    return {
        "published": [result.as_dict() for result in results],
        "counts": writer.counts(),
    }


@task(name="publish-serving", retries=1, retry_delay_seconds=30)
def publish_serving_task(
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Gold -> PostgreSQL serving tables. Idempotent by primary key."""
    from bmip.serving.loader import load_serving

    result = load_serving(
        get_settings(),
        start=_ts(start),
        end=_ts(end),
    )
    return result.as_dict()


def _ts(value: str | None):
    if not value:
        return None
    from datetime import UTC, datetime

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@flow(name="transform-gold", log_prints=True)
def transform_gold_flow(
    duckdb_path: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Silver gate -> gold build -> gold gate -> Iceberg publish.

    A critical silver failure raises before the gold models are built, so bad
    data never reaches ``gold.mart_*`` in the lakehouse. ``start``/``end`` scope
    a backfill to the partitions inside the range.
    """
    configure_logging()
    social_silver = build_silver_social_task()
    silver_build = transform_silver_task(select="staging intermediate silver")
    silver_quality = quality_silver_task()
    gold_build = transform_silver_task(select="marts")
    gold_quality = quality_gold_task(duckdb_path=duckdb_path)
    published = publish_gold_task(
        duckdb_path=duckdb_path,
        start=start,
        end=end,
    )
    serving = publish_serving_task(start=start, end=end)
    return {
        "social_silver": social_silver,
        "silver_build": silver_build,
        "silver_quality": silver_quality,
        "gold_build": gold_build,
        "gold_quality": gold_quality,
        "published": published,
        "serving": serving,
    }


@flow(name="backfill-gold", log_prints=True)
def backfill_gold_flow(
    start: str,
    end: str,
    duckdb_path: str | None = None,
) -> dict[str, Any]:
    """Rebuild gold and republish only the partitions inside [start, end).

    dbt recomputes the marts from silver; the publisher filters rows by
    ``window_start`` and overwrites only the affected ``event_date`` partitions,
    so replaying a range is idempotent and does not touch other days.
    """
    configure_logging()
    if start >= end:
        raise ValueError("backfill start must be before end")
    result = transform_gold_flow(duckdb_path=duckdb_path, start=start, end=end)
    return {"range": {"start": start, "end": end}, **result}
