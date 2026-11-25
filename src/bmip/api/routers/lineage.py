"""Lineage lookup from the local edge cache (W2-C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from bmip.api.deps import build_meta, get_repository
from bmip.api.errors import ApiProblem
from bmip.api.models import LineageOut
from bmip.serving.repository import ServingRepository

router = APIRouter(tags=["lineage"])


@router.get(
    "/lineage/{dataset_id}",
    response_model=LineageOut,
    summary="Upstream and downstream datasets for one catalogue entry",
)
def lineage(
    request: Request,
    dataset_id: str,
    repository: ServingRepository = Depends(get_repository),
) -> LineageOut:
    if repository.dataset(dataset_id) is None:
        raise ApiProblem(
            404,
            "dataset-not-found",
            "Dataset not found",
            f"No dataset with id {dataset_id!r} is registered.",
        )
    edges = repository.lineage(dataset_id)
    return LineageOut(
        dataset_id=dataset_id,
        upstream=edges["upstream"],
        downstream=edges["downstream"],
        source="ops.lineage_edges",
        meta=build_meta(
            request,
            source="serving",
            stale=False,
            count=len(edges["upstream"]) + len(edges["downstream"]),
        ),
    )
