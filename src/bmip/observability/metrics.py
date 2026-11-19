"""A tiny Prometheus registry for batch jobs.

The stream processor needs an HTTP server; a batch job only needs to leave a
value behind before it exits. Both write the same exposition format, so the
dashboards do not care which one produced a sample.

No third-party client is used on purpose: the format is a handful of lines and
adding a dependency to every container for it would be worse than the thirty
lines below.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass
class Sample:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    help: str = ""
    kind: str = "gauge"


class Registry:
    """Collects samples for one process or one batch run."""

    def __init__(self, service: str = "bmip") -> None:
        self.service = service
        self._samples: dict[tuple[str, tuple[tuple[str, str], ...]], Sample] = {}

    def set(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        *,
        help: str = "",
        kind: str = "gauge",
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        self._samples[key] = Sample(
            name=name,
            value=float(value),
            labels=dict(labels or {}),
            help=help or name,
            kind=kind,
        )

    def inc(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
        *,
        help: str = "",
        kind: str = "counter",
    ) -> None:
        key = (name, tuple(sorted((labels or {}).items())))
        existing = self._samples.get(key)
        current = existing.value if existing else 0.0
        self.set(name, current + value, labels, help=help, kind=kind)

    def get(self, name: str, labels: dict[str, str] | None = None) -> float:
        key = (name, tuple(sorted((labels or {}).items())))
        sample = self._samples.get(key)
        return sample.value if sample else 0.0

    def render(self) -> str:
        return render_samples(self._samples.values())

    def samples(self) -> list[Sample]:
        return list(self._samples.values())


def render_samples(samples: Any) -> str:
    """Render samples in the Prometheus text exposition format."""
    grouped: dict[str, list[Sample]] = {}
    for sample in samples:
        grouped.setdefault(sample.name, []).append(sample)

    lines: list[str] = []
    for name in sorted(grouped):
        rows = grouped[name]
        lines.append(f"# HELP {name} {rows[0].help}")
        lines.append(f"# TYPE {name} {rows[0].kind}")
        for row in rows:
            lines.append(f"{name}{_labels(row.labels)} {_value(row.value)}")
    return "\n".join(lines) + "\n" if lines else ""


def _labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    body = ",".join(
        f'{key}="{_escape(value)}"' for key, value in sorted(labels.items())
    )
    return "{" + body + "}"


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")


def push(
    registry: Registry,
    job: str,
    *,
    gateway: str | None = None,
    instance: str | None = None,
    timeout: float = 5.0,
) -> bool:
    """POST the registry to the Pushgateway; skip silently when unconfigured.

    A missing gateway is a normal state (tests, CI, a developer laptop), so it
    must never fail a pipeline run.
    """
    base = (gateway if gateway is not None else os.getenv("PUSHGATEWAY_URL", "")).strip()
    if not base:
        return False
    url = f"{base.rstrip('/')}/metrics/job/{urllib.parse.quote(job, safe='')}"
    if instance:
        url += f"/instance/{urllib.parse.quote(instance, safe='')}"
    request = urllib.request.Request(
        url,
        data=registry.render().encode("utf-8"),
        method="POST",
        headers={"Content-Type": CONTENT_TYPE},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


@contextmanager
def batch_run(
    job: str,
    *,
    gateway: str | None = None,
    instance: str | None = None,
) -> Iterator[Registry]:
    """Time one batch run, record success/failure, and push on the way out.

    ``bmip_last_success_timestamp_seconds`` is only refreshed on success; that
    is what the job-failure alert reads, so a failing job goes stale instead of
    quietly reporting a fresh timestamp.
    """
    registry = Registry(job)
    started = time.perf_counter()
    status = "ok"
    try:
        yield registry
    except Exception:
        status = "failed"
        raise
    finally:
        finished = time.time()
        registry.set(
            "bmip_batch_duration_seconds",
            time.perf_counter() - started,
            {"job": job, "status": status},
            help="Wall-clock duration of the last batch run.",
        )
        registry.set(
            "bmip_batch_last_run_timestamp_seconds",
            finished,
            {"job": job, "status": status},
            help="Unix timestamp when the batch run finished.",
        )
        if status == "ok":
            registry.set(
                "bmip_last_success_timestamp_seconds",
                finished,
                {"job": job},
                help="Unix timestamp of the last successful batch run.",
            )
        push(registry, job, gateway=gateway, instance=instance)
