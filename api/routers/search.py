from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from order_search.search.filters import Filters

from .. import audit, security
from ..db_helpers import client_ip, get_app_db, user_agent
from ..schemas import SearchRequest, SuggestRequest

router = APIRouter(prefix="/api/v1", tags=["search"])


def _filters(payload):
    if payload.filters is None:
        return None
    return Filters(**payload.filters.model_dump())


@router.post("/search")
def search(
    payload: SearchRequest,
    request: Request,
    user=Depends(security.rate_limit),
):
    result = request.app.state.snapshot.search(
        query=payload.q,
        mode=payload.mode,
        filters=_filters(payload),
        limit=payload.limit,
        cursor=payload.cursor,
    )
    audit.record(
        get_app_db(request),
        action="search",
        user_id=user["id"],
        query=payload.q,
        mode=result["mode"],
        result_count=len(result["products"]) + len(result["customers"]),
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return result


@router.post("/suggest")
def suggest(
    payload: SuggestRequest,
    request: Request,
    user=Depends(security.rate_limit),
):
    suggestions = request.app.state.snapshot.suggest(
        payload.q, limit=payload.limit
    )
    return {"suggestions": suggestions}
