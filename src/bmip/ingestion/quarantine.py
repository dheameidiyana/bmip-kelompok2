"""Write rejected source records to the quarantine bucket."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config

from bmip.common.config import Settings
from bmip.common.logging import get_logger
from bmip.ingestion.hashing import canonical_json

log = get_logger(__name__)


def write_quarantine(
    settings: Settings,
    source: str,
    rejected: list[dict[str, Any]],
) -> str | None:
    if not rejected:
        return None
    access_key, secret_key = settings.minio_credentials("ingest")
    client = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=settings.minio_region,
        config=Config(s3={"addressing_style": "path"}),
    )
    now = datetime.now(UTC)
    key = (
        f"{source}/ingest_date={now.date().isoformat()}"
        f"/reason=schema_violation/part-{uuid.uuid4().hex}.jsonl"
    )
    body = "\n".join(canonical_json(item["raw"]) for item in rejected) + "\n"
    client.put_object(
        Bucket="quarantine",
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/x-ndjson",
    )
    log.warning(
        "records quarantined",
        extra={"ctx_source": source, "ctx_count": len(rejected), "ctx_key": key},
    )
    return key
