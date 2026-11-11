"""Redpanda/Kafka producer for validated market trades."""

from __future__ import annotations

import json
from typing import Any

from confluent_kafka import KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic

from bmip.common.logging import get_logger

log = get_logger(__name__)

RETENTION_MS = 7 * 24 * 60 * 60 * 1000


def ensure_topic(brokers: str, topic: str, partitions: int = 3) -> None:
    admin = AdminClient({"bootstrap.servers": brokers})
    metadata = admin.list_topics(timeout=10)
    if topic in metadata.topics:
        return
    futures = admin.create_topics(
        [
            NewTopic(
                topic,
                num_partitions=partitions,
                replication_factor=1,
                config={"retention.ms": str(RETENTION_MS), "cleanup.policy": "delete"},
            )
        ]
    )
    for future in futures.values():
        try:
            future.result(timeout=30)
            log.info("topic created", extra={"ctx_topic": topic, "ctx_partitions": partitions})
        except KafkaException as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise


def publish_market_trades(
    brokers: str,
    topic: str,
    records: list[dict[str, Any]],
) -> int:
    ensure_topic(brokers, topic)
    producer = Producer(
        {
            "bootstrap.servers": brokers,
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
            topic,
            key=str(record["trade_id"]).encode("utf-8"),
            value=json.dumps(record, separators=(",", ":"), default=str).encode("utf-8"),
            on_delivery=on_delivery,
        )
        producer.poll(0)
    producer.flush(timeout=30)
    if errors:
        raise KafkaException(errors[0])
    log.info("market trades published", extra={"ctx_topic": topic, "ctx_count": delivered})
    return delivered
