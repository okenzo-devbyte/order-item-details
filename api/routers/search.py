from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from order_search.db import Tables
from order_search.search.engine import SearchEngine
from order_search.search.filters import Filters

from .. import audit, security
from ..db_helpers import client_ip, get_db, user_agent
from ..schemas import SearchRequest, SuggestRequest

router = APIRouter(prefix="/api/v1", tags=["search"])


def _filters(payload):
    if payload.filters is None:
        return None
    return Filters(**payload.filters.model_dump())


def _engine(request: Request) -> SearchEngine:
    db = get_db(request)
    return SearchEngine(db, Tables.from_schemas(db.schema_item, db.schema_sales))


@router.post("/search")
def search(
    payload: SearchRequest,
    request: Request,
    user=Depends(security.rate_limit),
):
    result = _engine(request).search(
        query=payload.q,
        mode=payload.mode,
        filters=_filters(payload),
        limit=payload.limit,
        cursor=payload.cursor,
    )
    audit.record(
        get_db(request),
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
    suggestions = _engine(request).suggest(payload.q, limit=payload.limit)
    audit.record(
        get_db(request),
        action="suggest",
        user_id=user["id"],
        query=payload.q,
        result_count=len(suggestions),
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return {"suggestions": suggestions}


@router.get("/customers/{customer_id}/history")
def customer_history(
    customer_id: int,
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    user=Depends(security.rate_limit),
):
    try:
        filters = Filters(date_from=date_from, date_to=date_to)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    history = _engine(request).customer_history(customer_id, filters)
    if not history:
        raise HTTPException(404, "customer not found")
    return history[0]


@router.get("/products/{product_id}/customers")
def product_customers(
    product_id: int,
    request: Request,
    user=Depends(security.rate_limit),
):
    results = _engine(request).product_customers(product_id)
    if not results:
        raise HTTPException(404, "product not found")
    return results[0]
