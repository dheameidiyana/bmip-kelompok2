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


def promotion_plan(
    *,
    gate_pass: bool,
    champion_before: str | None,
    candidate_version: str,
) -> dict[str, str | None]:
    archived = (
        champion_before
        if gate_pass
        and champion_before is not None
        and champion_before != candidate_version
        else None
    )
    return {
        "decision": "promoted" if gate_pass else "rejected",
        "champion_before": champion_before,
        "champion_after": candidate_version if gate_pass else champion_before,
        "archived_version": archived,
    }


def archive_champion_metrics(
    settings: Settings,
    *,
    new_champion_version: str,
) -> None:
    with psycopg.connect(settings.postgres_dsn) as connection:
        connection.execute(
            """
            UPDATE serving.model_metrics
            SET alias = 'archived', created_at = now()
            WHERE model_name = %s
              AND alias = 'champion'
              AND version <> %s
            """,
            (MODEL_NAME, new_champion_version),
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
