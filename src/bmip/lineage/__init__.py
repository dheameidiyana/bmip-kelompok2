"""OpenLineage emission for BMIP jobs (W2-C).

The module deliberately depends only on ``httpx`` and the standard library: the
platform already ships both, and the dbt/Prefect/stream hooks must never make a
job fail because the lineage backend is unavailable. Every emitter writes a
JSONL spool copy first, then posts to Marquez when ``OPENLINEAGE_URL`` is set.
"""

from __future__ import annotations

from bmip.lineage.dbt import mart_edges
from bmip.lineage.emitter import LineageEmitter, cache_edges, registry_id
from bmip.lineage.events import build_run_event, dataset_ref
from bmip.lineage.hooks import current_run_id, emit_edges, lineage_run

__all__ = [
    "LineageEmitter",
    "build_run_event",
    "cache_edges",
    "current_run_id",
    "dataset_ref",
    "emit_edges",
    "lineage_run",
    "mart_edges",
    "registry_id",
]
