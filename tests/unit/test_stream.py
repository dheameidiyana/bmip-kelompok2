"""Tests for stream decoding and lag helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from confluent_kafka import KafkaError

from bmip.common.config import Settings
from bmip.transform import stream
from bmip.transform.market import SinkStats
from bmip.transform.metrics import build_stream_metrics
from bmip.transform.silver import SilverFreshness
from bmip.transform.stream import MarketStreamProcessor, decode_trade, event_timestamp, sum_lag


def test_decode_trade_accepts_contract_record() -> None:
    payload = json.dumps(
        {
            "symbol": "BTCUSDT",
            "trade_id": 900000001,
            "event_ts": "2026-11-10T14:00:01.123Z",
            "price": 68000.5,
            "qty": 0.0125,
        }
    ).encode("utf-8")
    raw, error = decode_trade(payload)
    assert error is None
    assert raw is not None
    assert raw["trade_id"] == 900000001


def test_decode_trade_rejects_invalid_json() -> None:
    raw, error = decode_trade(b"{not json")
    assert raw is None
    assert error is not None
    assert error.startswith("invalid json")


def test_decode_trade_rejects_missing_fields() -> None:
    raw, error = decode_trade(json.dumps({"symbol": "BTCUSDT"}).encode("utf-8"))
    assert raw is None
    assert error == "missing fields: trade_id"


def test_decode_trade_rejects_empty_payload() -> None:
    raw, error = decode_trade(None)
    assert raw is None
    assert error == "empty payload"


def test_event_timestamp_from_iso() -> None:
    parsed = event_timestamp({"event_ts": "2026-11-10T14:00:01.123Z"})
    assert parsed == datetime(2026, 11, 10, 14, 0, 1, 123000, tzinfo=UTC)


def test_event_timestamp_from_binance_ms() -> None:
    parsed = event_timestamp({"T": 1794319201123})
    assert parsed == datetime(2026, 11, 10, 14, 0, 1, 123000, tzinfo=UTC)


def test_event_timestamp_returns_none_for_bad_input() -> None:
    assert event_timestamp({}) is None
    assert event_timestamp({"event_ts": "not-a-date"}) is None
    assert event_timestamp({"T": "nope"}) is None


def test_sum_lag_never_negative() -> None:
    assert sum_lag([(10, 4), (5, 5), (3, 7)]) == 6
    assert sum_lag([]) == 0


class _FakeMessage:
    def __init__(self, value: bytes, error=None, offset: int = 0) -> None:
        self._value = value
        self._error = error
        self._offset = offset

    def value(self) -> bytes:
        return self._value

    def error(self):
        return self._error

    def topic(self) -> str:
        return "market.trades"

    def partition(self) -> int:
        return 0

    def offset(self) -> int:
        return self._offset


class _FakePosition:
    offset = 1


class _FakeError:
    def __init__(self, code: int) -> None:
        self._code = code

    def code(self) -> int:
        return self._code


class _FakeConsumer:
    def __init__(self, messages: list[_FakeMessage]) -> None:
        self.messages = list(messages)
        self.commits = 0
        self.closed = False

    def subscribe(self, topics: list[str]) -> None:
        self.topics = topics

    def consume(self, num_messages: int, timeout: float) -> list[_FakeMessage]:
        batch = self.messages[:num_messages]
        del self.messages[: len(batch)]
        return batch

    def commit(self, asynchronous: bool = True) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed = True

    def assignment(self) -> list[object]:
        return [object()]

    def get_watermark_offsets(self, partition, timeout: float, cached: bool):
        return (0, 5)

    def position(self, partitions, timeout: float = -1):
        return [_FakePosition() for _ in partitions]


def _settings(monkeypatch) -> Settings:
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    return Settings.from_env()


def _trade(trade_id: int) -> bytes:
    return json.dumps(
        {
            "symbol": "BTCUSDT",
            "trade_id": trade_id,
            "event_ts": "2026-11-10T14:00:01.123Z",
            "price": 68000.5,
            "qty": 0.0125,
        }
    ).encode("utf-8")


def _trade_at(trade_id: int, event_ts: str, price: float = 68000.5) -> bytes:
    return json.dumps(
        {
            "symbol": "BTCUSDT",
            "trade_id": trade_id,
            "event_ts": event_ts,
            "price": price,
            "qty": 0.01,
            "is_buyer_maker": False,
        }
    ).encode("utf-8")


class _FakeSink:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.accepted: list[object] = []
        self.rejected: list[dict[str, object]] = []
        self.calls = 0
        self.freshness_result = SilverFreshness(
            observed_at=datetime(2026, 11, 10, 14, 0, 10, tzinfo=UTC),
            latest_event_ts=datetime(2026, 11, 10, 14, 0, 1, tzinfo=UTC),
            latest_window_end=datetime(2026, 11, 10, 14, 1, tzinfo=UTC),
            ingest_lag_seconds=2.0,
            bar_age_seconds=0.0,
        )

    def persist(self, trades, rejected):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sink failed")
        self.accepted.extend(trades)
        self.rejected.extend(rejected)
        return SinkStats(
            accepted=len(trades),
            quarantined=len(rejected),
            ohlcv_rows=1 if trades else 0,
        )

    def freshness(self, *, symbol=None):
        return self.freshness_result


def test_processor_commits_after_processing(monkeypatch) -> None:
    fake = _FakeConsumer([_FakeMessage(_trade(1))])
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics)
    result = processor.run(follow=False, max_records=1, idle_timeout=0)

    assert result["processed"] == 1
    assert result["events_total"] == 1
    assert result["lag"] == 4
    assert fake.commits == 1
    assert fake.closed is True
    assert metrics.get("bmip_ingest_events_total") == 1


def test_processor_skips_commit_for_eof_only_batch(monkeypatch) -> None:
    fake = _FakeConsumer(
        [_FakeMessage(b"", error=_FakeError(KafkaError._PARTITION_EOF))]
    )
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics)
    result = processor.run(follow=False, max_records=1, idle_timeout=0)

    assert result["processed"] == 0
    assert fake.commits == 0
    assert fake.closed is True


def test_processor_quarantines_invalid_payload(monkeypatch) -> None:
    fake = _FakeConsumer([_FakeMessage(b"not-json")])
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics)
    result = processor.run(follow=False, max_records=1, idle_timeout=0)

    assert result["processed"] == 1
    assert result["events_total"] == 0
    assert result["quarantined"] == 1
    assert fake.commits == 1


def test_processor_with_sink_dedupes_batch(monkeypatch) -> None:
    fake = _FakeConsumer(
        [
            _FakeMessage(_trade_at(1, "2026-11-10T14:00:01.100Z")),
            _FakeMessage(_trade_at(1, "2026-11-10T14:00:01.100Z"), offset=1),
        ]
    )
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)
    result = processor.run(follow=False, max_records=2, idle_timeout=0)

    assert result["events_total"] == 2
    assert result["duplicates"] == 1
    assert result["ohlcv_rows"] == 1
    assert len(sink.accepted) == 1
    assert sink.rejected == []
    assert fake.commits == 1


def test_processor_sets_silver_freshness_metrics(monkeypatch) -> None:
    fake = _FakeConsumer([_FakeMessage(_trade_at(1, "2026-11-10T14:00:01.100Z"))])
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)
    processor.run(follow=False, max_records=1, idle_timeout=0)

    assert metrics.get("bmip_freshness_seconds") == 2.0
    assert metrics.get("bmip_silver_bar_age_seconds") == 0.0


def test_processor_with_sink_quarantines_malformed(monkeypatch) -> None:
    fake = _FakeConsumer(
        [
            _FakeMessage(b"{not-json"),
            _FakeMessage(_trade_at(1, "2026-11-10T14:00:01.100Z"), offset=1),
        ]
    )
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)
    result = processor.run(follow=False, max_records=2, idle_timeout=0)

    assert len(sink.accepted) == 1
    assert len(sink.rejected) == 1
    assert sink.rejected[0]["reason"] == "malformed_json"
    assert result["quarantined"] == 1
    assert fake.commits == 1


def test_processor_with_sink_quarantines_late_event(monkeypatch) -> None:
    fake = _FakeConsumer(
        [
            _FakeMessage(_trade_at(1, "2026-11-10T13:00:00Z")),
            _FakeMessage(_trade_at(2, "2026-11-10T14:10:00Z", price=68001), offset=1),
        ]
    )
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)
    result = processor.run(follow=False, max_records=2, idle_timeout=0)

    assert len(sink.accepted) == 1
    assert len(sink.rejected) == 1
    assert sink.rejected[0]["reason"] == "late_beyond_window"
    assert result["quarantined"] == 1
    assert fake.commits == 1


def test_replay_flushes_per_minute(monkeypatch) -> None:
    fake = _FakeConsumer(
        [
            _FakeMessage(_trade_at(1, "2026-11-10T14:00:01Z")),
            _FakeMessage(_trade_at(2, "2026-11-10T14:01:02Z"), offset=1),
        ]
    )
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink()

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)
    result = processor.run_replay(
        start=datetime(2026, 11, 10, 14, 0, tzinfo=UTC),
        end=datetime(2026, 11, 10, 14, 2, tzinfo=UTC),
        idle_timeout=0,
    )

    assert result["processed"] == 2
    assert result["flushes"] == 2
    assert sink.calls == 2
    assert result["commits"] == 0
    assert fake.commits == 0


def test_processor_does_not_commit_when_sink_fails(monkeypatch) -> None:
    fake = _FakeConsumer([_FakeMessage(_trade_at(1, "2026-11-10T14:00:01.100Z"))])
    monkeypatch.setattr(stream, "Consumer", lambda config: fake)
    metrics = build_stream_metrics()
    sink = _FakeSink(fail=True)

    processor = MarketStreamProcessor(_settings(monkeypatch), metrics, sink=sink)

    with pytest.raises(RuntimeError, match="sink failed"):
        processor.run(follow=False, max_records=1, idle_timeout=0)
    assert fake.commits == 0
    assert fake.closed is True
