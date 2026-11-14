from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bmip.api.deps import get_lake, get_repository
from bmip.api.lake import LakeUnavailable
from bmip.api.main import create_app
from bmip.common.config import Settings
from bmip.serving.repository import Page

NOW = datetime.now(UTC).replace(microsecond=0)
HOUR = NOW.replace(minute=0, second=0, microsecond=0)
API_KEY = "test-key"


def bar(hour: datetime, close: float = 100.0) -> dict:
    return {
        "symbol": "BTCUSDT",
        "window_start": hour,
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 10.0,
        "quote_volume": 1000.0,
        "trade_count": 3,
        "vwap": close - 0.5,
        "log_return_1h": 0.01,
        "realized_vol_1h": 0.02,
        "rv_ewma_24h": 0.03,
        "source": "binance_vision",
        "event_date": hour.date(),
        "updated_at": hour,
    }


def sentiment(hour: datetime) -> dict:
    return {
        "window_start": hour,
        "post_count": 2,
        "unique_authors": 2,
        "mean_sentiment": 0.4,
        "positive_share": 0.5,
        "negative_share": 0.0,
        "neutral_share": 0.5,
        "total_likes": 1,
        "total_reposts": 0,
        "total_replies": 0,
        "engagement_per_post": 0.5,
        "top_hashtags": ["btc"],
        "sentiment_model_version": "vaderSentiment-3.3.2",
    }


class FakeRepository:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.closed = False

    # health
    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    # market
    def market_latest(self, symbol: str):
        return bar(HOUR, 101.0) if symbol == "BTCUSDT" else None

    def market_hourly(self, symbol, *, start=None, end=None, limit=100, cursor=None):
        rows = [bar(HOUR - timedelta(hours=index)) for index in range(3)]
        return Page(rows=rows[:limit])

    def volatility_latest(self, symbol):
        return bar(HOUR)

    def volatility_range(self, symbol, *, start=None, end=None, limit=100, cursor=None):
        return self.market_hourly(symbol, limit=limit)

    # sentiment
    def sentiment_latest(self):
        return sentiment(HOUR)

    def sentiment_range(self, *, start=None, end=None, limit=100, cursor=None):
        rows = [sentiment(HOUR - timedelta(hours=index)) for index in range(2)]
        return Page(rows=rows[:limit])

    # freshness
    def freshness(self):
        return [
            {
                "metric": "market",
                "data_ts": HOUR,
                "slo_seconds": 5400,
                "status": "ok",
                "clock": "live",
                "as_of": NOW,
            }
        ]

    def freshness_one(self, metric):
        return self.freshness()[0]

    # catalog
    def datasets(self, *, q=None, domain=None, layer=None, owner=None, limit=100, cursor=None):
        row = {
            "id": "gold.mart_market",
            "name": "Market mart",
            "layer": "gold",
            "domain": "market",
            "kind": "iceberg",
            "location": "gold.mart_market",
            "description": "Hourly market mart",
            "owner": "vio",
            "classification": "internal",
            "retention_days": 90,
            "refresh_schedule": "hourly",
            "sla": "90 minutes",
            "license": "Binance public",
            "contains_pii": False,
            "tags": ["gold"],
        }
        return Page(rows=[row], next_cursor=None)

    def dataset(self, dataset_id):
        if dataset_id != "gold.mart_market":
            return None
        return self.datasets().rows[0]

    # quality
    def quality_status(self):
        return {"status": "pass", "run_ts": NOW, "critical_failures": 0, "failures": []}

    # model
    def model_latest(self, model_name="volatility_model"):
        return None

    def champion(self, model_name="volatility_model"):
        return None

    def insert_prediction(self, **kwargs):
        self.inserted.append(kwargs)


class FakeLake:
    def __init__(self, *, fail: bool = False, rows: int = 3) -> None:
        self.fail = fail
        self.rows = [bar(HOUR - timedelta(hours=index)) for index in range(rows)]

    def market_range(self, symbol, start, end, limit):
        if self.fail:
            raise LakeUnavailable("minio is down")
        return self.rows[:limit]

    def sentiment_range(self, start, end, limit):
        if self.fail:
            raise LakeUnavailable("minio is down")
        return [sentiment(HOUR - timedelta(hours=index)) for index in range(2)][:limit]

    def health(self) -> bool:
        return not self.fail


