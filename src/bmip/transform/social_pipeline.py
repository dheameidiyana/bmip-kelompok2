"""Bronze social -> silver social pipeline (W1-C).

Kept out of ``transform.cli`` so the W1-B market processor keeps its exact
interface. This module owns the silver social boundary: contract checks, PII
pseudonymization, deduplication, VADER scoring, and the Iceberg write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.iceberg import load_rest_catalog, table_with_host_io
from bmip.transform.silver_social import SocialWriter
from bmip.transform.social import (
    SocialPost,
    dedupe_posts,
    parse_social_post,
)

log = get_logger(__name__)

BRONZE_SOCIAL_TABLE = "bronze.social_post_raw"


def read_bronze_social(settings: Settings) -> list[dict[str, Any]]:
    catalog = load_rest_catalog(settings)
    table = table_with_host_io(catalog, settings, BRONZE_SOCIAL_TABLE)
    rows = table.scan().to_arrow().to_pylist()
    rows.sort(key=lambda row: (row["created_at"], row["post_uri"]))
    return rows


def build_silver_social(
    settings: Settings,
    *,
    rows: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Transform bronze social rows into silver posts and sentiment."""
    bronze_rows = read_bronze_social(settings) if rows is None else rows
    stamp = now or datetime.now(UTC)

    posts: list[SocialPost] = []
    rejected: list[dict[str, str]] = []
    for row in bronze_rows:
        post, reason = parse_social_post(
            row,
            salt=settings.pii_hash_salt,
            now=stamp,
            model_version=settings.sentiment_model_version,
        )
        if post is None:
            rejected.append(
                {
                    "reason": str(reason),
                    "post_key_hint": str(row.get("payload_hash") or "")[:12],
                }
            )
            continue
        posts.append(post)

    unique, duplicates = dedupe_posts(posts)
    writer = SocialWriter(settings)
    writer.ensure_tables()
    stats = writer.write(unique)

    result = {
        "bronze_rows": len(bronze_rows),
        "accepted": len(unique),
        "rejected": len(rejected),
        "duplicates": duplicates,
        "written": stats.as_dict(),
        "counts": writer.counts(),
    }
    log.info("silver social build finished", extra={"ctx_result": result})
    return result
