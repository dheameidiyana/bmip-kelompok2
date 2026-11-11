from __future__ import annotations

import json
from pathlib import Path

from bmip.ingestion.feeds import (
    iter_static_market,
    iter_static_social,
    map_bluesky_post,
    parse_binance_vision_row,
    parse_binance_ws,
)
from bmip.ingestion.hashing import records_checksum

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_binance_ws_maps_contract() -> None:
    raw = json.loads((FIXTURES / "binance_agg_trades.jsonl").read_text().splitlines()[0])
    record = parse_binance_ws(raw, "BTCUSDT")
    assert record is not None
    assert record["trade_id"] == 900000001
    assert record["price"] == 68000.5
    assert record["event_ts"] == "2026-11-10T14:00:01.123000Z"
    assert len(record["payload_hash"]) == 64


def test_parse_binance_vision_row_maps_event_time() -> None:
    row = {
        "agg_trade_id": "900000001",
        "price": "68000.50",
        "quantity": "0.0125",
        "first_trade_id": "1",
        "last_trade_id": "1",
        "transact_time": "1794319201123",
        "is_buyer_maker": "false",
        "is_best_match": "true",
    }
    record = parse_binance_vision_row(row)
    assert record["source"] == "binance_vision"
    assert record["event_ts"] == "2026-11-10T14:00:01.123000Z"
    assert record["is_buyer_maker"] is False


def test_map_bluesky_post_extracts_hashtags() -> None:
    posts = json.loads((FIXTURES / "bluesky_posts.json").read_text())
    record = map_bluesky_post(posts[0])
    assert record["post_uri"].startswith("at://")
    assert record["hashtags"] == ["bitcoin"]
    assert record["raw_ref"].startswith("iceberg://lakehouse/bronze.social_post_raw")


def test_static_replays_are_readable() -> None:
    assert len(list(iter_static_market(FIXTURES / "binance_agg_trades.jsonl"))) == 3
    assert len(list(iter_static_social(FIXTURES / "bluesky_posts.json"))) == 2


def test_checksum_is_order_independent() -> None:
    assert records_checksum(["a" * 64, "b" * 64]) == records_checksum(["b" * 64, "a" * 64])
