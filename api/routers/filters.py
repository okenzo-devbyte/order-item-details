from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import security

router = APIRouter(prefix="/api/v1", tags=["filters"])


@router.get("/filters")
def filters(request: Request, user=Depends(security.rate_limit)):
    return request.app.state.snapshot.facets()