@pytest.fixture
def settings(monkeypatch) -> Settings:
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("PII_HASH_SALT", "salt")
    monkeypatch.setenv("BMIP_API_KEY", API_KEY)
    monkeypatch.setenv("API_AUTH_REQUIRED", "true")
    monkeypatch.setenv("BMIP_AS_OF", "")
    return Settings.from_env()


@pytest.fixture
def harness(settings):
    app = create_app(settings)
    repository = FakeRepository()
    lake = FakeLake()
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_lake] = lambda: lake
    client = TestClient(app)
    return client, repository, lake, app


def auth() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def test_api_index_is_public_and_lists_the_endpoints(harness):
    client, *_ = harness
    response = client.get("/api")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "bmip-api"
    assert "GET /v1/market/ohlc" in body["endpoints"]
    assert "POST /v1/predict" in body["endpoints"]


def test_data_routes_require_an_api_key(harness):
    client, *_ = harness
    response = client.get("/v1/market/latest")
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"].endswith("/unauthorized")
    assert body["request_id"].startswith("req-")
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_wrong_api_key_is_rejected(harness):
    client, *_ = harness
    response = client.get("/v1/market/latest", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_request_id_is_propagated(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/latest", headers={**auth(), "X-Request-ID": "req-test-123"}
    )
    assert response.headers["X-Request-ID"] == "req-test-123"
    assert response.json()["meta"]["request_id"] == "req-test-123"


def test_market_latest_defaults_to_btcusdt(harness):
    client, *_ = harness
    response = client.get("/v1/market/latest", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["symbol"] == "BTCUSDT"
    assert body["meta"]["source"] == "serving"
    assert body["meta"]["count"] is None


def test_unknown_symbol_is_a_400_problem(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/latest", params={"symbol": "ETHUSDT"}, headers=auth()
    )
    assert response.status_code == 400
    assert response.json()["type"].endswith("/unknown-symbol")


def test_ohlc_uses_the_lake_and_pages(harness):
    client, *_ = harness
    response = client.get("/v1/market/ohlc", params={"limit": 2}, headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["meta"]["source"] == "lake"
    assert body["meta"]["stale"] is False
    assert body["meta"]["next_cursor"]
    assert response.headers["X-Data-Source"] == "lake"
    assert response.headers["X-Data-Stale"] == "false"


def test_lake_failure_falls_back_to_serving_and_marks_stale(harness):
    client, repository, lake, app = harness
    lake.fail = True
    response = client.get("/v1/market/ohlc", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["source"] == "serving"
    assert body["meta"]["stale"] is True
    assert response.headers["X-Data-Stale"] == "true"
    assert app.state.metrics["fallbacks"] == 1


def test_invalid_range_is_rejected(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/ohlc",
        params={"from": "2026-11-16T00:00:00Z", "to": "2026-11-15T00:00:00Z"},
        headers=auth(),
    )
    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-range")


def test_range_longer_than_the_cap_is_rejected(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/ohlc",
        params={"from": "2026-01-01T00:00:00Z", "to": "2026-03-01T00:00:00Z"},
        headers=auth(),
    )
    assert response.status_code == 400


@pytest.mark.parametrize("limit", [0, 5000])
def test_limit_outside_the_cap_is_422(harness, limit):
    client, *_ = harness
    response = client.get("/v1/market/ohlc", params={"limit": limit}, headers=auth())
    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/invalid-limit")
    assert body["request_id"]


def test_malformed_cursor_is_400(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/ohlc", params={"cursor": "broken"}, headers=auth()
    )
    assert response.status_code == 400
    assert response.json()["type"].endswith("/invalid-cursor")


def test_malformed_datetime_is_422(harness):
    client, *_ = harness
    response = client.get(
        "/v1/market/ohlc", params={"from": "yesterday"}, headers=auth()
    )
    assert response.status_code == 422
    body = response.json()
    assert body["type"].endswith("/validation-error")
    assert body["errors"]


def test_sentiment_range_requires_both_bounds(harness):
    client, *_ = harness
    response = client.get(
        "/v1/sentiment/range", params={"from": "2026-11-10T00:00:00Z"}, headers=auth()
    )
    assert response.status_code == 400
    assert response.json()["type"].endswith("/missing-range")


def test_sentiment_hourly_alias_matches(harness):
    client, *_ = harness
    primary = client.get("/v1/sentiment/hourly", headers=auth())
    alias = client.get("/v1/sentiment/timeseries", headers=auth())
    assert primary.status_code == alias.status_code == 200
    assert primary.json()["data"] == alias.json()["data"]


def test_freshness_is_recomputed_at_request_time(harness):
    client, *_ = harness
    response = client.get("/v1/freshness", headers=auth())
    body = response.json()
    assert body["data"][0]["status"] in {"ok", "warn", "stale"}
    assert body["data"][0]["age_seconds"] is not None


def test_dataset_list_and_404(harness):
    client, *_ = harness
    listed = client.get("/v1/dataset", headers=auth())
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == "gold.mart_market"

    missing = client.get("/v1/dataset/nope/schema", headers=auth())
    assert missing.status_code == 404
    assert missing.json()["type"].endswith("/dataset-not-found")


def test_quality_status_returns_the_last_run(harness):
    client, *_ = harness
    response = client.get("/v1/quality/status", headers=auth())
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pass"


def test_model_latest_says_not_available_instead_of_inventing_a_value(harness):
    client, *_ = harness
    response = client.get("/v1/model/latest", headers=auth())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_available"
    assert "W2-A" in body["detail"]


def test_predict_rejects_a_malformed_payload(harness):
    client, *_ = harness
    response = client.post(
        "/v1/predict",
        json={"symbol": "BTCUSDT", "features": {"rv_60m": "not-a-number"}},
        headers=auth(),
    )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/validation-error")


def test_predict_records_an_out_of_range_feature(harness):
    client, repository, *_ = harness
    response = client.post(
        "/v1/predict",
        json={"symbol": "BTCUSDT", "features": {"rv_60m": -1}},
        headers=auth(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert repository.inserted and repository.inserted[0]["status"] == "error"


def test_predict_without_a_champion_is_not_available(harness):
    client, *_ = harness
    response = client.post("/v1/predict", json={"symbol": "BTCUSDT"}, headers=auth())
    assert response.status_code == 200
    assert response.json()["status"] == "not_available"


def test_health_ready_reports_both_paths(harness):
    client, repository, lake, _ = harness
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == {"lake": True, "serving": True}

    lake.fail = True
    repository.ping = lambda: False
    response = client.get("/health/ready")
    assert response.status_code == 503


def test_metrics_expose_the_counters(harness):
    client, *_ = harness
    client.get("/v1/market/latest", headers=auth())
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "bmip_api_requests_total" in text
    assert "bmip_api_fallback_total" in text
    assert "bmip_api_request_duration_seconds_count" in text


def test_aliases_stay_in_openapi(harness):
    _, _, _, app = harness
    paths = app.openapi()["paths"]
    assert "/v1/market/ohlcv" in paths
    assert "/v1/market/volatility" in paths
    assert "/v1/sentiment/timeseries" in paths
    assert "/v1/dq/results" in paths
    assert "/v1/catalog/search" in paths


def test_event_date_is_serialised(harness):
    client, *_ = harness
    response = client.get("/v1/market/latest", headers=auth())
    assert response.json()["data"]["event_date"] == HOUR.date().isoformat()


def test_committed_openapi_tracks_the_app(harness):
    """CI drift guard: a new route must be committed to contracts/openapi.json."""
    import json
    from pathlib import Path

    _, _, _, app = harness
    root = Path(__file__).resolve().parents[2]
    committed = json.loads((root / "contracts" / "openapi.json").read_text(encoding="utf-8"))
    live = app.openapi()
    assert set(committed["paths"]) == set(live["paths"])
    assert committed["info"]["version"] == live["info"]["version"]
