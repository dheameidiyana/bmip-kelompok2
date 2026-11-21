"""HTTP emitter for OpenLineage events with a mandatory file spool.

Marquez is optional during development: the platform risk table allows a file
fallback when the governance stack is unavailable. The spool is written even
when the HTTP post succeeds, so ``evidence/lineage/`` always contains the raw
event that was sent.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from bmip.common.logging import get_logger
from bmip.lineage.events import build_run_event

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SPOOL = ROOT / "evidence" / "lineage" / "spool"


class LineageEmitter:
    def __init__(
        self,
        url: str | None = None,
        *,
        namespace: str = "bmip_batch",
        spool_dir: str | Path | None = None,
        timeout: float = 3.0,
        enabled: bool | None = None,
    ) -> None:
        configured = os.getenv("OPENLINEAGE_URL", "") if url is None else url
        self.url = configured.rstrip("/")
        self.namespace = namespace
        self.spool_dir = Path(spool_dir or os.getenv("OPENLINEAGE_SPOOL_DIR") or DEFAULT_SPOOL)
        if enabled is None:
            enabled = os.getenv("OPENLINEAGE_DISABLED", "").lower() not in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.enabled = enabled
        self.timeout = timeout
        self._client: httpx.Client | None = None

    @classmethod
    def from_env(cls, namespace: str = "bmip_batch") -> LineageEmitter:
        return cls(namespace=namespace)

    @property
    def endpoint(self) -> str:
        if not self.url:
            return ""
        if self.url.endswith("/api/v1/lineage"):
            return self.url
        return f"{self.url}/api/v1/lineage"

    def emit(
        self,
        event_type: str,
        job_name: str,
        *,
        inputs: list[dict[str, Any]] | None = None,
        outputs: list[dict[str, Any]] | None = None,
        run_id: str | None = None,
        run_facets: dict[str, Any] | None = None,
        job_facets: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        event = build_run_event(
            event_type=event_type,
            job_name=job_name,
            run_id=run_id,
            inputs=inputs,
            outputs=outputs,
            namespace=self.namespace,
            run_facets=run_facets,
            job_facets=job_facets,
        )
        self._spool(event)
        self._cache_edges(event)
        self._post(event)
        return event

    def _spool(self, event: dict[str, Any]) -> None:
        try:
            self.spool_dir.mkdir(parents=True, exist_ok=True)
            day = datetime.now(UTC).strftime("%Y%m%d")
            path = self.spool_dir / f"events_{day}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        except OSError as exc:  # noqa: BLE001 - evidence write must not fail a job
            log.warning("lineage spool write failed", extra={"ctx_error": str(exc)})

    def _cache_edges(self, event: dict[str, Any]) -> None:
        try:
            cache_edges(event)
        except Exception as exc:  # noqa: BLE001 - the cache is optional
            log.warning("lineage edge cache failed", extra={"ctx_error": str(exc)})

    def _post(self, event: dict[str, Any]) -> None:
        if not self.endpoint:
            return
        try:
            if self._client is None:
                self._client = httpx.Client(timeout=self.timeout)
            response = self._client.post(self.endpoint, json=event)
            if response.status_code >= 400:
                log.warning(
                    "lineage post rejected",
                    extra={
                        "ctx_status": response.status_code,
                        "ctx_job": event["job"]["name"],
                    },
                )
        except httpx.HTTPError as exc:
            log.warning(
                "lineage post failed",
                extra={"ctx_job": event["job"]["name"], "ctx_error": str(exc)},
            )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> LineageEmitter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def registry_id(namespace: str, name: str) -> str:
    """Map an OpenLineage dataset to the catalogue id used by the API."""
    if namespace.startswith("s3://lakehouse/warehouse"):
        layer, separator, table = name.partition(".db/")
        if separator:
            return f"{layer}.{table}"
    if namespace.startswith("postgres://serving"):
        return f"serving.{name}"
    return name.replace("/", ".")


def cache_edges(event: dict[str, Any]) -> int:
    """Upsert the input -> output pairs of one completed event."""
    if event.get("eventType") != "COMPLETE":
        return 0
    dsn = os.getenv("POSTGRES_CORE_DSN")
    if not dsn:
        return 0
    inputs = event.get("inputs") or []
    outputs = event.get("outputs") or []
    if not inputs or not outputs:
        return 0
    import psycopg

    job = event.get("job") or {}
    if str(job.get("name")) in {
        "dbt_build",
        "publish-serving",
        "transform-gold",
        "transform-silver",
    }:
        return 0
    run = event.get("run") or {}
    pairs = [
        (
            registry_id(str(out.get("namespace")), str(out.get("name"))),
            registry_id(str(inp.get("namespace")), str(inp.get("name"))),
            job.get("namespace"),
            job.get("name"),
            run.get("runId"),
            event.get("eventType"),
        )
        for out in outputs
        for inp in inputs
    ]
    with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO ops.lineage_edges
                    (dataset_id, upstream_id, job_namespace, job_name, run_id,
                     event_type, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (dataset_id, upstream_id) DO UPDATE SET
                    job_namespace = EXCLUDED.job_namespace,
                    job_name = EXCLUDED.job_name,
                    run_id = EXCLUDED.run_id,
                    event_type = EXCLUDED.event_type,
                    updated_at = now()
                """,
                pairs,
            )
    return len(pairs)
