"""Unit tests for the silver social transform (W1-C)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bmip.transform.silver_social import post_row, sentiment_row
from bmip.transform.social import (
    aggregate_sentiment_hourly,
    dedupe_posts,
    parse_social_post,
    pseudonymize,
    score_sentiment,
)

SALT = "unit-test-salt"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def bronze_row(**overrides):
    base = {
        "post_uri": "at://did:plc:example123/app.bsky.feed.post/3kexample101",
        "author_did": "did:plc:example123",
        "author_handle": "alice.bsky.social",
        "created_at": "2026-11-10T11:05:00Z",
        "ingest_ts": "2026-11-10T11:06:00Z",
        "lang": "en",
        "text": "BTC looks strong today #bitcoin",
        "hashtags": ["bitcoin"],
        "like_count": 10,
        "repost_count": 2,
        "reply_count": 1,
        "quote_count": 0,
        "source": "bluesky",
    }
    base.update(overrides)
    return base


def test_pseudonymize_is_stable_and_salted():
    first = pseudonymize("did:plc:example123", SALT)
    assert first == pseudonymize("did:plc:example123", SALT)
    assert first != pseudonymize("did:plc:example123", "other-salt")
    assert first != "did:plc:example123"
    assert len(first) == 64


def test_pseudonymize_requires_salt():
    with pytest.raises(ValueError):
        pseudonymize("did:plc:example123", "")


def test_parse_post_removes_pii_and_scores_sentiment():
    post, reason = parse_social_post(bronze_row(), salt=SALT, now=NOW)
    assert reason is None
    assert post is not None
    assert post.post_key != bronze_row()["post_uri"]
    assert post.author_key != bronze_row()["author_did"]
    assert -1.0 <= post.sentiment.compound <= 1.0
    assert post.sentiment.label in {"positive", "negative", "neutral"}

    row = post_row(post)
    for forbidden in ("post_uri", "author_did", "author_handle", "display_name", "avatar"):
        assert forbidden not in row
    assert "at://" not in str(row)
    assert "did:plc:" not in str(row)

    sentiment = sentiment_row(post)
    assert sentiment["sentiment_score"] == post.sentiment.compound
    assert sentiment["sentiment_model_version"].startswith("vaderSentiment")


def test_parse_rejects_empty_text():
    post, reason = parse_social_post(bronze_row(text="   "), salt=SALT, now=NOW)
    assert post is None
    assert reason == "empty_text"


def test_parse_rejects_future_created_at():
    post, reason = parse_social_post(
        bronze_row(created_at="2026-11-10T13:00:00Z"), salt=SALT, now=NOW
    )
    assert post is None
    assert reason == "future_created_at"


def test_parse_rejects_negative_engagement():
    post, reason = parse_social_post(bronze_row(like_count=-1), salt=SALT, now=NOW)
    assert post is None
    assert reason == "invalid_like_count"


def test_dedupe_keeps_newest_ingest_ts():
    older, _ = parse_social_post(bronze_row(), salt=SALT, now=NOW)
    newer, _ = parse_social_post(
        bronze_row(ingest_ts="2026-11-10T11:30:00Z", text="BTC looks strong today"),
        salt=SALT,
        now=NOW,
    )
    assert older is not None and newer is not None

    unique, duplicates = dedupe_posts([older, newer])
    assert duplicates == 1
    assert len(unique) == 1
    assert unique[0].ingest_ts == newer.ingest_ts
    assert unique[0].text == "BTC looks strong today"


def test_dedupe_is_order_independent():
    first, _ = parse_social_post(bronze_row(), salt=SALT, now=NOW)
    second, _ = parse_social_post(
        bronze_row(ingest_ts="2026-11-10T11:30:00Z"), salt=SALT, now=NOW
    )
    assert first is not None and second is not None
    assert dedupe_posts([first, second])[0] == dedupe_posts([second, first])[0]


def test_sentiment_scores_stay_in_range():
    samples = [
        "BTC to the moon!!!",
        "I hate this market so much",
        "Bitcoin traded sideways today",
        "#bitcoin #btc volatility rising",
    ]
    for text in samples:
        sentiment = score_sentiment(text)
        assert -1.0 <= sentiment.compound <= 1.0
        assert sentiment.positive + sentiment.neutral + sentiment.negative == pytest.approx(
            1.0
        )
    empty = score_sentiment("")
    assert empty.compound == 0.0
    assert empty.label == "neutral"


def test_aggregate_fills_empty_hours_explicitly():
    later = datetime(2026, 11, 10, 14, 0, tzinfo=UTC)
    first, _ = parse_social_post(bronze_row(), salt=SALT, now=later)
    third, _ = parse_social_post(
        bronze_row(
            post_uri="at://did:plc:example456/app.bsky.feed.post/3kexample102",
            author_did="did:plc:example456",
            created_at="2026-11-10T13:10:00Z",
            ingest_ts="2026-11-10T13:11:00Z",
            text="Watching BTC volatility into the close",
            hashtags=[],
        ),
        salt=SALT,
        now=later,
    )
    assert first is not None and third is not None

    hours = aggregate_sentiment_hourly([first, third], updated_at=NOW)
    assert [hour.window_start.hour for hour in hours] == [11, 12, 13]
    empty = hours[1]
    assert empty.post_count == 0
    assert empty.unique_authors == 0
    assert empty.mean_sentiment is None
    assert empty.positive_share is None
    assert empty.engagement_per_post is None
    assert empty.top_hashtags == ()
    assert empty.total_likes == 0


def test_aggregate_hourly_metrics():
    first, _ = parse_social_post(bronze_row(), salt=SALT, now=NOW)
    second, _ = parse_social_post(
        bronze_row(
            post_uri="at://did:plc:example999/app.bsky.feed.post/3kexample103",
            author_did="did:plc:example999",
            created_at="2026-11-10T11:45:00Z",
            ingest_ts="2026-11-10T11:46:00Z",
            text="I hate this market",
            hashtags=["bitcoin", "crypto"],
            like_count=0,
            repost_count=0,
            reply_count=0,
        ),
        salt=SALT,
        now=NOW,
    )
    assert first is not None and second is not None

    hours = aggregate_sentiment_hourly(
        [first, second],
        start=datetime(2026, 11, 10, 11, tzinfo=UTC),
        end=datetime(2026, 11, 10, 11, tzinfo=UTC),
        updated_at=NOW,
    )
    assert len(hours) == 1
    hour = hours[0]
    assert hour.post_count == 2
    assert hour.unique_authors == 2
    assert hour.positive_share + hour.negative_share + hour.neutral_share == pytest.approx(1.0)
    assert hour.total_likes == 10
    assert hour.top_hashtags[0] == "bitcoin"
    assert hour.engagement_per_post == pytest.approx(6.5)


def test_window_start_truncates_to_hour():
    post, _ = parse_social_post(
        bronze_row(created_at="2026-11-10T11:59:59Z", ingest_ts="2026-11-10T12:00:01Z"),
        salt=SALT,
        now=datetime(2026, 11, 10, 12, 30, tzinfo=UTC),
    )
    assert post is not None
    assert post.window_start == datetime(2026, 11, 10, 11, tzinfo=UTC)
    assert post.event_date == datetime(2026, 11, 10, 11, tzinfo=UTC).date()
    assert post.window_start + timedelta(hours=1) == datetime(2026, 11, 10, 12, tzinfo=UTC)
