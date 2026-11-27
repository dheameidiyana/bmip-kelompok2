"""Scheduled Iceberg lifecycle flow (C3-C)."""

from __future__ import annotations

from typing import Any

from prefect import flow, task

from bmip.common.config import get_settings
from bmip.common.logging import configure_logging
from bmip.lifecycle import run


@task(name="iceberg-lifecycle", retries=1, retry_delay_seconds=300)
def lifecycle_task(
    *,
    compact: bool,
    expire: bool,
    orphans: bool,
    apply_retention: list[str],
    as_of: str | None = None,
) -> dict[str, Any]:
    from datetime import date

    configure_logging(service="lifecycle")
    return run(
        get_settings(),
        compact=compact,
        expire=expire,
        orphans=orphans,
        retention_apply=set(apply_retention),
        as_of=date.fromisoformat(as_of) if as_of else None,
    )


@flow(name="compact_iceberg", log_prints=True)
def compact_iceberg_flow(
    compact: bool = True,
    expire: bool = True,
    orphans: bool = True,
    apply_retention: list[str] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Daily 01:00 UTC compaction, 7-day snapshot expiry, and retention.

    ``apply_retention`` defaults to an empty list so the scheduled job reports
    what would be deleted instead of deleting demo history. C3-D can enable one
    or more layers by updating the deployment parameter; the apply path is
    proven on the fixture table in every run.
    """
    return lifecycle_task(
        compact=compact,
        expire=expire,
        orphans=orphans,
        apply_retention=apply_retention or [],
        as_of=as_of,
    )
