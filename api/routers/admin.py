from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from .. import audit, security, users
from ..db_helpers import client_ip, get_app_db, get_settings, user_agent
from ..imports import build_snapshot_bytes
from ..schemas import RollbackRequest, UserCreateRequest, UserPatchRequest

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users")
def list_users(request: Request, _admin=Depends(security.require_admin)):
    rows = users.list_users(get_app_db(request))
    return {"users": [dict(row) for row in rows]}


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_app_db(request)
    try:
        user_id = users.create_user(
            db, payload.username, payload.password, payload.role
        )
    except sqlite3.IntegrityError:
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
    db = get_app_db(request)
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
def get_audit(request: Request, _admin=Depends(security.require_admin)):
    return {"entries": []}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


@router.post("/import")
async def import_workbook(
    request: Request,
    file: UploadFile = File(...),
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    settings = get_settings(request)
    db = get_app_db(request)
    snapshot = request.app.state.snapshot

    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "only .xlsx workbooks are accepted")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, "uploaded workbook is too large")

    versions_dir: Path = settings.versions_dir
    versions_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        suffix=".xlsx", dir=versions_dir, delete=False
    ) as handle:
        handle.write(data)
        temp_xlsx = Path(handle.name)

    try:
        plaintext, report = build_snapshot_bytes(temp_xlsx)
    finally:
        temp_xlsx.unlink(missing_ok=True)

    sealed = snapshot.seal_bytes(plaintext)
    digest = hashlib.sha256(sealed).hexdigest()
    version_path = versions_dir / f"{_timestamp()}_{digest[:8]}.enc"
    version_path.write_bytes(sealed)

    db.run("UPDATE import_versions SET is_current = 0")
    version_id = db.run(
        "INSERT INTO import_versions (path, sha256, row_count, product_count,"
        " customer_count, is_current, created_at, created_by)"
        " VALUES (?,?,?,?,?,1,?,?)",
        (
            str(version_path),
            digest,
            report.rows_imported,
            report.products,
            report.customers,
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            admin["id"],
        ),
    )
    snapshot.replace_with_bytes(plaintext)
    audit.record(
        db,
        action="import",
        user_id=admin["id"],
        query=str(version_id),
        result_count=report.rows_imported,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return {
        "version_id": version_id,
        "persistent": settings.persistent,
        "report": {
            "rows_read": report.rows_read,
            "rows_imported": report.rows_imported,
            "rows_skipped": report.rows_skipped,
            "products": report.products,
            "customers": report.customers,
            "barcodes": report.barcodes,
        },
    }


@router.get("/import/versions")
def list_versions(request: Request, _admin=Depends(security.require_admin)):
    settings = get_settings(request)
    rows = get_app_db(request).query_all(
        "SELECT id, path, sha256, row_count, product_count, customer_count,"
        " is_current, created_at, created_by FROM import_versions"
        " ORDER BY id DESC"
    )
    return {
        "persistent": settings.persistent,
        "versions": [dict(row) for row in rows],
    }


@router.post("/import/rollback")
def rollback(
    payload: RollbackRequest,
    request: Request,
    admin=Depends(security.require_admin),
    _csrf=Depends(security.require_csrf),
):
    db = get_app_db(request)
    snapshot = request.app.state.snapshot
    row = db.query_one(
        "SELECT * FROM import_versions WHERE id = ?", (payload.version_id,)
    )
    if row is None:
        raise HTTPException(404, "version not found")
    try:
        plaintext = snapshot.load_version_bytes(row["path"])
    except Exception:
        raise HTTPException(422, "version file missing or corrupt") from None
    snapshot.replace_with_bytes(plaintext)
    db.run("UPDATE import_versions SET is_current = 0")
    db.run("UPDATE import_versions SET is_current = 1 WHERE id = ?", (row["id"],))
    audit.record(
        db,
        action="rollback",
        user_id=admin["id"],
        query=str(row["id"]),
    )
    return {"ok": True, "version_id": row["id"]}
