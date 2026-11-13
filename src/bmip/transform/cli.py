"""Command line entry point for the market stream processor."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from bmip.common.config import Settings, get_settings
from bmip.common.logging import configure_logging, get_logger
from bmip.transform.metrics import MetricsServer, build_stream_metrics
from bmip.transform.stream import MarketStreamProcessor, group_lag, replay_range

log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BMIP stream processor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stream = subparsers.add_parser("stream", help="consume market trades from Redpanda")
    stream.add_argument("--follow", action="store_true", help="keep polling until stopped")
    stream.add_argument("--once", action="store_true", help="drain and exit after idle")
    stream.add_argument("--group", default=None, help="consumer group override")
    stream.add_argument("--topic", default=None, help="topic override")
    stream.add_argument("--max-records", type=int, default=None)
    stream.add_argument("--idle-timeout", type=float, default=None)
    stream.add_argument("--startup-delay", type=float, default=None)
    stream.add_argument("--metrics-host", default=None)
    stream.add_argument("--metrics-port", type=int, default=None)
    stream.add_argument("--no-metrics", action="store_true")
    stream.add_argument("--no-sink", action="store_true", help="skip silver and DLQ writes")

    lag = subparsers.add_parser("lag", help="print committed offsets and lag")
    lag.add_argument("--group", default=None)
    lag.add_argument("--topic", default=None)

    replay = subparsers.add_parser("replay", help="replay a market event-time range")
    replay.add_argument("--from", dest="from_ts", required=True, help="ISO-8601 start")
    replay.add_argument("--to", dest="to_ts", required=True, help="ISO-8601 end")
    replay.add_argument("--group", default=None, help="consumer group override")
    replay.add_argument("--topic", default=None, help="topic override")
    replay.add_argument("--max-records", type=int, default=None)
    replay.add_argument("--idle-timeout", type=float, default=5.0)
    return parser


def _stream(args: argparse.Namespace, settings: Settings) -> int:
    metrics = build_stream_metrics()
    server: MetricsServer | None = None
    if not args.no_metrics:
        host = args.metrics_host or settings.stream_metrics_host
        port = settings.stream_metrics_port if args.metrics_port is None else args.metrics_port
        server = MetricsServer(metrics, host, port).start()
        log.info("metrics server started", extra={"ctx_url": server.url})

    sink = None
    if not args.no_sink:
        from bmip.transform.silver import MarketSink

        sink = MarketSink(settings)
    processor = MarketStreamProcessor(
        settings,
        metrics,
        group=args.group,
        topic=args.topic,
        sink=sink,
    )
    try:
        result = processor.run(
            follow=not args.once,
            max_records=args.max_records,
            idle_timeout=(
                settings.stream_idle_exit_seconds
                if args.idle_timeout is None
                else args.idle_timeout
            ),
            startup_delay=(
                settings.stream_startup_delay_seconds
                if args.startup_delay is None
                else args.startup_delay
            ),
        )
    finally:
        if server is not None:
            server.stop()
    result["metrics"] = metrics.snapshot()
    print(json.dumps({"stream": result}, indent=2))
    return 0


def _lag(args: argparse.Namespace, settings: Settings) -> int:
    result = group_lag(
        settings,
        args.group or settings.stream_consumer_group,
        args.topic,
    )
    print(json.dumps({"lag": result}, indent=2))
    return 0


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _replay(args: argparse.Namespace, settings: Settings) -> int:
    result = replay_range(
        settings,
        start=_parse_ts(args.from_ts),
        end=_parse_ts(args.to_ts),
        group=args.group,
        topic=args.topic,
        max_records=args.max_records,
        idle_timeout=args.idle_timeout,
    )
    print(json.dumps({"replay": result}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        settings = get_settings()
        if args.command == "stream":
            return _stream(args, settings)
        if args.command == "replay":
            return _replay(args, settings)
        return _lag(args, settings)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.exception("stream processor failed")
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
