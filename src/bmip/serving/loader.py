"""Gold -> serving loader (W1-D).

The loader is the only writer of the serving schema. It reads the published
Iceberg marts, upserts them into PostgreSQL keyed by their natural primary key,
refreshes the freshness table, imports the last Great Expectations report, and
publishes the dataset registry.

Idempotency is structural: every insert is ``ON CONFLICT ... DO UPDATE`` and
``logical_hash`` ignores load timestamps, so publishing the same gold twice
returns the same rows and the same hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.serving import freshness as freshness_policy
from bmip.serving.registry import (
    iceberg_columns,
    load_registry,
    postgres_columns,
)
from bmip.serving.repository import (
    MARKET_COLUMNS,
    SENTIMENT_COLUMNS,
    ServingRepository,
    connect,
    ensure_schema,
)

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]

MART_MARKET = "gold.mart_market"
MART_SENTIMENT = "gold.mart_sentiment"

FRESHNESS_MARKET = "market"
FRESHNESS_SENTIMENT = "sentiment"
FRESHNESS_PREDICTIONS = "predictions"
FRESHNESS_QUALITY = "quality"

IGNORED_IN_HASH = ("loaded_at", "updated_at", "computed_at")


class LoaderError(RuntimeError):
    """Raised when gold cannot be read or the serving schema cannot be written."""


@dataclass
class LoadResult:
    counts: dict[str, int] = field(default_factory=dict)
    freshness: list[dict[str, Any]] = field(default_factory=list)
    logical_hash: str = ""
    market_rows: int = 0
    sentiment_rows: int = 0
    quality_run: str | None = None
    registry_rows: int = 0
    started_at: str = ""
    finished_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "freshness": self.freshness,
            "logical_hash": self.logical_hash,
            "market_rows": self.market_rows,
            "sentiment_rows": self.sentiment_rows,
            "quality_run": self.quality_run,
            "registry_rows": self.registry_rows,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def _arrow_rows(settings: Settings, identifier: str) -> list[dict[str, Any]]:
    from bmip.transform.iceberg import load_rest_catalog, table_with_host_io

    try:
        catalog = load_rest_catalog(settings, "api")
        table = table_with_host_io(catalog, settings, identifier, "api")
        arrow = table.scan().to_arrow()
    except Exception as exc:  # noqa: BLE001 - surface a precise loader error
        raise LoaderError(
            f"cannot read {identifier} with the svc-api credentials: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    return arrow.to_pylist()


def _market_rows(
    raw: list[dict[str, Any]], *, start: datetime | None, end: datetime | None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in raw:
        window_start = _ts(row.get("window_start"))
        if window_start is None:
            continue
        if start is not None and window_start < start:
            continue
        if end is not None and window_start >= end:
            continue
        rows.append(
            {
                "symbol": str(row["symbol"]),
                "window_start": window_start,
                "open": _decimal(row.get("open")),
                "high": _decimal(row.get("high")),
                "low": _decimal(row.get("low")),
                "close": _decimal(row.get("close")),
                "volume": _decimal(row.get("volume")),
                "quote_volume": _decimal(row.get("quote_volume")),
                "trade_count": int(row.get("trade_count") or 0),
                "vwap": _decimal(row.get("vwap")),
                "log_return_1h": _float(row.get("log_return_1h")),
                "realized_vol_1h": _float(row.get("realized_vol_1h")),
                "rv_ewma_24h": _float(row.get("rv_ewma_24h")),
                "source": str(row.get("source") or "unknown"),
                "event_date": _date(row.get("event_date"), window_start),
                "updated_at": _ts(row.get("updated_at")) or datetime.now(UTC),
            }
        )
    rows.sort(key=lambda item: (item["symbol"], item["window_start"]))
    return rows


def _sentiment_rows(
    raw: list[dict[str, Any]], *, start: datetime | None, end: datetime | None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in raw:
        window_start = _ts(row.get("window_start"))
        if window_start is None:
            continue
        if start is not None and window_start < start:
            continue
        if end is not None and window_start >= end:
            continue
        rows.append(
            {
                "window_start": window_start,
                "post_count": int(row.get("post_count") or 0),
                "unique_authors": int(row.get("unique_authors") or 0),
                "mean_sentiment": _float(row.get("mean_sentiment")),
                "positive_share": _float(row.get("positive_share")),
                "negative_share": _float(row.get("negative_share")),
                "neutral_share": _float(row.get("neutral_share")),
                "total_likes": int(row.get("total_likes") or 0),
                "total_reposts": int(row.get("total_reposts") or 0),
                "total_replies": int(row.get("total_replies") or 0),
                "engagement_per_post": _float(row.get("engagement_per_post")),
                "top_hashtags": list(row.get("top_hashtags") or []),
                "sentiment_model_version": str(
                    row.get("sentiment_model_version") or "unknown"
                ),
                "event_date": _date(row.get("event_date"), window_start),
                "updated_at": _ts(row.get("updated_at")) or datetime.now(UTC),
            }
        )
    rows.sort(key=lambda item: item["window_start"])
    return rows


def _latest_per_symbol(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = latest.get(row["symbol"])
        if current is None or row["window_start"] > current["window_start"]:
            latest[row["symbol"]] = row
    return list(latest.values())


def _freshness_rows(
    settings: Settings,
    market: list[dict[str, Any]],
    sentiment: list[dict[str, Any]],
    quality_run: datetime | None,
) -> list[dict[str, Any]]:
    as_of = freshness_policy.parse_as_of(settings.bmip_as_of)
    now, clock = freshness_policy.clock_for(as_of)
    entries = [
        (
            FRESHNESS_MARKET,
            _max_hour_end(row["window_start"] for row in market),
            settings.freshness_market_slo_seconds,
        ),
        (
            FRESHNESS_SENTIMENT,
            _max_hour_end(row["window_start"] for row in sentiment),
            settings.freshness_sentiment_slo_seconds,
        ),
        (
            FRESHNESS_QUALITY,
            quality_run,
            settings.freshness_quality_slo_seconds,
        ),
    ]
    return [
        freshness_policy.compute(
            metric, data_ts, slo, now=now, clock=clock
        ).as_dict()
        for metric, data_ts, slo in entries
    ]


def _max_hour_end(values) -> datetime | None:
    stamps = [value for value in values if value is not None]
    if not stamps:
        return None
    return freshness_policy.hour_end(max(stamps))


def load_quality_report(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log.warning(
            "dq report is not valid json",
            extra={"ctx_path": str(path), "ctx_error": str(exc)},
        )
        return None


def logical_hash(rows: list[dict[str, Any]], ignore: tuple[str, ...] = IGNORED_IN_HASH) -> str:
    cleaned = [
        {key: value for key, value in row.items() if key not in ignore} for row in rows
    ]
    ordered = sorted(json.dumps(row, sort_keys=True, default=str) for row in cleaned)
    return hashlib.sha256("\n".join(ordered).encode("utf-8")).hexdigest()


def load_serving(
    settings: Settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    with_registry: bool = True,
    with_quality: bool = True,
    default_prediction_slo: bool = True,
) -> LoadResult:
    started = datetime.now(UTC)
    result = LoadResult(started_at=freshness_policy.iso(started) or "")

    market_raw = _arrow_rows(settings, MART_MARKET)
    sentiment_raw = _arrow_rows(settings, MART_SENTIMENT)
    market = _market_rows(market_raw, start=start, end=end)
    sentiment = _sentiment_rows(sentiment_raw, start=start, end=end)
    if not market:
        if start is None and end is None:
            raise LoaderError(f"{MART_MARKET} produced no rows")
        log.warning(
            "no market rows in the requested range; serving left untouched",
            extra={"ctx_start": str(start), "ctx_end": str(end)},
        )
        result.finished_at = freshness_policy.iso(datetime.now(UTC)) or ""
        with connect(settings) as connection:
            result.counts = ServingRepository(
                settings, connection=connection
            ).counts()
        return result

    with connect(settings) as connection:
        ensure_schema(connection)
        repository = ServingRepository(settings, connection=connection)
        result.market_rows = repository.upsert_market_hourly(market)
        result.counts["market_latest"] = repository.upsert_market_latest(
            _latest_per_symbol(market)
        )
        result.sentiment_rows = repository.upsert_sentiment(sentiment)

        quality_payload = None
        report_path = Path(settings.dq_report_path)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        if with_quality:
            quality_payload = load_quality_report(report_path)
            if quality_payload is not None:
                result.quality_run = repository.replace_quality(
                    quality_payload, report_path=str(report_path)
                )
            else:
                log.warning(
                    "dq report not found; quality status stays unknown",
                    extra={"ctx_path": str(report_path)},
                )

        quality_run = _parse_dt(result.quality_run)
        freshness_rows = _freshness_rows(settings, market, sentiment, quality_run)
        if default_prediction_slo:
            freshness_rows.append(
                _prediction_freshness(settings, repository)
            )
        repository.upsert_freshness(freshness_rows)
        result.freshness = freshness_rows

        if with_registry:
            result.registry_rows = repository.upsert_registry(
                _registry_rows(settings, connection)
            )
        result.counts = repository.counts()

    result.logical_hash = logical_hash(
        [
            {key: value for key, value in row.items() if key in MARKET_COLUMNS}
            for row in market
        ]
        + [
            {key: value for key, value in row.items() if key in SENTIMENT_COLUMNS}
            for row in sentiment
        ]
    )
    result.finished_at = freshness_policy.iso(datetime.now(UTC)) or ""
    log.info(
        "serving loaded",
        extra={
            "ctx_market_rows": result.market_rows,
            "ctx_sentiment_rows": result.sentiment_rows,
            "ctx_registry_rows": result.registry_rows,
            "ctx_hash": result.logical_hash[:12],
        },
    )
    return result


def _prediction_freshness(
    settings: Settings, repository: ServingRepository
) -> dict[str, Any]:
    as_of = freshness_policy.parse_as_of(settings.bmip_as_of)
    now, clock = freshness_policy.clock_for(as_of)
    row = repository.connection.execute(
        "SELECT max(predicted_at) AS ts FROM serving.predictions WHERE status = 'ok'"
    ).fetchone()
    data_ts = _parse_dt(row["ts"] if row else None)
    return freshness_policy.compute(
        FRESHNESS_PREDICTIONS,
        data_ts,
        settings.freshness_predictions_slo_seconds,
        now=now,
        clock=clock,
    ).as_dict()


def _registry_rows(settings: Settings, connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for dataset in load_registry(settings):
        schema = None
        if dataset.kind == "iceberg":
            schema = iceberg_columns(settings, dataset.location)
        else:
            try:
                schema = postgres_columns(connection, dataset.location)
            except Exception as exc:  # noqa: BLE001 - metadata must not block the load
                log.warning(
                    "postgres schema lookup failed",
                    extra={
                        "ctx_dataset": dataset.id,
                        "ctx_error": f"{type(exc).__name__}: {exc}",
                    },
                )
        payload = dataset.row()
        payload["schema"] = schema
        rows.append(payload)
    return rows


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value if value is not None else 0))


def _float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _date(value: Any, fallback: datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return fallback.date()


def _parse_dt(value: Any) -> datetime | None:
    return _ts(value)


def prune_serving(settings: Settings, *, days: int = 30) -> dict[str, int]:
    """Trim the serving copy; Iceberg keeps the history."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with connect(settings) as connection:
        repository = ServingRepository(settings, connection=connection)
        deleted: dict[str, int] = {}
        for table in ("serving.market_hourly", "serving.sentiment_hourly"):
            cursor = connection.execute(
                f"DELETE FROM {table} WHERE window_start < %s", (cutoff,)
            )
            deleted[table] = cursor.rowcount or 0
        connection.commit()
        deleted["remaining_market"] = repository.counts()["serving.market_hourly"]
        return deleted
