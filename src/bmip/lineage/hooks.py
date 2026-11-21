"""Reusable hooks for Prefect flows and the stream processor."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from bmip.lineage.emitter import LineageEmitter
from bmip.lineage.events import error_facet


def current_run_id(prefix: str = "run") -> str:
    configured = os.getenv("BMIP_RUN_ID")
    if configured:
        return configured
    try:
        from prefect.runtime import flow_run

        value = flow_run.id
        if value:
            return str(value)
    except Exception:  # noqa: BLE001 - running outside Prefect is normal
        pass
    return f"{prefix}-{uuid4().hex[:12]}"


@contextmanager
def lineage_run(
    job_name: str,
    *,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    namespace: str = "bmip_batch",
    run_id: str | None = None,
    facets: dict[str, Any] | None = None,
) -> Iterator[str]:
    """Emit START, then COMPLETE or FAIL around a unit of work.

    Any lineage problem is logged inside the emitter and never raised, so a
    missing Marquez cannot break an ingestion or transform run.
    """
    emitter = LineageEmitter.from_env(namespace)
    active_run = run_id or current_run_id(job_name.replace(" ", "-").lower())
    emitter.emit(
        "START",
        job_name,
        inputs=inputs,
        outputs=outputs,
        run_id=active_run,
        run_facets=facets,
    )
    try:
        yield active_run
    except Exception as exc:
        emitter.emit(
            "FAIL",
            job_name,
            inputs=inputs,
            outputs=outputs,
            run_id=active_run,
            run_facets={**(facets or {}), "errorMessage": error_facet(str(exc))},
        )
        raise
    else:
        emitter.emit(
            "COMPLETE",
            job_name,
            inputs=inputs,
            outputs=outputs,
            run_id=active_run,
            run_facets=facets,
        )
    finally:
        emitter.close()


def emit_edges(
    job_name: str,
    edges: list[tuple[list[dict[str, Any]], list[dict[str, Any]], str]],
    *,
    namespace: str = "bmip_batch",
    run_id: str | None = None,
) -> int:
    """Emit one COMPLETE per precise input -> output edge.

    Used by flows that fan in/out over several datasets, so the catalogue does
    not show a misleading all-to-all graph.
    """
    emitter = LineageEmitter.from_env(namespace)
    try:
        for inputs, outputs, suffix in edges:
            emitter.emit(
                "COMPLETE",
                f"{job_name}.{suffix}",
                inputs=inputs,
                outputs=outputs,
                run_id=f"{run_id}:{suffix}" if run_id else None,
            )
    finally:
        emitter.close()
    return len(edges)
