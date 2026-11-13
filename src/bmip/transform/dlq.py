"""Dead-letter topic publisher for rejected market records."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from confluent_kafka import Consumer, KafkaException, Producer

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.ingestion.kafka import ensure_topic

log = get_logger(__name__)


def read_dlq(
    settings: Settings,
    *,
    topic: str | None = None,
    max_messages: int = 1000,
    idle_timeout: float = 3.0,
) -> list[dict[str, Any]]:
    topic = topic or settings.market_dlq_topic
    ensure_topic(settings.redpanda_brokers, topic)
    consumer = Consumer(
        {
            "bootstrap.servers": settings.redpanda_brokers,
            "group.id": f"dlq-reader-{uuid.uuid4().hex[:12]}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    consumer.subscribe([topic])
    records: list[dict[str, Any]] = []
    last_activity = time.monotonic()
    try:
        while len(records) < max_messages:
            messages = consumer.consume(
                num_messages=min(100, max_messages - len(records)),
                timeout=0.5,
            )
            if not messages:
                if time.monotonic() - last_activity >= idle_timeout:
                    break
                continue
            last_activity = time.monotonic()
            for message in messages:
                if message.error() is not None:
                    continue
                try:
                    record = json.loads(message.value())
                except (TypeError, ValueError):
                    continue
                if isinstance(record, dict):
                    records.append(record)
    finally:
        consumer.close()
    return records


class DlqPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.topic = settings.market_dlq_topic

    def publish(self, records: list[dict[str, Any]]) -> int:
        if not records:
            return 0
        ensure_topic(self.settings.redpanda_brokers, self.topic)
        producer = Producer(
            {
                "bootstrap.servers": self.settings.redpanda_brokers,
                "acks": "all",
                "enable.idempotence": True,
                "message.timeout.ms": 15000,
            }
        )
        delivered = 0
        errors: list[Any] = []

        def on_delivery(error: Any, _message: Any) -> None:
            nonlocal delivered
            if error is not None:
                errors.append(error)
                return
            delivered += 1

        for record in records:
            producer.produce(
                self.topic,
                key=str(record.get("quarantine_id", "")).encode("utf-8"),
                value=json.dumps(record, default=str, separators=(",", ":")).encode("utf-8"),
                on_delivery=on_delivery,
            )
            producer.poll(0)
        producer.flush(timeout=30)
        if errors:
            raise KafkaException(errors[0])
        log.info(
            "market records sent to dlq",
            extra={"ctx_topic": self.topic, "ctx_count": delivered},
        )
        return delivered
