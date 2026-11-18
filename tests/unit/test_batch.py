from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from bmip.common.config import Settings
from bmip.ml import batch


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.committed = False

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def commit(self) -> None:
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakePredictor:
    features = ("rv_60m",)

    class Model:
        def predict(self, frame):
            return [0.02]

    model = Model()


@pytest.fixture
def settings() -> Settings:
    return replace(Settings.from_env(), market_symbols=("BTCUSDT",))


def test_run_batch_rejects_stale_features_and_keeps_old_cache(
    monkeypatch, tmp_path, settings
):
    cache = tmp_path / "latest_features.json"
    cache.write_text(json.dumps({"sentinel": True}), encoding="utf-8")
    monkeypatch.setenv("ML_FEATURE_CACHE", str(cache))
    connection = FakeConnection()
    stale_ts = datetime.now(UTC) - timedelta(hours=3)

    monkeypatch.setattr(batch, "VolatilityPredictor", lambda _settings: FakePredictor())
    monkeypatch.setattr(
        batch,
        "MlflowClient",
        lambda: type(
            "Client",
            (),
            {"get_model_version_by_alias": lambda self, *args: type("V", (), {"version": "2"})()},
        )(),
    )
    monkeypatch.setattr(
        batch,
        "latest_feature_row",
        lambda *_args, **_kwargs: {"window_start": stale_ts, "rv_60m": 0.01},
    )
    monkeypatch.setattr(batch.psycopg, "connect", lambda _dsn: connection)

    result = batch.run_batch(settings)

    assert result["failed"] is True
    assert result["stale_symbols"] == ["BTCUSDT"]
    assert result["symbols"]["BTCUSDT"]["status"] == "error"
    assert json.loads(cache.read_text(encoding="utf-8")) == {"sentinel": True}
    assert connection.calls and connection.committed


def test_run_batch_writes_fresh_cache(monkeypatch, tmp_path, settings):
    cache = tmp_path / "latest_features.json"
    monkeypatch.setenv("ML_FEATURE_CACHE", str(cache))
    connection = FakeConnection()
    fresh_ts = datetime.now(UTC) - timedelta(minutes=5)

    monkeypatch.setattr(batch, "VolatilityPredictor", lambda _settings: FakePredictor())
    monkeypatch.setattr(
        batch,
        "MlflowClient",
        lambda: type(
            "Client",
            (),
            {"get_model_version_by_alias": lambda self, *args: type("V", (), {"version": "2"})()},
        )(),
    )
    monkeypatch.setattr(
        batch,
        "latest_feature_row",
        lambda *_args, **_kwargs: {"window_start": fresh_ts, "rv_60m": 0.01},
    )
    monkeypatch.setattr(batch.psycopg, "connect", lambda _dsn: connection)

    result = batch.run_batch(settings)

    assert result["failed"] is False
    assert result["symbols"]["BTCUSDT"]["status"] == "ok"
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["symbols"]["BTCUSDT"]["rv_60m"] == 0.01


def test_run_batch_uses_configured_as_of(monkeypatch, tmp_path, settings):
    cache = tmp_path / "latest_features.json"
    monkeypatch.setenv("ML_FEATURE_CACHE", str(cache))
    connection = FakeConnection()
    as_of = datetime(2026, 11, 17, tzinfo=UTC)
    seen: dict[str, datetime | None] = {}

    def latest(_settings, _symbol, *, at=None):
        seen["at"] = at
        return {"window_start": at - timedelta(minutes=5), "rv_60m": 0.01}

    monkeypatch.setattr(batch, "VolatilityPredictor", lambda _settings: FakePredictor())
    monkeypatch.setattr(
        batch,
        "MlflowClient",
        lambda: type(
            "Client",
            (),
            {"get_model_version_by_alias": lambda self, *args: type("V", (), {"version": "2"})()},
        )(),
    )
    monkeypatch.setattr(batch, "latest_feature_row", latest)
    monkeypatch.setattr(batch.psycopg, "connect", lambda _dsn: connection)

    result = batch.run_batch(replace(settings, bmip_as_of="2026-11-17T00:00:00Z"))

    assert seen["at"] == as_of
    assert result["as_of"] == as_of.isoformat()
    assert result["failed"] is False
