"""Mirror MLflow model metadata into the serving registry tables."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from bmip.common.config import Settings

MODEL_NAME = "volatility_model"


def upsert_model_metric(
    settings: Settings,
    *,
    version: str,
    alias: str | None,
    metrics: dict[str, Any],
) -> None:
    with psycopg.connect(settings.postgres_dsn) as connection:
        connection.execute(
            """
            INSERT INTO serving.model_metrics
                (model_name, version, alias, metrics, created_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (model_name, version) DO UPDATE SET
                alias = EXCLUDED.alias,
                metrics = EXCLUDED.metrics,
                created_at = now()
            """,
            (MODEL_NAME, version, alias, Jsonb(metrics)),
        )
        connection.commit()


def record_decision(
    settings: Settings,
    *,
    champion_version: str | None,
    challenger_version: str | None,
    decision: str,
    reason: str,
    metrics: dict[str, Any],
    decision_ts: datetime | None = None,
) -> None:
    timestamp = decision_ts or datetime.now(UTC)
    with psycopg.connect(settings.postgres_dsn) as connection:
        connection.execute(
            """
            INSERT INTO serving.model_decisions
                (model_name, decision_ts, champion_version, challenger_version,
                 decision, reason, metrics)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (model_name, decision_ts) DO UPDATE SET
                champion_version = EXCLUDED.champion_version,
                challenger_version = EXCLUDED.challenger_version,
                decision = EXCLUDED.decision,
                reason = EXCLUDED.reason,
                metrics = EXCLUDED.metrics
            """,
            (
                MODEL_NAME,
                timestamp,
                champion_version,
                challenger_version,
                decision,
                reason,
                Jsonb(metrics),
            ),
        )
        connection.commit()
