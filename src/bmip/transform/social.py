"""Pure event-time transforms for silver social posts.

The silver boundary is where PII disappears (ADR-011): the raw post URI, author
DID, handle, display name, and avatar never reach this layer. Only salted
HMAC-SHA256 keys survive, plus the post text that sentiment scoring needs.
"""

from __future__ import annotations

import hashlib
import hmac
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any

from bmip.ingestion.hashing import payload_hash

ONE_HOUR = timedelta(hours=1)
MAX_FUTURE_SKEW = timedelta(minutes=2)
MAX_HASHTAGS = 20
TOP_HASHTAGS = 5
POSITIVE_THRESHOLD = 0.05
NEGATIVE_THRESHOLD = -0.05
FALLBACK_MODEL_VERSION = "vaderSentiment-3.3.2"


def utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp is not a datetime or string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def pseudonymize(value: str, salt: str) -> str:
    """Salted HMAC-SHA256 so the same source value maps to a stable key."""
    if not salt:
        raise ValueError("PII_HASH_SALT is required for pseudonymization")
    return hmac.new(salt.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Sentiment:
    compound: float
    positive: float
    neutral: float
    negative: float
    label: str
    model_version: str = FALLBACK_MODEL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.compound,
            "positive": self.positive,
            "neutral": self.neutral,
            "negative": self.negative,
            "label": self.label,
            "model_version": self.model_version,
        }


def classify(compound: float) -> str:
    if compound >= POSITIVE_THRESHOLD:
        return "positive"
    if compound <= NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


@lru_cache(maxsize=1)
def _analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


def score_sentiment(text: str, *, model_version: str | None = None) -> Sentiment:
    """VADER compound score, clamped to [-1, 1] as the contract requires."""
    version = model_version or FALLBACK_MODEL_VERSION
    scores = _analyzer().polarity_scores(text or "")
    compound = min(max(float(scores.get("compound", 0.0)), -1.0), 1.0)
    return Sentiment(
        compound=compound,
        positive=float(scores.get("pos", 0.0)),
        neutral=float(scores.get("neu", 0.0)),
        negative=float(scores.get("neg", 0.0)),
        label=classify(compound),
        model_version=version,
    )


@dataclass(frozen=True)
class SocialPost:
    post_key: str
    author_key: str
    event_ts: datetime
    ingest_ts: datetime
    lang: str | None
    text: str
    hashtags: tuple[str, ...]
    like_count: int
    repost_count: int
    reply_count: int
    quote_count: int
    source: str
    payload_hash: str
    sentiment: Sentiment
    updated_at: datetime

    @property
    def event_date(self) -> date:
        return self.event_ts.date()

    @property
    def window_start(self) -> datetime:
        return self.event_ts.replace(minute=0, second=0, microsecond=0)

    @property
    def engagement(self) -> int:
        return self.like_count + self.repost_count + self.reply_count


def _engagement(row: dict[str, Any], field: str) -> tuple[int, str | None]:
    value = row.get(field)
    if value is None:
        return 0, None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0, f"invalid_{field}"
    if parsed < 0:
        return 0, f"invalid_{field}"
    return parsed, None


def _hashtags(row: dict[str, Any]) -> tuple[str, ...]:
    raw = row.get("hashtags") or []
    if not isinstance(raw, list):
        return ()
    seen: list[str] = []
    for item in raw:
        value = str(item).strip().lower().lstrip("#")
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= MAX_HASHTAGS:
            break
    return tuple(seen)


def parse_social_post(
    row: dict[str, Any],
    *,
    salt: str,
    now: datetime | None = None,
    model_version: str | None = None,
) -> tuple[SocialPost | None, str | None]:
    """Validate one bronze row and return the pseudonymized silver record."""
    if not isinstance(row, dict):
        return None, "not_an_object"

    post_uri = str(row.get("post_uri") or "").strip()
    author_did = str(row.get("author_did") or "").strip()
    text = str(row.get("text") or "").strip()
    if not post_uri:
        return None, "missing_post_uri"
    if not author_did:
        return None, "missing_author_did"
    if not text:
        return None, "empty_text"

    try:
        event_ts = utc_datetime(row.get("created_at"))
    except (TypeError, ValueError):
        return None, "invalid_created_at"
    current = now or datetime.now(UTC)
    if event_ts > current + MAX_FUTURE_SKEW:
        return None, "future_created_at"

    try:
        ingest_ts = utc_datetime(row.get("ingest_ts") or current)
    except (TypeError, ValueError):
        return None, "invalid_ingest_ts"

    counts: dict[str, int] = {}
    for field in ("like_count", "repost_count", "reply_count", "quote_count"):
        value, reason = _engagement(row, field)
        if reason is not None:
            return None, reason
        counts[field] = value

    raw_payload_hash = str(row.get("payload_hash") or "")
    if len(raw_payload_hash) != 64:
        raw_payload_hash = payload_hash(row)

    return (
        SocialPost(
            post_key=pseudonymize(post_uri, salt),
            author_key=pseudonymize(author_did, salt),
            event_ts=event_ts,
            ingest_ts=ingest_ts,
            lang=str(row["lang"]) if row.get("lang") else None,
            text=text,
            hashtags=_hashtags(row),
            like_count=counts["like_count"],
            repost_count=counts["repost_count"],
            reply_count=counts["reply_count"],
            quote_count=counts["quote_count"],
            source=str(row.get("source") or "bluesky"),
            payload_hash=raw_payload_hash,
            sentiment=score_sentiment(text, model_version=model_version),
            updated_at=current,
        ),
        None,
    )


