from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from .. import audit, security, users
from ..audit import list_entries
from ..db_helpers import client_ip, get_db, user_agent
from ..schemas import UserCreateRequest, UserPatchRequest

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users")
def list_users(request: Request, _admin=Depends(security.require_admin)):
    rows = users.list_users(get_db(request))
    return {"users": [dict(row) for row in rows]}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_db(request)
    try:
        user_id = users.create_user(
            db, payload.username, payload.password, payload.role
        )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "username already exists") from None
    audit.record(
        db,
        action="user_create",
        user_id=admin["id"],
        query=payload.username,
        mode=payload.role,
    )
    row = users.get_by_id(db, user_id)
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": row["is_active"],
    }


@router.patch("/users/{user_id}")
def patch_user(
    user_id: int,
    payload: UserPatchRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_db(request)
    updated = users.update_user(
        db,
        user_id,
        password=payload.password,
        role=payload.role,
        is_active=payload.is_active,
    )
    if not updated:
        raise HTTPException(404, "user not found")
    if payload.password is not None:
        security.revoke_all_for_user(db, user_id)
    audit.record(
        db,
        action="user_update",
        user_id=admin["id"],
        query=str(user_id),
        mode=payload.role,
    )
    row = users.get_by_id(db, user_id)
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": row["is_active"],
    }


@router.get("/audit")
def get_audit(
    request: Request,
    limit: int = 100,
    before_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
    _admin=Depends(security.require_admin),
):
    limit = max(1, min(limit, 500))
    entries = list_entries(
        get_db(request),
        limit=limit,
        before_id=before_id,
        user_id=user_id,
        action=action,
    )
    return {"entries": entries}


@router.get("/versions")
def versions(request: Request, _admin=Depends(security.require_admin)):
    db = get_db(request)
    return {
        "versions": db.all(
            f"SELECT id, version, source_filename, row_count, product_count,"
            f" customer_count, order_count, is_current, created_at"
            f' FROM "{db.schema_app}"."data_versions" ORDER BY id DESC'
        )
    }
