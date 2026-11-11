from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bmip.ingestion.contracts import (
    load_fixture,
    validate_market_trade,
    validate_social_post,
)


def test_social_contract_accepts_valid_post() -> None:
    result = validate_social_post(load_fixture("social_post_valid.json"))
    assert result.ok is True
    assert result.model is not None
    assert result.model.post_uri.startswith("at://")


def test_market_contract_rejects_negative_price() -> None:
    result = validate_market_trade(load_fixture("market_trade_negative_price.json"))
    assert result.ok is False
    assert any(issue.path == "$.price" for issue in result.errors)


def test_market_contract_rejects_unknown_field() -> None:
    payload = load_fixture("market_trade_valid.json")
    payload["unexpected"] = "value"
    result = validate_market_trade(payload)
    assert result.ok is False
    assert any("unexpected" in issue.message for issue in result.errors)


def test_market_contract_rejects_future_event() -> None:
    payload = load_fixture("market_trade_valid.json")
    future = datetime.now(UTC) + timedelta(days=1)
    payload["event_ts"] = future.isoformat()
    payload["ingest_ts"] = future.isoformat()
    result = validate_market_trade(payload)
    assert result.ok is False
    assert any(issue.path == "$.event_ts" for issue in result.errors)


def test_social_contract_rejects_non_at_uri() -> None:
    result = validate_social_post(load_fixture("social_post_invalid_uri.json"))
    assert result.ok is False
    assert any(issue.path == "$.post_uri" for issue in result.errors)
