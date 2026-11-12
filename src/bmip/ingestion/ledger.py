"""PostgreSQL ledger for batch runs and the social watermark."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class BatchRun:
    batch_id: str
    source: str
    window_start: datetime
    window_end: datetime
    row_count: int
    checksum: str
    status: str


def get_batch(dsn: str, batch_id: str) -> BatchRun | None:
    query = """
        SELECT batch_id, source, window_start, window_end, row_count, checksum, status
        FROM ops.batch_runs
        WHERE batch_id = %s
    """
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(query, (batch_id,))
        row = cursor.fetchone()
    return BatchRun(*row) if row else None


def begin_batch(
    dsn: str,
    batch_id: str,
    source: str,
    window_start: datetime,
    window_end: datetime,
    checksum: str,
) -> None:
    statement = """
        INSERT INTO ops.batch_runs
            (batch_id, source, window_start, window_end, row_count, checksum, status)
        VALUES (%s, %s, %s, %s, 0, %s, 'running')
        ON CONFLICT (batch_id) DO UPDATE SET
            source = EXCLUDED.source,
            window_start = EXCLUDED.window_start,
            window_end = EXCLUDED.window_end,
            checksum = EXCLUDED.checksum,
            status = 'running',
            updated_at = now()
    """
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(
            statement,
            (batch_id, source, window_start, window_end, checksum),
        )


def finish_batch(
    dsn: str,
    batch_id: str,
    status: str,
    row_count: int,
    checksum: str,
) -> None:
    statement = """
        UPDATE ops.batch_runs
        SET status = %s, row_count = %s, checksum = %s, updated_at = now()
        WHERE batch_id = %s
    """
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(statement, (status, row_count, checksum, batch_id))


def get_watermark(dsn: str, source: str) -> datetime | None:
    query = "SELECT last_created_at FROM ops.social_watermark WHERE source = %s"
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(query, (source,))
        row = cursor.fetchone()
    return row[0] if row else None


def advance_watermark(dsn: str, source: str, last_created_at: datetime) -> None:
    statement = """
        INSERT INTO ops.social_watermark (source, last_created_at, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (source) DO UPDATE SET
            last_created_at = GREATEST(
                ops.social_watermark.last_created_at,
                EXCLUDED.last_created_at
            ),
            updated_at = now()
    """
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute(statement, (source, last_created_at))
