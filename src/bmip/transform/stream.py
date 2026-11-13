"""Redpanda consumer that feeds the silver market pipeline."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.transform.market import (
    MarketTrade,
    classify_late,
    compute_watermark,
    dedupe_trades,
    parse_trade,
    quarantine_record,
)
from bmip.transform.metrics import Metrics, build_stream_metrics

log = get_logger(__name__)

OFFSET_UNAVAILABLE = -1001


def decode_trade(payload: bytes | None) -> tuple[dict[str, Any] | None, str | None]:
    if payload is None:
        return None, "empty payload"
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"invalid json: {exc}"
    if not isinstance(raw, dict):
        return None, "payload is not a json object"
    missing = [key for key in ("symbol", "trade_id") if key not in raw]
    if missing:
        return None, f"missing fields: {','.join(missing)}"
    return raw, None


def quarantine_reason(error: str) -> str:
    if error.startswith("invalid json"):
        return "malformed_json"
    if error == "empty payload":
        return "empty_payload"
    if error.startswith("missing fields"):
        return "schema_violation"
    if error == "payload is not a json object":
        return "not_an_object"
    return "decode_error"


def event_timestamp(raw: dict[str, Any]) -> datetime | None:
    value = raw.get("event_ts")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raw_time = raw.get("T")
    if raw_time is not None:
        try:
            number = int(raw_time)
        except (TypeError, ValueError):
            return None
        divisor = 1_000_000 if number > 10**14 else 1_000
        return datetime.fromtimestamp(number / divisor, tz=UTC)
    return None


def sum_lag(high_low: list[tuple[int, int]]) -> int:
    return sum(max(high - position, 0) for high, position in high_low)


def _consumer_config(settings: Settings, group: str, client_id: str) -> dict[str, Any]:
    return {
        "bootstrap.servers": settings.redpanda_brokers,
        "group.id": group,
        "client.id": client_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
        "enable.auto.offset.store": True,
    }


def consumer_lag(consumer: Consumer) -> int:
    pairs: list[tuple[int, int]] = []
    for partition in consumer.assignment():
        try:
            low, high = consumer.get_watermark_offsets(partition, timeout=1.0, cached=False)
            positions = consumer.position([partition])
        except KafkaException:
            continue
        position = positions[0].offset if positions else -1
        if position < 0:
            position = low
        pairs.append((high, position))
    return sum_lag(pairs)


def group_lag(settings: Settings, group: str, topic: str | None = None) -> dict[str, Any]:
    topic = topic or settings.market_topic
    consumer = Consumer(_consumer_config(settings, group, "bmip-lag-reader"))
    try:
        metadata = consumer.list_topics(topic, timeout=10)
        if topic not in metadata.topics:
            raise ValueError(f"topic {topic} does not exist")
        partitions = [
            TopicPartition(topic, partition.id)
            for partition in metadata.topics[topic].partitions.values()
        ]
        committed = {tp.partition: tp.offset for tp in consumer.committed(partitions, timeout=10)}
        rows: list[dict[str, Any]] = []
        pairs: list[tuple[int, int]] = []
        for tp in partitions:
            low, high = consumer.get_watermark_offsets(tp, timeout=5, cached=False)
            offset = committed.get(tp.partition, OFFSET_UNAVAILABLE)
            position = low if offset < 0 else offset
            pairs.append((high, position))
            rows.append(
                {
                    "partition": tp.partition,
                    "committed": None if offset < 0 else offset,
                    "low": low,
                    "high": high,
                    "lag": max(high - position, 0),
                }
            )
        return {"group": group, "topic": topic, "total_lag": sum_lag(pairs), "partitions": rows}
    finally:
        consumer.close()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def replay_range(
    settings: Settings,
    *,
    start: datetime,
    end: datetime,
    group: str | None = None,
    topic: str | None = None,
    sink: Any | None = None,
    metrics: Metrics | None = None,
    max_records: int | None = None,
    idle_timeout: float = 5.0,
) -> dict[str, Any]:
    from bmip.transform.silver import MarketSink

    start = _aware(start)
    end = _aware(end)
    if end < start:
        raise ValueError("replay end must be greater than or equal to start")
    topic = topic or settings.market_topic
    group = group or f"{settings.stream_consumer_group}-replay"
    metrics = metrics or build_stream_metrics()
    consumer = Consumer(_consumer_config(settings, group, "bmip-replay"))
    processor: MarketStreamProcessor | None = None
    try:
        metadata = consumer.list_topics(topic, timeout=10)
        if topic not in metadata.topics:
            raise ValueError(f"topic {topic} does not exist")
        partitions: list[TopicPartition] = []
        for partition in metadata.topics[topic].partitions.values():
            low, high = consumer.get_watermark_offsets(
                TopicPartition(topic, partition.id),
                timeout=5,
                cached=False,
            )
            probe = TopicPartition(topic, partition.id)
            try:
                found = consumer.offsets_for_times(
                    [probe],
                    timeout=10,
                )
                offset = found[0].offset if found and found[0] is not None else high
            except KafkaException:
                offset = low
            if offset is None or offset < 0:
                offset = high
            partitions.append(
                TopicPartition(topic, partition.id, max(low, min(offset, high)))
            )
        consumer.assign(partitions)
        processor = MarketStreamProcessor(
            settings,
            metrics,
            group=group,
            topic=topic,
            sink=sink if sink is not None else MarketSink(settings),
            consumer=consumer,
            subscribe=False,
        )
        result = processor.run_replay(
            start=start,
            end=end,
            max_records=max_records,
            idle_timeout=idle_timeout,
        )
        result["start"] = start.isoformat().replace("+00:00", "Z")
        result["end"] = end.isoformat().replace("+00:00", "Z")
        return result
    finally:
        if processor is None:
            consumer.close()


class MarketStreamProcessor:
    def __init__(
        self,
        settings: Settings,
        metrics: Metrics,
        group: str | None = None,
        topic: str | None = None,
        on_record: Callable[[dict[str, Any]], None] | None = None,
        sink: Any | None = None,
        consumer: Consumer | None = None,
        subscribe: bool = True,
    ) -> None:
        self.settings = settings
        self.metrics = metrics
        self.topic = topic or settings.market_topic
        self.group = group or settings.stream_consumer_group
        self.on_record = on_record
        self.sink = sink
        self._last_event_ts: datetime | None = None
        self._watermark: datetime | None = None
        self.consumer = consumer or Consumer(
            _consumer_config(settings, self.group, "bmip-stream-processor")
        )
        if subscribe:
            self.consumer.subscribe([self.topic])

    def _record_event(self, raw: dict[str, Any]) -> None:
        timestamp = event_timestamp(raw)
        if timestamp is None:
            return
        if self._last_event_ts is None or timestamp > self._last_event_ts:
            self._last_event_ts = timestamp
            self.metrics.set("bmip_last_event_timestamp_seconds", timestamp.timestamp())

    def _handle_message(self, message: Any) -> None:
        raw, error = decode_trade(message.value())
        if error is not None:
            self.metrics.inc("bmip_quarantine_total")
            log.warning(
                "market event rejected",
                extra={
                    "ctx_error": error,
                    "ctx_topic": message.topic(),
                    "ctx_partition": message.partition(),
                    "ctx_offset": message.offset(),
                },
            )
            return
        self.metrics.inc("bmip_ingest_events_total")
        self._record_event(raw)
        if self.on_record is not None:
            self.on_record(raw)

    def _collect_message(
        self,
        message: Any,
        valid: list[tuple[MarketTrade, str, dict[str, Any]]],
        rejected: list[dict[str, Any]],
    ) -> None:
        value = message.value()
        raw_text = value.decode("utf-8", errors="replace") if value is not None else ""
        raw, error = decode_trade(value)
        if error is not None:
            record = quarantine_record(
                quarantine_reason(error),
                raw_text,
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
                details=error,
            )
            rejected.append(record)
            log.warning(
                "market event rejected",
                extra={"ctx_reason": record["reason"], "ctx_offset": message.offset()},
            )
            return

        self.metrics.inc("bmip_ingest_events_total")
        self._record_event(raw)
        if self.on_record is not None:
            self.on_record(raw)

        trade, error = parse_trade(
            raw,
            allowed_symbols={self.settings.market_symbol},
        )
        if error is not None or trade is None:
            record = quarantine_record(
                error or "invalid_trade",
                raw_text,
                raw=raw,
                topic=message.topic(),
                partition=message.partition(),
                offset=message.offset(),
            )
            rejected.append(record)
            log.warning(
                "market event rejected",
                extra={"ctx_reason": record["reason"], "ctx_offset": message.offset()},
            )
            return
        valid.append((trade, raw_text, raw))

    def _persist_batch(
        self,
        valid: list[tuple[MarketTrade, str, dict[str, Any]]],
        rejected: list[dict[str, Any]],
    ) -> tuple[int, int]:
        trades = [item[0] for item in valid]
        self._watermark = compute_watermark(
            trades,
            timedelta(seconds=self.settings.stream_watermark_delay_seconds),
            self._watermark,
        )
        raw_by_key = {
            (trade.symbol, trade.trade_id): (raw_text, raw)
            for trade, raw_text, raw in valid
        }
        unique, duplicates = dedupe_trades(trades)
        accepted: list[MarketTrade] = []
        late_accepted = 0
        for trade in unique:
            reason = classify_late(
                trade,
                self._watermark,
                timedelta(minutes=self.settings.stream_correction_window_minutes),
            )
            raw_text, raw = raw_by_key[(trade.symbol, trade.trade_id)]
            if reason is not None:
                rejected.append(
                    quarantine_record(
                        reason,
                        raw_text,
                        raw=raw,
                        topic=self.topic,
                        details=(
                            f"watermark={self._watermark.isoformat() if self._watermark else None}"
                        ),
                    )
                )
                continue
            accepted.append(trade)
            if self._watermark is not None and trade.event_ts < self._watermark:
                late_accepted += 1

        stats = self.sink.persist(accepted, rejected)
        self.metrics.inc("bmip_duplicate_total", duplicates + stats.duplicates)
        self.metrics.inc("bmip_quarantine_total", stats.quarantined)
        self.metrics.inc("bmip_late_events_total", late_accepted)
        self.metrics.inc("bmip_ohlcv_rows_total", stats.ohlcv_rows)
        self._refresh_freshness()
        return duplicates + stats.duplicates, late_accepted

    def _refresh_freshness(self) -> None:
        freshness = getattr(self.sink, "freshness", None)
        if not callable(freshness):
            return
        try:
            value = freshness(symbol=self.settings.market_symbol)
        except Exception as exc:  # noqa: BLE001 - metrics must not fail a batch
            log.warning("cannot read silver freshness", extra={"ctx_error": str(exc)})
            return
        if value.ingest_lag_seconds is not None:
            self.metrics.set("bmip_freshness_seconds", value.ingest_lag_seconds)
        if value.bar_age_seconds is not None:
            self.metrics.set("bmip_silver_bar_age_seconds", value.bar_age_seconds)

    def _commit(self) -> None:
        self.consumer.commit(asynchronous=False)
        self.metrics.inc("bmip_commit_total")

    def _refresh_lag(self) -> int:
        lag = consumer_lag(self.consumer)
        self.metrics.set("bmip_consumer_lag", lag)
        return lag

    def run_replay(
        self,
        *,
        start: datetime | None = None,
        end: datetime,
        max_records: int | None = None,
        idle_timeout: float = 5.0,
    ) -> dict[str, Any]:
        processed = 0
        skipped = 0
        flushes = 0
        last_activity = time.monotonic()
        collected: list[tuple[datetime | None, int, int, Any]] = []
        try:
            while True:
                remaining = None if max_records is None else max_records - processed
                if remaining is not None and remaining <= 0:
                    break
                poll_size = self.settings.stream_poll_max_records
                if remaining is not None:
                    poll_size = min(poll_size, remaining)
                self.metrics.inc("bmip_stream_poll_total")
                messages = self.consumer.consume(
                    num_messages=poll_size,
                    timeout=self.settings.stream_poll_timeout_ms / 1000,
                )
                self.metrics.set("bmip_batch_size", len(messages))
                if not messages:
                    if time.monotonic() - last_activity >= idle_timeout:
                        break
                    continue
                last_activity = time.monotonic()
                for message in messages:
                    if message.error() is not None:
                        if message.error().code() != KafkaError._PARTITION_EOF:
                            log.warning(
                                "replay consumer error",
                                extra={"ctx_error": str(message.error())},
                            )
                        continue
                    raw, _ = decode_trade(message.value())
                    timestamp = event_timestamp(raw) if raw is not None else None
                    if timestamp is not None and (
                        timestamp > end or (start is not None and timestamp < start)
                    ):
                        skipped += 1
                        continue
                    collected.append(
                        (timestamp, message.partition(), message.offset(), message)
                    )
                    processed += 1
                    if max_records is not None and processed >= max_records:
                        break
                if max_records is not None and processed >= max_records:
                    break
        finally:
            self.consumer.close()

        latest = datetime.max.replace(tzinfo=UTC)
        collected.sort(
            key=lambda item: (
                item[0] is None,
                item[0] or latest,
                item[1],
                item[2],
            )
        )
        valid: list[tuple[MarketTrade, str, dict[str, Any]]] = []
        rejected: list[dict[str, Any]] = []
        current_minute: datetime | None = None

        def flush() -> None:
            nonlocal valid, rejected, flushes
            if not valid and not rejected:
                return
            self._persist_batch(valid, rejected)
            valid = []
            rejected = []
            flushes += 1

        for timestamp, _, _, message in collected:
            minute = timestamp.replace(second=0, microsecond=0) if timestamp else None
            if (
                current_minute is not None
                and minute is not None
                and minute != current_minute
            ):
                flush()
            if minute is not None:
                current_minute = minute
            self._collect_message(message, valid, rejected)
        flush()
        return {
            "group": self.group,
            "topic": self.topic,
            "processed": processed,
            "skipped": skipped,
            "flushes": flushes,
            "events_total": int(self.metrics.get("bmip_ingest_events_total")),
            "duplicates": int(self.metrics.get("bmip_duplicate_total")),
            "quarantined": int(self.metrics.get("bmip_quarantine_total")),
            "late_events": int(self.metrics.get("bmip_late_events_total")),
            "ohlcv_rows": int(self.metrics.get("bmip_ohlcv_rows_total")),
            "commits": int(self.metrics.get("bmip_commit_total")),
            "watermark": (
                self._watermark.isoformat().replace("+00:00", "Z")
                if self._watermark
                else None
            ),
            "last_event_ts": (
                self._last_event_ts.isoformat().replace("+00:00", "Z")
                if self._last_event_ts
                else None
            ),
        }

    def run(
        self,
        follow: bool = True,
        max_records: int | None = None,
        idle_timeout: float = 5.0,
        startup_delay: float = 0.0,
    ) -> dict[str, Any]:
        if startup_delay > 0:
            try:
                backlog = group_lag(self.settings, self.group, self.topic)
                self.metrics.set("bmip_consumer_lag", backlog["total_lag"])
            except Exception as exc:  # noqa: BLE001 - metrics must not block startup
                log.warning("cannot read initial lag", extra={"ctx_error": str(exc)})
            time.sleep(startup_delay)
        processed = 0
        lag = 0
        last_activity = time.monotonic()
        try:
            while True:
                remaining = None if max_records is None else max_records - processed
                if remaining is not None and remaining <= 0:
                    break
                poll_size = self.settings.stream_poll_max_records
                if remaining is not None:
                    poll_size = min(poll_size, remaining)
                self.metrics.inc("bmip_stream_poll_total")
                messages = self.consumer.consume(
                    num_messages=poll_size,
                    timeout=self.settings.stream_poll_timeout_ms / 1000,
                )
                self.metrics.set("bmip_batch_size", len(messages))
                if messages:
                    last_activity = time.monotonic()
                    valid: list[tuple[MarketTrade, str, dict[str, Any]]] = []
                    rejected: list[dict[str, Any]] = []
                    batch_processed = 0
                    for message in messages:
                        if message.error() is not None:
                            if message.error().code() != KafkaError._PARTITION_EOF:
                                log.warning(
                                    "consumer error",
                                    extra={"ctx_error": str(message.error())},
                                )
                            continue
                        if self.sink is None:
                            self._handle_message(message)
                        else:
                            self._collect_message(message, valid, rejected)
                        processed += 1
                        batch_processed += 1
                        if max_records is not None and processed >= max_records:
                            break
                    if self.sink is not None and batch_processed > 0:
                        self._persist_batch(valid, rejected)
                    if batch_processed > 0:
                        self._commit()
                    last_activity = time.monotonic()
                self._refresh_lag()
                if max_records is not None and processed >= max_records:
                    break
                if not follow and time.monotonic() - last_activity >= idle_timeout:
                    break
            lag = self._refresh_lag()
        finally:
            self.consumer.close()
        return {
            "group": self.group,
            "topic": self.topic,
            "processed": processed,
            "events_total": int(self.metrics.get("bmip_ingest_events_total")),
            "duplicates": int(self.metrics.get("bmip_duplicate_total")),
            "quarantined": int(self.metrics.get("bmip_quarantine_total")),
            "late_events": int(self.metrics.get("bmip_late_events_total")),
            "ohlcv_rows": int(self.metrics.get("bmip_ohlcv_rows_total")),
            "commits": int(self.metrics.get("bmip_commit_total")),
            "lag": lag,
            "watermark": (
                self._watermark.isoformat().replace("+00:00", "Z")
                if self._watermark
                else None
            ),
            "last_event_ts": (
                self._last_event_ts.isoformat().replace("+00:00", "Z")
                if self._last_event_ts
                else None
            ),
        }
