from datetime import UTC, datetime, timedelta

import pytest

from bmip.serving.freshness import (
    OK,
    STALE,
    UNKNOWN,
    WARN,
    classify,
    clock_for,
    compute,
    hour_end,
    iso,
    parse_as_of,
)


@pytest.mark.parametrize(
    ("age", "slo", "expected"),
    [
        (0, 5400, OK),
        (5400, 5400, OK),
        (5401, 5400, WARN),
        (10800, 5400, WARN),
        (10801, 5400, STALE),
        (None, 5400, UNKNOWN),
    ],
)
def test_classify_thresholds(age, slo, expected):
    assert classify(age, slo) == expected


def test_classify_negative_age_is_clamped_not_counted_as_stale():
    assert classify(-30, 60) == OK


def test_hour_end_is_one_hour_after_window_start():
    start = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert hour_end(start) == datetime(2026, 11, 10, 17, 0, tzinfo=UTC)


def test_compute_uses_the_given_clock():
    data_ts = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
    now = data_ts + timedelta(minutes=5)
    fresh = compute("market", data_ts, 5400, now=now)
    assert fresh.age_seconds == 300
    assert fresh.status == OK
    assert fresh.clock == "live"
    assert fresh.as_dict()["data_ts"] == "2026-11-10T17:00:00Z"


def test_compute_without_data_is_unknown_not_stale():
    fresh = compute("sentiment", None, 5400)
    assert fresh.status == UNKNOWN
    assert fresh.age_seconds is None


def test_parse_as_of_accepts_z_and_rejects_junk():
    parsed = parse_as_of("2026-11-10T16:00:00Z")
    assert parsed == datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert parse_as_of("not-a-date") is None
    assert parse_as_of("") is None


def test_clock_for_labels_replay():
    explicit = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert clock_for(explicit) == (explicit, "replay")
    now, clock = clock_for(None)
    assert clock == "live"
    assert abs((now - datetime.now(UTC)).total_seconds()) < 5


def test_iso_normalises_to_utc_z():
    assert iso(datetime(2026, 11, 10, 16, 0)) == "2026-11-10T16:00:00Z"
    assert iso(None) is None
