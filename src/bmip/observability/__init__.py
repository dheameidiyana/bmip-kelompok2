"""Prometheus metrics and batch push helpers (W2-B).

The stream processor keeps its own tiny registry (``bmip.transform.metrics``)
because it must expose HTTP while running. Everything that runs as a batch job
uses this module instead: it renders the same text format and pushes the result
to the Pushgateway, so a job that exits still leaves a value behind.
"""

from bmip.observability.metrics import (
    Registry,
    batch_run,
    push,
    render_samples,
)

__all__ = ["Registry", "batch_run", "push", "render_samples"]
