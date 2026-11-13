import pytest

from bmip.common.config import Settings


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv(
        "POSTGRES_CORE_DSN", "postgresql://bmip:pw@localhost:5432/bmip"
    )

    settings = Settings.from_env()

    assert settings.env in {"dev", "ci"}
    assert settings.market_topic == "market.trades"
    assert settings.social_max_pages == 50
    assert settings.postgres_dsn.endswith("/bmip")


def test_stream_settings_defaults(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")

    settings = Settings.from_env()

    assert settings.market_dlq_topic == "market.trades.dlq"
    assert settings.stream_consumer_group == "ohlcv-builder"
    assert settings.stream_replay_group == "ohlcv-builder-replay"
    assert settings.stream_poll_max_records == 1000
    assert settings.stream_poll_timeout_ms == 500
    assert settings.stream_watermark_delay_seconds == 120
    assert settings.stream_correction_window_minutes == 30
    assert settings.stream_metrics_host == "0.0.0.0"
    assert settings.stream_metrics_port == 9101
    assert settings.stream_idle_exit_seconds == 5.0
    assert settings.stream_startup_delay_seconds == 0.0


def test_stream_settings_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("MARKET_DLQ_TOPIC", "market.trades.dead")
    monkeypatch.setenv("STREAM_CONSUMER_GROUP", "silver-cp1")
    monkeypatch.setenv("STREAM_REPLAY_GROUP", "silver-cp1-replay")
    monkeypatch.setenv("STREAM_POLL_MAX_RECORDS", "250")
    monkeypatch.setenv("STREAM_POLL_TIMEOUT_MS", "750")
    monkeypatch.setenv("STREAM_WATERMARK_DELAY_SECONDS", "60")
    monkeypatch.setenv("STREAM_CORRECTION_WINDOW_MINUTES", "15")
    monkeypatch.setenv("STREAM_METRICS_HOST", "127.0.0.1")
    monkeypatch.setenv("STREAM_METRICS_PORT", "9201")
    monkeypatch.setenv("STREAM_IDLE_EXIT_SECONDS", "2.5")
    monkeypatch.setenv("STREAM_STARTUP_DELAY_SECONDS", "3.5")

    settings = Settings.from_env()

    assert settings.market_dlq_topic == "market.trades.dead"
    assert settings.stream_consumer_group == "silver-cp1"
    assert settings.stream_replay_group == "silver-cp1-replay"
    assert settings.stream_poll_max_records == 250
    assert settings.stream_poll_timeout_ms == 750
    assert settings.stream_watermark_delay_seconds == 60
    assert settings.stream_correction_window_minutes == 15
    assert settings.stream_metrics_host == "127.0.0.1"
    assert settings.stream_metrics_port == 9201
    assert settings.stream_idle_exit_seconds == 2.5
    assert settings.stream_startup_delay_seconds == 3.5


def test_minio_credentials(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("MINIO_SVC_INGEST_ACCESS_KEY", "ingest-key")
    monkeypatch.setenv("MINIO_SVC_INGEST_SECRET_KEY", "ingest-secret")

    settings = Settings.from_env()

    assert settings.minio_credentials("ingest") == ("ingest-key", "ingest-secret")
    with pytest.raises(KeyError):
        settings.minio_credentials("unknown")
