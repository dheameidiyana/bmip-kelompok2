from datetime import UTC, datetime, timedelta

import pytest

from bmip.serving.repository import Page, _page, decode_cursor, encode_cursor


def test_cursor_roundtrip():
    stamp = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    assert decode_cursor(encode_cursor(stamp)) == stamp


def test_cursor_rejects_garbage():
    with pytest.raises(ValueError):
        decode_cursor("not-a-cursor")


def test_cursor_is_opaque():
    stamp = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    encoded = encode_cursor(stamp)
    assert "2026" not in encoded
    assert ":" not in encoded


def test_page_returns_everything_when_under_the_limit():
    rows = [{"window_start": datetime(2026, 11, 10, 16, 0, tzinfo=UTC)}]
    page = _page(rows, 2)
    assert page.rows == rows
    assert page.next_cursor is None


def test_page_trims_and_sets_a_cursor_at_the_last_kept_row():
    base = datetime(2026, 11, 10, 16, 0, tzinfo=UTC)
    rows = [{"window_start": base - timedelta(hours=index)} for index in range(3)]
    page = _page(rows, 2)
    assert len(page.rows) == 2
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor) == rows[1]["window_start"]


def test_keyset_walk_never_duplicates_or_skips_rows():
    """Mirror the SQL predicate: next page is strictly older than the cursor."""
    base = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
    all_rows = [
        {"window_start": base - timedelta(hours=index)} for index in range(25)
    ]
    seen: list[datetime] = []
    boundary: datetime | None = None
    while True:
        available = [
            row
            for row in all_rows
            if boundary is None or row["window_start"] < boundary
        ][:8]
        page = _page(available, 7)
        seen.extend(row["window_start"] for row in page.rows)
        if page.next_cursor is None:
            break
        boundary = decode_cursor(page.next_cursor)
    assert len(seen) == len(all_rows)
    assert len(set(seen)) == len(all_rows)
    assert seen == [row["window_start"] for row in all_rows]


def test_page_defaults_are_empty():
    assert Page().as_dict() == {"rows": [], "next_cursor": None}
