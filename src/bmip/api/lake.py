"""Range queries over the Iceberg gold marts (W1-D).

Primary path: DuckDB attaches the Lakekeeper REST catalog and scans
``lake.gold.*`` directly, which keeps the query engine embedded and stateless.
Fallback: PyIceberg reads the same table through the same catalog. The fallback
exists because "DuckDB can attach the catalog" is an assumption (ARCHITECTURE
R04), not a fact, and a range endpoint that dies when that assumption breaks
would take the dashboard with it.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Protocol
from urllib.parse import urlparse

from bmip.common.config import Settings
from bmip.common.logging import get_logger

log = get_logger(__name__)

ATTACH_COOLDOWN_SECONDS = 30.0

MARKET_SELECT = (
    "symbol, window_start, open, high, low, close, volume, quote_volume, "
    "trade_count, vwap, log_return_1h, realized_vol_1h, rv_ewma_24h, source, "
    "event_date, updated_at"
)
SENTIMENT_SELECT = (
    "window_start, post_count, unique_authors, mean_sentiment, positive_share, "
    "negative_share, neutral_share, total_likes, total_reposts, total_replies, "
    "engagement_per_post, top_hashtags, sentiment_model_version, event_date, "
    "updated_at"
)


class LakeUnavailable(RuntimeError):
    """The lake path cannot answer; the caller falls back to PostgreSQL."""


class LakeReader(Protocol):
    name: str

    def market_range(
        self, symbol: str, start: Any, end: Any, limit: int
    ) -> list[dict[str, Any]]: ...

    def sentiment_range(
        self, start: Any, end: Any, limit: int
    ) -> list[dict[str, Any]]: ...

    def health(self) -> bool: ...


def build_lake(settings: Settings) -> LakeReader:
    if settings.lake_reader.lower() == "pyiceberg":
        return PyIcebergLakeReader(settings)
    try:
        import duckdb  # noqa: F401

        return DuckDBLakeReader(settings)
    except Exception as exc:  # noqa: BLE001 - fall back, never fail startup
        log.warning(
            "duckdb reader unavailable, using pyiceberg",
            extra={"ctx_error": f"{type(exc).__name__}: {exc}"},
        )
        return PyIcebergLakeReader(settings)


class DuckDBLakeReader:
    name = "duckdb"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._local = threading.local()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lake")
        self._cooldown_until = 0.0
        parsed = urlparse(settings.minio_endpoint)
        self._s3_endpoint = parsed.netloc or settings.minio_endpoint
        self._s3_ssl = parsed.scheme == "https"
        self._catalog_uri = f"{settings.lakekeeper_url.rstrip('/')}/catalog"

    # ------------------------------------------------------------- connection

    def _connection(self):
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        if time.monotonic() < self._cooldown_until:
            raise LakeUnavailable(
                "duckdb catalog attach is cooling down after a recent failure"
            )
        try:
            connection = self._build_connection()
        except LakeUnavailable:
            # Fail fast for a while instead of paying the attach timeout on
            # every request (and on every Docker healthcheck).
            self._cooldown_until = time.monotonic() + ATTACH_COOLDOWN_SECONDS
            raise
        self._cooldown_until = 0.0
        self._local.connection = connection
        return connection

    def _build_connection(self):
        import duckdb

        config: dict[str, Any] = {"threads": 2}
        if self.settings.duckdb_extension_dir:
            config["extension_directory"] = self.settings.duckdb_extension_dir
        connection = duckdb.connect(":memory:", config=config)
        try:
            connection.execute("INSTALL iceberg")
            connection.execute("LOAD iceberg")
            connection.execute("INSTALL httpfs")
            connection.execute("LOAD httpfs")
        except Exception as exc:  # noqa: BLE001
            raise LakeUnavailable(
                f"duckdb iceberg/httpfs extensions unavailable: {type(exc).__name__}: {exc}"
            ) from exc

        access_key, secret_key = self.settings.minio_credentials("api")
        connection.execute(f"SET s3_endpoint = '{self._s3_endpoint}'")
        connection.execute(f"SET s3_use_ssl = {'true' if self._s3_ssl else 'false'}")
        connection.execute("SET s3_url_style = 'path'")
        connection.execute(f"SET s3_access_key_id = '{access_key}'")
        connection.execute(f"SET s3_secret_access_key = '{secret_key}'")
        connection.execute(f"SET s3_region = '{self.settings.minio_region}'")
        self._attach(connection)
        return connection

    def _attach(self, connection) -> None:
        warehouse = self.settings.lakekeeper_warehouse
        uri = self._catalog_uri
        variants = [
            f"ATTACH '{warehouse}' AS lake (TYPE iceberg, ENDPOINT '{uri}', "
            "AUTHORIZATION_TYPE 'none')",
            f"ATTACH '{warehouse}' AS lake (TYPE iceberg, ENDPOINT '{uri}')",
        ]
        errors: list[str] = []
        for statement in variants:
            try:
                connection.execute(statement)
                log.info("duckdb attached iceberg catalog")
                return
            except Exception as exc:  # noqa: BLE001 - try the next dialect
                errors.append(f"{type(exc).__name__}: {exc}")
                if _attached(connection):
                    try:
                        connection.execute("DETACH lake")
                    except Exception:  # noqa: BLE001 - best effort
                        pass
        raise LakeUnavailable(
            "duckdb could not attach the Iceberg catalog: " + " | ".join(errors)
        )

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        def run() -> list[dict[str, Any]]:
            connection = self._connection()
            return connection.execute(sql, params).fetch_arrow_table().to_pylist()

        future = self._executor.submit(run)
        try:
            return future.result(timeout=self.settings.lake_query_timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            raise LakeUnavailable(
                f"lake query exceeded {self.settings.lake_query_timeout_seconds}s"
            ) from exc
        except LakeUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any engine error is a fallback
            raise LakeUnavailable(f"lake query failed: {type(exc).__name__}: {exc}") from exc

    # ---------------------------------------------------------------- queries

    def market_range(self, symbol, start, end, limit):
        clauses = ["symbol = ?"]
        params: list[Any] = [symbol]
        if start is not None:
            clauses.append("window_start >= ?")
            params.append(start)
        if end is not None:
            clauses.append("window_start < ?")
            params.append(end)
        params.append(int(limit))
        sql = (
            f"SELECT {MARKET_SELECT} FROM lake.gold.mart_market "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY window_start DESC LIMIT ?"
        )
        return self._query(sql, params)

    def sentiment_range(self, start, end, limit):
        clauses: list[str] = []
        params: list[Any] = []
        if start is not None:
            clauses.append("window_start >= ?")
            params.append(start)
        if end is not None:
            clauses.append("window_start < ?")
            params.append(end)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.append(int(limit))
        sql = (
            f"SELECT {SENTIMENT_SELECT} FROM lake.gold.mart_sentiment "
            f"{where}ORDER BY window_start DESC LIMIT ?"
        )
        return self._query(sql, params)

    def health(self) -> bool:
        """A real lake read, not just a DuckDB ping.

        ``SELECT 1`` succeeds even when MinIO is unreachable because it never
        touches object storage; readiness would then lie about the fallback.
        Reading one row from the gold table exercises the catalog, the S3
        endpoint, and the table metadata.
        """
        try:
            self._query(
                "SELECT symbol FROM lake.gold.mart_market LIMIT 1", []
            )
            return True
        except LakeUnavailable:
            return False


class PyIcebergLakeReader:
    name = "pyiceberg"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._catalog = None

    def _table(self, identifier: str):
        if self._catalog is None:
            from bmip.transform.iceberg import load_rest_catalog

            self._catalog = load_rest_catalog(self.settings, "api")
        from bmip.transform.iceberg import table_with_host_io

        return table_with_host_io(self._catalog, self.settings, identifier, "api")

    def _rows(self, identifier: str, columns: list[str]) -> list[dict[str, Any]]:
        try:
            table = self._table(identifier)
            arrow = table.scan(selected_fields=tuple(columns)).to_arrow()
        except Exception as exc:  # noqa: BLE001
            raise LakeUnavailable(
                f"pyiceberg read of {identifier} failed: {type(exc).__name__}: {exc}"
            ) from exc
        return arrow.to_pylist()

    def market_range(self, symbol, start, end, limit):
        rows = self._rows(
            "gold.mart_market",
            [
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
            ],
        )
        return _filter_market(rows, symbol, start, end, limit)

    def sentiment_range(self, start, end, limit):
        rows = self._rows(
            "gold.mart_sentiment",
            [
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
            ],
        )
        rows = [
            row
            for row in rows
            if _inside(row.get("window_start"), start, end)
        ]
        rows.sort(key=lambda row: row["window_start"], reverse=True)
        return rows[:limit]

    def health(self) -> bool:
        try:
            self._rows("gold.mart_market", ["symbol"])
            return True
        except LakeUnavailable:
            return False


def _attached(connection) -> bool:
    try:
        connection.execute("SELECT * FROM duckdb_databases() WHERE database_name = 'lake'")
        return bool(connection.fetchall())
    except Exception:  # noqa: BLE001
        return False


def _inside(value, start, end) -> bool:
    if value is None:
        return False
    if start is not None and value < start:
        return False
    if end is not None and value >= end:
        return False
    return True


def _filter_market(rows, symbol, start, end, limit):
    subset = [
        row
        for row in rows
        if row.get("symbol") == symbol and _inside(row.get("window_start"), start, end)
    ]
    subset.sort(key=lambda row: row["window_start"], reverse=True)
    return subset[:limit]
