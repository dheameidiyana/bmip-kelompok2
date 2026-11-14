"""PostgreSQL access for the serving tier (W1-D).

One module owns every query so the API routers stay thin and the loader and
the API cannot drift apart. Reads use keyset pagination (never OFFSET) so a
page cannot duplicate or skip a row while the loader writes.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.errors import InvalidSchemaName, UndefinedTable
from psycopg.rows import dict_row

from bmip.common.config import Settings
from bmip.serving.freshness import iso

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
SCHEMA_SQL = SCHEMA_FILE.read_text(encoding="utf-8")

MARKET_COLUMNS = (
    "symbol",
    "window_start",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "trade_count",
    "vwap",
    "log_return_1h",
    "realized_vol_1h",
    "rv_ewma_24h",
    "source",
    "event_date",
    "updated_at",
)

SENTIMENT_COLUMNS = (
    "window_start",
    "post_count",
    "unique_authors",
    "mean_sentiment",
    "positive_share",
    "negative_share",
    "neutral_share",
    "total_likes",
    "total_reposts",
    "total_replies",
    "engagement_per_post",
    "top_hashtags",
    "sentiment_model_version",
    "event_date",
    "updated_at",
)


class ServingNotReady(RuntimeError):
    """The serving schema has not been created yet (the pipeline never ran)."""


@dataclass
class Page:
    rows: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"rows": self.rows, "next_cursor": self.next_cursor}


def encode_cursor(window_start: datetime) -> str:
    raw = json.dumps({"w": iso(window_start)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> datetime:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        value = datetime.fromisoformat(str(payload["w"]).replace("Z", "+00:00"))
    except Exception as exc:  # noqa: BLE001 - any malformed cursor is a client error
        raise ValueError("invalid cursor") from exc
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@contextmanager
def connect(settings: Settings, *, autocommit: bool = False) -> Iterator[psycopg.Connection]:
    connection = psycopg.connect(
        settings.postgres_dsn,
        row_factory=dict_row,
        connect_timeout=5,
        autocommit=autocommit,
    )
    try:
        yield connection
    finally:
        connection.close()


def ensure_schema(connection: psycopg.Connection) -> None:
    connection.execute(SCHEMA_SQL)


def _one(connection: psycopg.Connection, sql: str, params: list[Any] | tuple = ()) -> dict | None:
    """Fetch one row, tolerating a serving schema that has not been loaded yet.

    Before the first pipeline run the tables do not exist. That is an empty
    state, not a server error: the API answers 200 with ``data: null`` and an
    ``unknown`` freshness badge instead of a 500.
    """
    try:
        return _clean(connection.execute(sql, params).fetchone())
    except (UndefinedTable, InvalidSchemaName):
        connection.rollback()
        return None


def _many(connection: psycopg.Connection, sql: str, params: list[Any] | tuple = ()) -> list[dict]:
    try:
        return [_clean(row) for row in connection.execute(sql, params).fetchall()]
    except (UndefinedTable, InvalidSchemaName):
        connection.rollback()
        return []


class ServingRepository:
    """Read/write facade over the serving schema.

    A connection is opened per instance; the API opens one per request so a
    long query cannot pin a connection in a pool that the loader needs.
    """

    def __init__(self, settings: Settings, connection: psycopg.Connection | None = None):
        self.settings = settings
        self._connection = connection
        self._owns_connection = connection is None

    @property
    def connection(self) -> psycopg.Connection:
        if self._connection is None:
            # Read-only API sessions use autocommit so one invalid statement
            # (for example a serving table that has not been loaded yet) cannot
            # poison the rest of the request.
            self._connection = psycopg.connect(
                self.settings.postgres_dsn,
                row_factory=dict_row,
                connect_timeout=5,
                autocommit=True,
            )
        return self._connection

    def close(self) -> None:
        if self._connection is not None and self._owns_connection:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> ServingRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ health

    def ping(self) -> bool:
        try:
            self.connection.execute("select 1")
            return True
        except Exception:  # noqa: BLE001 - readiness reports the failure
            return False

    # ----------------------------------------------------------------- market

    def market_latest(self, symbol: str) -> dict[str, Any] | None:
        return _one(
            self.connection,
            "SELECT * FROM serving.market_latest WHERE symbol = %s",
            (symbol,),
        )

    def market_hourly(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        clauses = ["symbol = %s"]
        params: list[Any] = [symbol]
        if start is not None:
            clauses.append("window_start >= %s")
            params.append(start)
        if end is not None:
            clauses.append("window_start < %s")
            params.append(end)
        if cursor is not None:
            clauses.append("window_start < %s")
            params.append(decode_cursor(cursor))
        params.append(limit + 1)
        rows = _many(
            self.connection,
            f"""
            SELECT * FROM serving.market_hourly
            WHERE {' AND '.join(clauses)}
            ORDER BY window_start DESC
            LIMIT %s
            """,
            params,
        )
        return _page(rows, limit)

    def volatility_latest(self, symbol: str) -> dict[str, Any] | None:
        return _one(
            self.connection,
            """
            SELECT * FROM serving.volatility
            WHERE symbol = %s
            ORDER BY window_start DESC
            LIMIT 1
            """,
            (symbol,),
        )

    def volatility_range(
        self,
        symbol: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        page = self.market_hourly(
            symbol, start=start, end=end, limit=limit, cursor=cursor
        )
        keep = (
            "symbol",
            "window_start",
            "log_return_1h",
            "realized_vol_1h",
            "rv_ewma_24h",
            "event_date",
            "updated_at",
        )
        page.rows = [{key: row[key] for key in keep} for row in page.rows]
        return page

    # -------------------------------------------------------------- sentiment

    def sentiment_latest(self) -> dict[str, Any] | None:
        return _one(
            self.connection,
            """
            SELECT * FROM serving.sentiment_hourly
            ORDER BY window_start DESC
            LIMIT 1
            """,
        )

    def sentiment_range(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            clauses.append("window_start >= %s")
            params.append(start)
        if end is not None:
            clauses.append("window_start < %s")
            params.append(end)
        if cursor is not None:
            clauses.append("window_start < %s")
            params.append(decode_cursor(cursor))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit + 1)
        rows = _many(
            self.connection,
            f"""
            SELECT * FROM serving.sentiment_hourly
            {where}
            ORDER BY window_start DESC
            LIMIT %s
            """,
            params,
        )
        return _page(rows, limit)

    # -------------------------------------------------------------- freshness

    def freshness(self) -> list[dict[str, Any]]:
        return _many(self.connection, "SELECT * FROM serving.freshness ORDER BY metric")

    def freshness_one(self, metric: str) -> dict[str, Any] | None:
        return _one(
            self.connection,
            "SELECT * FROM serving.freshness WHERE metric = %s",
            (metric,),
        )

    # --------------------------------------------------------------- catalog

    def datasets(
        self,
        *,
        q: str | None = None,
        domain: str | None = None,
        layer: str | None = None,
        owner: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Page:
        clauses: list[str] = []
        params: list[Any] = []
        if q:
            clauses.append(
                "(id ILIKE %s OR name ILIKE %s OR description ILIKE %s "
                "OR owner ILIKE %s OR array_to_string(tags, ' ') ILIKE %s)"
            )
            params.extend([f"%{q}%"] * 5)
        if domain:
            clauses.append("domain = %s")
            params.append(domain)
        if layer:
            clauses.append("layer = %s")
            params.append(layer)
        if owner:
            clauses.append("owner = %s")
            params.append(owner)
        if cursor is not None:
            clauses.append("id > %s")
            params.append(cursor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit + 1)
        rows = _many(
            self.connection,
            f"""
            SELECT * FROM serving.catalog_datasets
            {where}
            ORDER BY id
            LIMIT %s
            """,
            params,
        )
        next_cursor = None
        if len(rows) > limit:
            rows = rows[:limit]
            next_cursor = rows[-1]["id"]
        return Page(rows=rows, next_cursor=next_cursor)

    def dataset(self, dataset_id: str) -> dict[str, Any] | None:
        return _one(
            self.connection,
            "SELECT * FROM serving.catalog_datasets WHERE id = %s",
            (dataset_id,),
        )

    # --------------------------------------------------------------- quality

    def quality_status(self) -> dict[str, Any]:
        run = _one(
            self.connection,
            "SELECT * FROM serving.dq_runs ORDER BY run_ts DESC LIMIT 1",
        )
        if run is None:
            return {"status": "unknown", "detail": "no quality run recorded yet"}
        failures = _many(
            self.connection,
            """
            SELECT suite, rule_id, severity, status, detail, observed, expected
            FROM serving.dq_results
            WHERE run_ts = %s AND status = 'fail'
            ORDER BY severity DESC, suite, rule_id
            """,
            (run["run_ts"],),
        )
        return {**run, "failures": failures}

    # ----------------------------------------------------------------- model

    def model_latest(self, model_name: str = "volatility_model") -> dict[str, Any] | None:
        return _one(
            self.connection,
            """
            SELECT * FROM serving.model_metrics
            WHERE model_name = %s
            ORDER BY (alias = 'champion') DESC, created_at DESC
            LIMIT 1
            """,
            (model_name,),
        )

    def champion(self, model_name: str = "volatility_model") -> dict[str, Any] | None:
        return _one(
            self.connection,
            """
            SELECT * FROM serving.model_metrics
            WHERE model_name = %s AND alias = 'champion'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (model_name,),
        )

    # ---------------------------------------------------------------- writes

    def upsert_market_hourly(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [dict(row) for row in rows]
        if not payload:
            return 0
        sql = f"""
            INSERT INTO serving.market_hourly ({', '.join(MARKET_COLUMNS)})
            VALUES ({', '.join(['%s'] * len(MARKET_COLUMNS))})
            ON CONFLICT (symbol, window_start) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                quote_volume = EXCLUDED.quote_volume,
                trade_count = EXCLUDED.trade_count,
                vwap = EXCLUDED.vwap,
                log_return_1h = EXCLUDED.log_return_1h,
                realized_vol_1h = EXCLUDED.realized_vol_1h,
                rv_ewma_24h = EXCLUDED.rv_ewma_24h,
                source = EXCLUDED.source,
                event_date = EXCLUDED.event_date,
                updated_at = EXCLUDED.updated_at,
                loaded_at = now()
        """
        with self.connection.cursor() as cursor:
            cursor.executemany(
                sql, [[row[column] for column in MARKET_COLUMNS] for row in payload]
            )
        self.connection.commit()
        return len(payload)

    def upsert_market_latest(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [dict(row) for row in rows]
        if not payload:
            return 0
        columns = [column for column in MARKET_COLUMNS if column != "event_date"]
        sql = f"""
            INSERT INTO serving.market_latest ({', '.join(columns)})
            VALUES ({', '.join(['%s'] * len(columns))})
            ON CONFLICT (symbol) DO UPDATE SET
                window_start = EXCLUDED.window_start,
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                quote_volume = EXCLUDED.quote_volume,
                trade_count = EXCLUDED.trade_count,
                vwap = EXCLUDED.vwap,
                log_return_1h = EXCLUDED.log_return_1h,
                realized_vol_1h = EXCLUDED.realized_vol_1h,
                rv_ewma_24h = EXCLUDED.rv_ewma_24h,
                source = EXCLUDED.source,
                updated_at = EXCLUDED.updated_at,
                loaded_at = now()
            WHERE serving.market_latest.window_start <= EXCLUDED.window_start
        """
        with self.connection.cursor() as cursor:
            cursor.executemany(
                sql, [[row[column] for column in columns] for row in payload]
            )
        self.connection.commit()
        return len(payload)

    def upsert_sentiment(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [dict(row) for row in rows]
        if not payload:
            return 0
        sql = f"""
            INSERT INTO serving.sentiment_hourly ({', '.join(SENTIMENT_COLUMNS)})
            VALUES ({', '.join(['%s'] * len(SENTIMENT_COLUMNS))})
            ON CONFLICT (window_start) DO UPDATE SET
                post_count = EXCLUDED.post_count,
                unique_authors = EXCLUDED.unique_authors,
                mean_sentiment = EXCLUDED.mean_sentiment,
                positive_share = EXCLUDED.positive_share,
                negative_share = EXCLUDED.negative_share,
                neutral_share = EXCLUDED.neutral_share,
                total_likes = EXCLUDED.total_likes,
                total_reposts = EXCLUDED.total_reposts,
                total_replies = EXCLUDED.total_replies,
                engagement_per_post = EXCLUDED.engagement_per_post,
                top_hashtags = EXCLUDED.top_hashtags,
                sentiment_model_version = EXCLUDED.sentiment_model_version,
                event_date = EXCLUDED.event_date,
                updated_at = EXCLUDED.updated_at,
                loaded_at = now()
        """
        with self.connection.cursor() as cursor:
            cursor.executemany(
                sql, [[row[column] for column in SENTIMENT_COLUMNS] for row in payload]
            )
        self.connection.commit()
        return len(payload)

    def upsert_freshness(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [dict(row) for row in rows]
        if not payload:
            return 0
        columns = (
            "metric",
            "data_ts",
            "age_seconds",
            "slo_seconds",
            "status",
            "clock",
            "as_of",
        )
        sql = f"""
            INSERT INTO serving.freshness ({', '.join(columns)}, computed_at)
            VALUES ({', '.join(['%s'] * len(columns))}, now())
            ON CONFLICT (metric) DO UPDATE SET
                data_ts = EXCLUDED.data_ts,
                age_seconds = EXCLUDED.age_seconds,
                slo_seconds = EXCLUDED.slo_seconds,
                status = EXCLUDED.status,
                clock = EXCLUDED.clock,
                as_of = EXCLUDED.as_of,
                computed_at = now()
        """
        with self.connection.cursor() as cursor:
            cursor.executemany(
                sql, [[row[column] for column in columns] for row in payload]
            )
        self.connection.commit()
        return len(payload)

    def replace_quality(self, report: dict[str, Any], *, report_path: str) -> str:
        run_ts = _parse_ts(report.get("generated_at")) or datetime.now(UTC)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO serving.dq_runs
                    (run_ts, status, critical_failures, warning_failures,
                     commit_sha, warning_only, report_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_ts) DO UPDATE SET
                    status = EXCLUDED.status,
                    critical_failures = EXCLUDED.critical_failures,
                    warning_failures = EXCLUDED.warning_failures,
                    commit_sha = EXCLUDED.commit_sha,
                    warning_only = EXCLUDED.warning_only,
                    report_path = EXCLUDED.report_path,
                    loaded_at = now()
                """,
                (
                    run_ts,
                    str(report.get("status") or "unknown"),
                    int(report.get("critical_failures") or 0),
                    int(report.get("warning_failures") or 0),
                    report.get("commit"),
                    bool(report.get("warning_only", False)),
                    report_path,
                ),
            )
            for suite in report.get("suites") or ():
                for rule in suite.get("rules") or ():
                    cursor.execute(
                        """
                        INSERT INTO serving.dq_results
                            (run_ts, suite, dataset, rule_id, severity, status,
                             detail, observed, expected)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT (run_ts, suite, rule_id) DO UPDATE SET
                            dataset = EXCLUDED.dataset,
                            severity = EXCLUDED.severity,
                            status = EXCLUDED.status,
                            detail = EXCLUDED.detail,
                            observed = EXCLUDED.observed,
                            expected = EXCLUDED.expected
                        """,
                        (
                            run_ts,
                            suite.get("suite"),
                            suite.get("dataset"),
                            rule.get("id"),
                            rule.get("severity"),
                            rule.get("status"),
                            rule.get("detail"),
                            json.dumps(rule.get("observed"), default=str),
                            str(rule.get("expected") or ""),
                        ),
                    )
        self.connection.commit()
        return iso(run_ts) or ""

    def upsert_registry(self, rows: Iterable[dict[str, Any]]) -> int:
        payload = [dict(row) for row in rows]
        if not payload:
            return 0
        with self.connection.cursor() as cursor:
            for row in payload:
                cursor.execute(
                    """
                    INSERT INTO serving.catalog_datasets
                        (id, name, layer, domain, kind, location, description,
                         owner, classification, retention_days, refresh_schedule,
                         sla, license, contains_pii, tags, schema_json, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        layer = EXCLUDED.layer,
                        domain = EXCLUDED.domain,
                        kind = EXCLUDED.kind,
                        location = EXCLUDED.location,
                        description = EXCLUDED.description,
                        owner = EXCLUDED.owner,
                        classification = EXCLUDED.classification,
                        retention_days = EXCLUDED.retention_days,
                        refresh_schedule = EXCLUDED.refresh_schedule,
                        sla = EXCLUDED.sla,
                        license = EXCLUDED.license,
                        contains_pii = EXCLUDED.contains_pii,
                        tags = EXCLUDED.tags,
                        schema_json = COALESCE(
                            EXCLUDED.schema_json, serving.catalog_datasets.schema_json
                        ),
                        updated_at = now()
                    """,
                    (
                        row["id"],
                        row["name"],
                        row["layer"],
                        row["domain"],
                        row["kind"],
                        row["location"],
                        row["description"],
                        row["owner"],
                        row["classification"],
                        int(row["retention_days"]),
                        row.get("refresh_schedule"),
                        row.get("sla"),
                        row.get("license"),
                        bool(row.get("contains_pii", False)),
                        list(row.get("tags") or ()),
                        json.dumps(row.get("schema")) if row.get("schema") else None,
                    ),
                )
        self.connection.commit()
        return len(payload)

    def insert_prediction(
        self,
        *,
        symbol: str,
        window_start: datetime,
        status: str,
        detail: str | None = None,
        model_name: str = "none",
        model_version: str = "none",
        model_alias: str = "none",
        predicted_rv_next_1h: float | None = None,
        request_id: str | None = None,
        input_hash: str | None = None,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO serving.predictions
                    (symbol, window_start, model_version, model_name, model_alias,
                     predicted_rv_next_1h, predicted_at, status, detail, request_id,
                     input_hash)
                VALUES (%s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s)
                ON CONFLICT (symbol, window_start, model_version) DO UPDATE SET
                    predicted_rv_next_1h = EXCLUDED.predicted_rv_next_1h,
                    predicted_at = now(),
                    status = EXCLUDED.status,
                    detail = EXCLUDED.detail,
                    request_id = EXCLUDED.request_id,
                    input_hash = EXCLUDED.input_hash
                """,
                (
                    symbol,
                    window_start,
                    model_version,
                    model_name,
                    model_alias,
                    predicted_rv_next_1h,
                    status,
                    detail,
                    request_id,
                    input_hash,
                ),
            )
        except (UndefinedTable, InvalidSchemaName) as exc:
            raise ServingNotReady(
                "serving.predictions does not exist yet; run scripts/serve_load.py"
            ) from exc
        self.connection.commit()

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in (
            "serving.market_hourly",
            "serving.market_latest",
            "serving.sentiment_hourly",
            "serving.predictions",
            "serving.freshness",
            "serving.catalog_datasets",
            "serving.dq_runs",
        ):
            row = self.connection.execute(f"SELECT count(*) AS n FROM {table}").fetchone()
            result[table] = int(row["n"])
        return result


def _page(rows: list[dict[str, Any]], limit: int) -> Page:
    if len(rows) > limit:
        rows = rows[:limit]
        return Page(rows=rows, next_cursor=encode_cursor(rows[-1]["window_start"]))
    return Page(rows=rows)


def _clean(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: value for key, value in row.items() if key != "loaded_at"}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
