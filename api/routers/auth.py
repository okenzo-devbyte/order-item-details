from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import audit, security
from ..db_helpers import client_ip, get_db, get_settings, user_agent
from ..schemas import LoginRequest
from ..users import authenticate

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    _limit=Depends(security.login_rate_limit),
):
    settings = get_settings(request)
    db = get_db(request)
    user = authenticate(db, payload.username, payload.password)
    if user is None:
        audit.record(
            db,
            action="login_failed",
            query=payload.username,
            ip=client_ip(request),
            user_agent=user_agent(request),
        )
        raise HTTPException(401, "invalid credentials")
    access, refresh = security.issue_session(
        db,
        settings.secret_key,
        user,
        timedelta(minutes=settings.access_ttl_minutes),
        timedelta(days=settings.refresh_ttl_days),
    )
    security.set_auth_cookies(response, settings, access, refresh)
    audit.record(
        db,
        action="login",
        user_id=user["id"],
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    settings = get_settings(request)
    db = get_db(request)
    security.revoke_refresh(
        db, settings.secret_key, request.cookies.get(security.COOKIE_REFRESH)
    )
    security.clear_auth_cookies(response)
    return {"ok": True}


@router.post("/refresh")
def refresh(request: Request, response: Response):
    settings = get_settings(request)
    db = get_db(request)
    token = request.cookies.get(security.COOKIE_REFRESH)
    if not token:
        raise HTTPException(401, "no refresh token")
    try:
        access, renewed = security.rotate_refresh(
            db,
            settings.secret_key,
            token,
            timedelta(minutes=settings.access_ttl_minutes),
            timedelta(days=settings.refresh_ttl_days),
            timedelta(minutes=settings.idle_timeout_minutes),
        )
    except security.InvalidToken:
        security.clear_auth_cookies(response)
        raise HTTPException(401, "session expired") from None
    security.set_auth_cookies(response, settings, access, renewed)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(security.require_staff)):
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
    }
