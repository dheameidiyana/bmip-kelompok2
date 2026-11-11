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


def test_minio_credentials(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    monkeypatch.setenv("MINIO_SVC_INGEST_ACCESS_KEY", "ingest-key")
    monkeypatch.setenv("MINIO_SVC_INGEST_SECRET_KEY", "ingest-secret")

    settings = Settings.from_env()

    assert settings.minio_credentials("ingest") == ("ingest-key", "ingest-secret")
    with pytest.raises(KeyError):
        settings.minio_credentials("unknown")