def dedupe_posts(posts: list[SocialPost]) -> tuple[list[SocialPost], int]:
    """One row per post_key; the newest ingest_ts wins the merge policy."""
    latest: dict[str, SocialPost] = {}
    for post in posts:
        current = latest.get(post.post_key)
        if current is None or post.ingest_ts >= current.ingest_ts:
            latest[post.post_key] = post
    duplicates = len(posts) - len(latest)
    ordered = sorted(latest.values(), key=lambda post: (post.event_ts, post.post_key))
    return ordered, duplicates


def merge_posts(existing: list[SocialPost], incoming: list[SocialPost]) -> list[SocialPost]:
    """Merge a partition snapshot with new rows; ingest_ts terbaru menang."""
    merged, _ = dedupe_posts([*existing, *incoming])
    return merged


@dataclass(frozen=True)
class SentimentHour:
    window_start: datetime
    post_count: int
    unique_authors: int
    mean_sentiment: float | None
    positive_share: float | None
    negative_share: float | None
    neutral_share: float | None
    total_likes: int
    total_reposts: int
    total_replies: int
    engagement_per_post: float | None
    top_hashtags: tuple[str, ...]
    sentiment_model_version: str
    updated_at: datetime

    @property
    def event_date(self) -> date:
        return self.window_start.date()

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_start": self.window_start,
            "post_count": self.post_count,
            "unique_authors": self.unique_authors,
            "mean_sentiment": self.mean_sentiment,
            "positive_share": self.positive_share,
            "negative_share": self.negative_share,
            "neutral_share": self.neutral_share,
            "total_likes": self.total_likes,
            "total_reposts": self.total_reposts,
            "total_replies": self.total_replies,
            "engagement_per_post": self.engagement_per_post,
            "top_hashtags": list(self.top_hashtags),
            "sentiment_model_version": self.sentiment_model_version,
            "updated_at": self.updated_at,
            "event_date": self.event_date,
        }


def _hour_series(start: datetime, end: datetime) -> list[datetime]:
    hours: list[datetime] = []
    current = start
    while current <= end:
        hours.append(current)
        current += ONE_HOUR
    return hours


def aggregate_sentiment_hourly(
    posts: list[SocialPost],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    updated_at: datetime | None = None,
) -> list[SentimentHour]:
    """Hourly sentiment aggregate; empty hours stay visible with explicit nulls."""
    stamp = updated_at or datetime.now(UTC)
    unique, _ = dedupe_posts(posts)
    groups: dict[datetime, list[SocialPost]] = {}
    for post in unique:
        groups.setdefault(post.window_start, []).append(post)

    first = start or (min(groups) if groups else None)
    last = end or (max(groups) if groups else None)
    if first is None or last is None:
        return []

    hours: list[SentimentHour] = []
    for hour in _hour_series(first, last):
        group = groups.get(hour, [])
        if not group:
            hours.append(
                SentimentHour(
                    window_start=hour,
                    post_count=0,
                    unique_authors=0,
                    mean_sentiment=None,
                    positive_share=None,
                    negative_share=None,
                    neutral_share=None,
                    total_likes=0,
                    total_reposts=0,
                    total_replies=0,
                    engagement_per_post=None,
                    top_hashtags=(),
                    sentiment_model_version=FALLBACK_MODEL_VERSION,
                    updated_at=stamp,
                )
            )
            continue

        count = len(group)
        labels = Counter(post.sentiment.label for post in group)
        hashtags = Counter(tag for post in group for tag in post.hashtags)
        top = tuple(tag for tag, _ in hashtags.most_common(TOP_HASHTAGS))
        total_engagement = sum(post.engagement for post in group)
        hours.append(
            SentimentHour(
                window_start=hour,
                post_count=count,
                unique_authors=len({post.author_key for post in group}),
                mean_sentiment=round(
                    sum(post.sentiment.compound for post in group) / count, 6
                ),
                positive_share=round(labels["positive"] / count, 6),
                negative_share=round(labels["negative"] / count, 6),
                neutral_share=round(labels["neutral"] / count, 6),
                total_likes=sum(post.like_count for post in group),
                total_reposts=sum(post.repost_count for post in group),
                total_replies=sum(post.reply_count for post in group),
                engagement_per_post=round(total_engagement / count, 6),
                top_hashtags=top,
                sentiment_model_version=max(
                    post.sentiment.model_version for post in group
                ),
                updated_at=stamp,
            )
        )
    return hours
