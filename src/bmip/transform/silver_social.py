"""PyIceberg writers for silver social posts and sentiment (W1-C).

Both tables are partitioned by ``event_date`` and written with a partition
overwrite, so a replay or a late post corrects the affected day instead of
appending duplicates. Inside a partition the merge key is ``post_key`` and the
newest ``ingest_ts`` wins (workplan W1-C item 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pyarrow as pa
from pyiceberg.catalog import Catalog
from pyiceberg.expressions import EqualTo
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DateType,
    DoubleType,
    ListType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.iceberg import (
    date_filter,
    ensure_namespace,
    load_rest_catalog,
    table_with_host_io,
)
from bmip.transform.social import SocialPost, utc_datetime

log = get_logger(__name__)

SILVER_NAMESPACE = "silver"
POSTS_TABLE = "silver.social_post"
SENTIMENT_TABLE = "silver.social_sentiment"

POSTS_LOCATION = "s3://lakehouse/warehouse/silver.db/social_post"
SENTIMENT_LOCATION = "s3://lakehouse/warehouse/silver.db/social_sentiment"


def _iceberg_posts_schema() -> Schema:
    return Schema(
        NestedField(1, "post_key", StringType(), required=True),
        NestedField(2, "author_key", StringType(), required=True),
        NestedField(3, "event_ts", TimestamptzType(), required=True),
        NestedField(4, "ingest_ts", TimestamptzType(), required=True),
        NestedField(5, "lang", StringType(), required=False),
        NestedField(6, "text", StringType(), required=True),
        NestedField(
            7,
            "hashtags",
            ListType(element_id=8, element_type=StringType(), element_required=False),
            required=False,
        ),
        NestedField(9, "like_count", LongType(), required=True),
        NestedField(10, "repost_count", LongType(), required=True),
        NestedField(11, "reply_count", LongType(), required=True),
        NestedField(12, "quote_count", LongType(), required=True),
        NestedField(13, "source", StringType(), required=True),
        NestedField(14, "payload_hash", StringType(), required=True),
        NestedField(15, "event_date", DateType(), required=True),
        NestedField(16, "updated_at", TimestamptzType(), required=True),
    )


def _iceberg_sentiment_schema() -> Schema:
    return Schema(
        NestedField(1, "post_key", StringType(), required=True),
        NestedField(2, "event_ts", TimestamptzType(), required=True),
        NestedField(3, "window_start", TimestamptzType(), required=True),
        NestedField(4, "ingest_ts", TimestamptzType(), required=True),
        NestedField(5, "sentiment_score", DoubleType(), required=True),
        NestedField(6, "sentiment_pos", DoubleType(), required=True),
        NestedField(7, "sentiment_neu", DoubleType(), required=True),
        NestedField(8, "sentiment_neg", DoubleType(), required=True),
        NestedField(9, "sentiment_label", StringType(), required=True),
        NestedField(10, "sentiment_model_version", StringType(), required=True),
        NestedField(11, "event_date", DateType(), required=True),
        NestedField(12, "updated_at", TimestamptzType(), required=True),
    )


def _field(name: str, data_type: pa.DataType, nullable: bool = False) -> pa.Field:
    return pa.field(name, data_type, nullable=nullable)


POSTS_ARROW_SCHEMA = pa.schema(
    [
        _field("post_key", pa.large_string()),
        _field("author_key", pa.large_string()),
        _field("event_ts", pa.timestamp("us", tz="UTC")),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
        _field("lang", pa.large_string(), nullable=True),
        _field("text", pa.large_string()),
        _field("hashtags", pa.list_(pa.large_string()), nullable=True),
        _field("like_count", pa.int64()),
        _field("repost_count", pa.int64()),
        _field("reply_count", pa.int64()),
        _field("quote_count", pa.int64()),
        _field("source", pa.large_string()),
        _field("payload_hash", pa.large_string()),
        _field("event_date", pa.date32()),
        _field("updated_at", pa.timestamp("us", tz="UTC")),
    ]
)

SENTIMENT_ARROW_SCHEMA = pa.schema(
    [
        _field("post_key", pa.large_string()),
        _field("event_ts", pa.timestamp("us", tz="UTC")),
        _field("window_start", pa.timestamp("us", tz="UTC")),
        _field("ingest_ts", pa.timestamp("us", tz="UTC")),
        _field("sentiment_score", pa.float64()),
        _field("sentiment_pos", pa.float64()),
        _field("sentiment_neu", pa.float64()),
        _field("sentiment_neg", pa.float64()),
        _field("sentiment_label", pa.large_string()),
        _field("sentiment_model_version", pa.large_string()),
        _field("event_date", pa.date32()),
        _field("updated_at", pa.timestamp("us", tz="UTC")),
    ]
)


def post_row(post: SocialPost) -> dict[str, Any]:
    return {
        "post_key": post.post_key,
        "author_key": post.author_key,
        "event_ts": post.event_ts,
        "ingest_ts": post.ingest_ts,
        "lang": post.lang,
        "text": post.text,
        "hashtags": list(post.hashtags),
        "like_count": post.like_count,
        "repost_count": post.repost_count,
        "reply_count": post.reply_count,
        "quote_count": post.quote_count,
        "source": post.source,
        "payload_hash": post.payload_hash,
        "event_date": post.event_date,
        "updated_at": post.updated_at,
    }


def sentiment_row(post: SocialPost) -> dict[str, Any]:
    sentiment = post.sentiment
    return {
        "post_key": post.post_key,
        "event_ts": post.event_ts,
        "window_start": post.window_start,
        "ingest_ts": post.ingest_ts,
        "sentiment_score": sentiment.compound,
        "sentiment_pos": sentiment.positive,
        "sentiment_neu": sentiment.neutral,
        "sentiment_neg": sentiment.negative,
        "sentiment_label": sentiment.label,
        "sentiment_model_version": sentiment.model_version,
        "event_date": post.event_date,
        "updated_at": post.updated_at,
    }


def merge_rows(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    key: str = "post_key",
) -> list[dict[str, Any]]:
    """Newest ingest_ts wins inside a partition; output order is deterministic."""
    merged: dict[str, dict[str, Any]] = {}
    for row in [*existing, *incoming]:
        current = merged.get(row[key])
        if current is None or utc_datetime(row["ingest_ts"]) >= utc_datetime(
            current["ingest_ts"]
        ):
            merged[row[key]] = row
    return sorted(merged.values(), key=lambda row: (row["event_ts"], row[key]))


@dataclass(frozen=True)
class SocialWriteStats:
    posts: int
    sentiment_rows: int
    duplicates: int
    partitions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "posts": self.posts,
            "sentiment_rows": self.sentiment_rows,
            "duplicates": self.duplicates,
            "partitions": self.partitions,
        }


class SocialWriter:
    def __init__(self, settings: Settings, catalog: Catalog | None = None) -> None:
        self.settings = settings
        self.catalog = catalog or load_rest_catalog(settings)

    def ensure_tables(self) -> None:
        ensure_namespace(self.catalog, SILVER_NAMESPACE)
        self.catalog.create_table_if_not_exists(
            POSTS_TABLE,
            schema=_iceberg_posts_schema(),
            location=POSTS_LOCATION,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=15,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )
        self.catalog.create_table_if_not_exists(
            SENTIMENT_TABLE,
            schema=_iceberg_sentiment_schema(),
            location=SENTIMENT_LOCATION,
            partition_spec=PartitionSpec(
                PartitionField(
                    source_id=11,
                    field_id=1000,
                    transform=IdentityTransform(),
                    name="event_date",
                )
            ),
        )

    def _table(self, identifier: str):
        return table_with_host_io(self.catalog, self.settings, identifier)

    def write(self, posts: list[SocialPost]) -> SocialWriteStats:
        if not posts:
            return SocialWriteStats(0, 0, 0, 0)

        incoming_posts = [post_row(post) for post in posts]
        incoming_sentiment = [sentiment_row(post) for post in posts]
        by_date: dict[date, list[SocialPost]] = {}
        for post in posts:
            by_date.setdefault(post.event_date, []).append(post)

        posts_table = self._table(POSTS_TABLE)
        sentiment_table = self._table(SENTIMENT_TABLE)
        duplicates = 0
        for event_date in sorted(by_date):
            partition_posts = [
                row for row in incoming_posts if row["event_date"] == event_date
            ]
            partition_sentiment = [
                row for row in incoming_sentiment if row["event_date"] == event_date
            ]
            existing_posts = (
                posts_table.scan(row_filter=EqualTo("event_date", event_date))
                .to_arrow()
                .to_pylist()
            )
            existing_sentiment = (
                sentiment_table.scan(row_filter=EqualTo("event_date", event_date))
                .to_arrow()
                .to_pylist()
            )
            merged_posts = merge_rows(existing_posts, partition_posts)
            merged_sentiment = merge_rows(existing_sentiment, partition_sentiment)
            duplicates += max(
                len(existing_posts) + len(partition_posts) - len(merged_posts), 0
            )
            posts_table.overwrite(
                pa.Table.from_pylist(merged_posts, schema=POSTS_ARROW_SCHEMA),
                overwrite_filter=EqualTo("event_date", event_date),
            )
            sentiment_table.overwrite(
                pa.Table.from_pylist(merged_sentiment, schema=SENTIMENT_ARROW_SCHEMA),
                overwrite_filter=EqualTo("event_date", event_date),
            )

        log.info(
            "silver social partition overwrite",
            extra={
                "ctx_posts": len(incoming_posts),
                "ctx_partitions": len(by_date),
                "ctx_duplicates": duplicates,
            },
        )
        return SocialWriteStats(
            posts=len(incoming_posts),
            sentiment_rows=len(incoming_sentiment),
            duplicates=duplicates,
            partitions=len(by_date),
        )

    def fetch_posts(
        self,
        *,
        dates: list[date] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        table = self._table(POSTS_TABLE)
        scan = table.scan(row_filter=date_filter(dates)) if dates else table.scan()
        rows = scan.to_arrow().to_pylist()
        rows.sort(key=lambda row: (row["event_ts"], row["post_key"]))
        return rows[:limit] if limit else rows

    def fetch_sentiment(
        self,
        *,
        dates: list[date] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        table = self._table(SENTIMENT_TABLE)
        scan = table.scan(row_filter=date_filter(dates)) if dates else table.scan()
        rows = scan.to_arrow().to_pylist()
        rows.sort(key=lambda row: (row["event_ts"], row["post_key"]))
        return rows[:limit] if limit else rows

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for identifier in (POSTS_TABLE, SENTIMENT_TABLE):
            try:
                result[identifier] = len(self._table(identifier).scan().to_arrow())
            except Exception as exc:
                log.warning(
                    "social count failed",
                    extra={"ctx_table": identifier, "ctx_error": str(exc)},
                )
                result[identifier] = 0
        return result


@dataclass(frozen=True)
class SocialFreshness:
    observed_at: datetime
    latest_event_ts: datetime | None
    latest_ingest_ts: datetime | None
    ingest_lag_seconds: float | None
    age_seconds: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at.isoformat().replace("+00:00", "Z"),
            "latest_event_ts": (
                self.latest_event_ts.isoformat().replace("+00:00", "Z")
                if self.latest_event_ts
                else None
            ),
            "latest_ingest_ts": (
                self.latest_ingest_ts.isoformat().replace("+00:00", "Z")
                if self.latest_ingest_ts
                else None
            ),
            "ingest_lag_seconds": self.ingest_lag_seconds,
            "age_seconds": self.age_seconds,
        }


def compute_social_freshness(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> SocialFreshness:
    observed_at = now or datetime.now(UTC)
    if not rows:
        return SocialFreshness(observed_at, None, None, None, None)
    latest = max(rows, key=lambda row: utc_datetime(row["event_ts"]))
    latest_event_ts = utc_datetime(latest["event_ts"])
    latest_ingest_ts = utc_datetime(latest["ingest_ts"])
    return SocialFreshness(
        observed_at=observed_at,
        latest_event_ts=latest_event_ts,
        latest_ingest_ts=latest_ingest_ts,
        ingest_lag_seconds=max(
            (latest_ingest_ts - latest_event_ts).total_seconds(), 0.0
        ),
        age_seconds=max((observed_at - latest_event_ts).total_seconds(), 0.0),
    )
