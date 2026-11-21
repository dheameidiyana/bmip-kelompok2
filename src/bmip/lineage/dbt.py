"""Derive lineage edges from the dbt manifest.

The repository uses dbt-duckdb for computation and PyIceberg for publication, so
the intermediate dbt relations are not lakehouse datasets. For the graph that
matters to governance we collapse each ``gold.mart_*`` model to its upstream
``source`` nodes (``silver.*`` / ``bronze.*``) and emit one edge per mart.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from bmip.lineage.emitter import LineageEmitter
from bmip.lineage.events import dataset_ref, error_facet, schema_facet
from bmip.lineage.hooks import current_run_id

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = ROOT / "dbt" / "target" / "manifest.json"


def _load(manifest_path: str | Path | None) -> dict[str, Any]:
    path = Path(manifest_path or DEFAULT_MANIFEST)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _upstream_sources(
    node_id: str,
    nodes: dict[str, Any],
    sources: dict[str, Any],
    seen: set[str],
) -> set[str]:
    found: set[str] = set()
    if node_id in seen:
        return found
    seen.add(node_id)
    node = nodes.get(node_id)
    if node is None:
        if node_id in sources:
            found.add(node_id)
        return found
    for parent in node.get("depends_on", {}).get("nodes", []) or []:
        found.update(_upstream_sources(parent, nodes, sources, seen))
    return found


def mart_edges(manifest_path: str | Path | None = None) -> list[dict[str, Any]]:
    manifest = _load(manifest_path)
    if not manifest:
        return []
    nodes: dict[str, Any] = manifest.get("nodes", {})
    sources: dict[str, Any] = manifest.get("sources", {})
    edges: list[dict[str, Any]] = []
    for _, node in sorted(nodes.items()):
        if node.get("resource_type") != "model":
            continue
        schema = str(node.get("schema") or "").lower()
        if schema != "gold":
            continue
        seen: set[str] = set()
        upstream = _upstream_sources(node.get("unique_id", ""), nodes, sources, seen)
        inputs = []
        for source_id in sorted(upstream):
            source = sources[source_id]
            inputs.append(
                dataset_ref(
                    str(source.get("schema") or "silver"),
                    str(source.get("name") or source.get("identifier")),
                )
            )
        columns = [
            {"name": name, **(value or {})}
            for name, value in (node.get("columns") or {}).items()
        ]
        outputs = [
            dataset_ref(
                "gold",
                str(node.get("name")),
                facets={"schema": schema_facet(columns)} if columns else None,
            )
        ]
        edges.append(
            {
                "model": str(node.get("name")),
                "inputs": inputs,
                "outputs": outputs,
                "columns": columns,
            }
        )
    return edges


def combined(manifest_path: str | Path | None = None) -> tuple[list[dict], list[dict]]:
    """Return unique input and output refs across every gold mart."""
    seen_in: dict[str, dict] = {}
    seen_out: dict[str, dict] = {}
    for edge in mart_edges(manifest_path):
        for item in edge["inputs"]:
            seen_in[f"{item['namespace']}/{item['name']}"] = item
        for item in edge["outputs"]:
            seen_out[f"{item['namespace']}/{item['name']}"] = item
    return list(seen_in.values()), list(seen_out.values())


@contextmanager
def dbt_lineage(
    job_name: str = "dbt_build",
    *,
    select: str | None = None,
    manifest_path: str | Path | None = None,
) -> Iterator[str]:
    """Emit START/COMPLETE/FAIL around a dbt invocation.

    The COMPLETE event re-reads the manifest, so the first run of a clean
    checkout still records the edges that were just written.
    """
    emitter = LineageEmitter.from_env("bmip_batch")
    run_id = current_run_id("dbt")
    inputs, outputs = combined(manifest_path)
    job_facets = {"dbt": {"select": select or "all"}}
    emitter.emit(
        "START",
        job_name,
        run_id=run_id,
        job_facets=job_facets,
    )
    try:
        yield run_id
    except Exception as exc:
        emitter.emit(
            "FAIL",
            job_name,
            inputs=inputs,
            outputs=outputs,
            run_id=run_id,
            run_facets={"errorMessage": error_facet(str(exc))},
            job_facets=job_facets,
        )
        raise
    else:
        for edge in mart_edges(manifest_path):
            emitter.emit(
                "COMPLETE",
                f"{job_name}.{edge['model']}",
                inputs=edge["inputs"],
                outputs=edge["outputs"],
                run_id=f"{run_id}:{edge['model']}",
                job_facets=job_facets,
            )
    finally:
        emitter.close()
