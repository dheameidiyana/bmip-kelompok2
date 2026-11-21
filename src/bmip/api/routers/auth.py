"""Identity endpoint used by the dashboard and catalog (W2-C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from bmip.api.deps import build_meta, get_actor, get_role
from bmip.api.models import WhoAmIOut

router = APIRouter(tags=["auth"])


@router.get("/auth/whoami", response_model=WhoAmIOut, summary="Caller identity and role")
def whoami(
    request: Request,
    actor: str = Depends(get_actor),
    role: str = Depends(get_role),
) -> WhoAmIOut:
    return WhoAmIOut(
        actor=actor,
        role=role,
        key_id=getattr(request.state, "key_id", None),
        meta=build_meta(request, source="serving", stale=False, count=1),
    )
