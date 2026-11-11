"""Source adapters for Binance and Bluesky.

Every adapter returns contract-shaped dictionaries. Validation happens in the
batch pipeline so live, replay, and fixture inputs follow exactly the same path.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import time
import urllib.request
import zipfile
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import websockets

from bmip.common.logging import get_logger
from bmip.ingestion.hashing import payload_hash

log = get_logger(__name__)

BINANCE_VISION_BASE = "https://data.binance.vision"
BLUESKY_BASE = "https://api.bsky.app"
SOCIAL_REPLAY_TABLE = "iceberg://lakehouse/bronze.social_post_raw"


def now_utc() -> datetime:
    return datetime.now(UTC)


def epoch_to_datetime(value: int | float) -> datetime:
    number = int(value)
    if number > 10**14:
        return datetime.fromtimestamp(number / 1_000_000, tz=UTC)
    return datetime.fromtimestamp(number / 1_000, tz=UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def binance_ws_url(base_url: str, symbol: str) -> str:
    base = base_url.rstrip("/")
    stream = f"{symbol.lower()}@aggTrade"
    if base.endswith("/ws"):
        return f"{base}/{stream}"
    if "/stream" in base:
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}streams={stream}"
    return f"{base}/{stream}"


def parse_binance_ws(
    raw: dict[str, Any],
    symbol: str,
    source: str = "binance_ws",
    ingest_ts: datetime | None = None,
) -> dict[str, Any] | None:
    if raw.get("e") != "aggTrade":
        return None
    if raw.get("s") != symbol:
        return None
    ingest = ingest_ts or now_utc()
    event_ts = epoch_to_datetime(raw["T"])
    return {
        "symbol": raw["s"],
        "trade_id": int(raw["a"]),
        "event_ts": iso_z(event_ts),
        "price": float(raw["p"]),
        "qty": float(raw["q"]),
        "is_buyer_maker": bool(raw["m"]),
        "ingest_ts": iso_z(ingest),
        "source": source,
        "schema_version": "1.0",
        "payload_hash": payload_hash(raw),
        "_raw": raw,
    }


def parse_binance_vision_row(
    row: dict[str, Any],
    ingest_ts: datetime | None = None,
) -> dict[str, Any]:
    ingest = ingest_ts or now_utc()
    event_ts = epoch_to_datetime(row["transact_time"])

    def flag(value: Any) -> bool:
        return str(value).strip().lower() in {"true", "1", "t"}

    return {
        "symbol": "BTCUSDT",
        "trade_id": int(row["agg_trade_id"]),
        "event_ts": iso_z(event_ts),
        "price": float(row["price"]),
        "qty": float(row["quantity"]),
        "is_buyer_maker": flag(row["is_buyer_maker"]),
        "ingest_ts": iso_z(ingest),
        "source": "binance_vision",
        "schema_version": "1.0",
        "payload_hash": payload_hash(row),
        "_raw": row,
    }


def _bluesky_hashtags(record: dict[str, Any]) -> list[str]:
    tags = []
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            tag = feature.get("tag")
            if tag:
                tags.append(str(tag).strip().lstrip("#"))
    return [tag for tag in tags if tag][:20]


def map_bluesky_post(raw: dict[str, Any], ingest_ts: datetime | None = None) -> dict[str, Any]:
    record = raw.get("record") or {}
    author = raw.get("author") or {}
    created_at = record.get("createdAt") or raw.get("indexedAt")
    if not created_at:
        raise ValueError("post has no createdAt")
    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    langs = record.get("langs") or []
    event_date = created.astimezone(UTC).date().isoformat()
    return {
        "post_uri": raw["uri"],
        "author_did": author.get("did") or "",
        "author_handle": author.get("handle"),
        "created_at": iso_z(created),
        "lang": langs[0] if langs else None,
        "text": record.get("text") or "",
        "hashtags": _bluesky_hashtags(record),
        "like_count": int(raw.get("likeCount") or 0),
        "repost_count": int(raw.get("repostCount") or 0),
        "reply_count": int(raw.get("replyCount") or 0),
        "quote_count": int(raw.get("quoteCount") or 0),
        "source": "bluesky",
        "schema_version": "1.0",
        "raw_ref": f"{SOCIAL_REPLAY_TABLE}/event_date={event_date}",
        "payload_hash": payload_hash(raw),
        "_raw": raw,
    }


def iter_static_market(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            record = parse_binance_ws(raw, "BTCUSDT", source="binance_vision")
            if record is not None:
                yield record


def iter_static_social(path: Path) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return
    if text.startswith("["):
        posts = json.loads(text)
    else:
        posts = [json.loads(line) for line in text.splitlines() if line.strip()]
    for post in posts:
        if isinstance(post, dict) and "posts" in post:
            for item in post["posts"]:
                yield map_bluesky_post(item)
        else:
            yield map_bluesky_post(post)


def download_binance_vision_day(
    day: str,
    symbol: str,
    cache_dir: Path,
    base_url: str = BINANCE_VISION_BASE,
) -> Path:
    filename = f"{symbol}-aggTrades-{day}.zip"
    target = cache_dir / filename
    if target.exists() and target.stat().st_size > 0:
        return target
    cache_dir.mkdir(parents=True, exist_ok=True)
    url = f"{base_url}/data/spot/daily/aggTrades/{symbol}/{filename}"
    log.info("downloading Binance Vision day", extra={"ctx_url": url})
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read()
    target.write_bytes(data)
    return target


def iter_binance_vision_csv(
    path: Path,
    symbol: str,
    max_records: int | None = None,
    speed: float = 0.0,
) -> Iterator[dict[str, Any]]:
    columns = [
        "agg_trade_id",
        "price",
        "quantity",
        "first_trade_id",
        "last_trade_id",
        "transact_time",
        "is_buyer_maker",
        "is_best_match",
    ]
    count = 0
    with zipfile.ZipFile(path) as archive:
        name = next((item for item in archive.namelist() if item.endswith(".csv")), None)
        if name is None:
            raise ValueError(f"{path} contains no CSV file")
        with archive.open(name) as raw_handle:
            text = io.TextIOWrapper(raw_handle, encoding="utf-8")
            reader = csv.reader(text)
            first = next(reader, None)
            if first is None:
                return
            if first[0].strip().lower() == "agg_trade_id":
                rows: Iterable[list[str]] = reader
            else:
                rows = (first, *reader)
            for values in rows:
                if not values:
                    continue
                row = dict(zip(columns, values, strict=False))
                yield parse_binance_vision_row(row)
                count += 1
                if max_records is not None and count >= max_records:
                    return
                if speed > 0:
                    time.sleep(1 / speed)


async def _collect_binance_ws(
    url: str,
    symbol: str,
    max_records: int,
    idle_timeout: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    backoff = 1.0
    while len(records) < max_records:
        try:
            async with websockets.connect(url, open_timeout=10, ping_interval=20) as socket:
                backoff = 1.0
                while len(records) < max_records:
                    message = await asyncio.wait_for(socket.recv(), timeout=idle_timeout)
                    raw = json.loads(message)
                    record = parse_binance_ws(raw, symbol)
                    if record is not None:
                        records.append(record)
                        log.info(
                            "market trade received",
                            extra={"ctx_trade_id": record["trade_id"]},
                        )
            if len(records) >= max_records:
                break
        except (TimeoutError, OSError, websockets.WebSocketException) as exc:
            log.warning(
                "binance websocket reconnect",
                extra={"ctx_error": str(exc), "ctx_backoff": backoff},
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
    return records


def collect_binance_ws(
    base_url: str,
    symbol: str,
    max_records: int = 10,
    idle_timeout: float = 30.0,
) -> list[dict[str, Any]]:
    url = binance_ws_url(base_url, symbol)
    return asyncio.run(_collect_binance_ws(url, symbol, max_records, idle_timeout))


def _cache_page(cache_dir: Path, query: str, page: int, payload: dict[str, Any]) -> None:
    digest = hashlib.sha1(query.encode("utf-8")).hexdigest()[:12]
    target = cache_dir / digest / f"page-{page:03d}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def iter_bluesky_search(
    query: str,
    limit: int = 100,
    max_pages: int = 50,
    since: datetime | None = None,
    base_url: str = BLUESKY_BASE,
    cache_dir: Path | None = None,
    timeout: float = 30.0,
) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    until = now_utc()
    with httpx.Client(timeout=timeout) as client:
        for page in range(max_pages):
            params: dict[str, Any] = {"q": query, "limit": limit, "sort": "latest"}
            if cursor:
                params["cursor"] = cursor
            if since:
                params["since"] = iso_z(since)
            if until:
                params["until"] = iso_z(until)
            response = client.get(f"{base_url}/xrpc/app.bsky.feed.searchPosts", params=params)
            response.raise_for_status()
            body = response.json()
            if cache_dir is not None:
                _cache_page(cache_dir, query, page, body)
            posts = body.get("posts") or []
            if not posts:
                return
            for post in posts:
                try:
                    yield map_bluesky_post(post)
                except ValueError as exc:
                    log.warning("skipping malformed Bluesky post", extra={"ctx_error": str(exc)})
            cursor = body.get("cursor")
            if not cursor:
                return


def watermark_since(watermark: datetime | None, lookback_minutes: int = 5) -> datetime:
    if watermark is None:
        return now_utc() - timedelta(hours=1)
    return watermark - timedelta(minutes=lookback_minutes)
