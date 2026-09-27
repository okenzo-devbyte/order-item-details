from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, Response

from . import users
from .db_helpers import get_app_db, get_settings

ACCESS = "access"
REFRESH = "refresh"
ALGORITHM = "HS256"
COOKIE_ACCESS = "access_token"
COOKIE_REFRESH = "refresh_token"
COOKIE_CSRF = "csrf_token"


class InvalidToken(Exception):
    """Raised when a token is missing, expired, malformed or revoked."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tokens(schema: str) -> str:
    return f'"{schema}"."refresh_tokens"'


def encode_token(
    secret: str,
    user_id: int,
    role: str,
    token_type: str,
    ttl: timedelta,
    jti: str | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(secret: str, token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise InvalidToken("wrong token type")
    return payload


def issue_session(db, secret, user, access_ttl, refresh_ttl) -> tuple[str, str]:
    access = encode_token(secret, user["id"], user["role"], ACCESS, access_ttl)
    jti = uuid.uuid4().hex
    refresh = encode_token(
        secret, user["id"], user["role"], REFRESH, refresh_ttl, jti=jti
    )
    db.run(
        f"INSERT INTO {_tokens(db.schema_app)}"
        " (id, user_id, issued_at, expires_at, last_used_at, revoked)"
        " VALUES (%s,%s,now(),now() + make_interval(secs => %s),now(),false)",
        (jti, user["id"], refresh_ttl.total_seconds()),
    )
    return access, refresh


def rotate_refresh(
    db, secret, token, access_ttl, refresh_ttl, idle_timeout
) -> tuple[str, str]:
    payload = decode_token(secret, token, REFRESH)
    jti = payload.get("jti")
    row = db.one(
        f"SELECT * FROM {_tokens(db.schema_app)} WHERE id = %s", (jti,)
    )
    if row is None:
        raise InvalidToken("refresh token unknown")
    claimed = db.one(
        f"UPDATE {_tokens(db.schema_app)} SET revoked = true"
        " WHERE id = %s AND revoked = false RETURNING id",
        (jti,),
    )
    if claimed is None:
        raise InvalidToken("refresh token revoked")
    if _now() - row["last_used_at"] > idle_timeout:
        raise InvalidToken("session idle timeout")
    user = users.get_by_id(db, int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise InvalidToken("user inactive")
    return issue_session(db, secret, user, access_ttl, refresh_ttl)


def revoke_refresh(db, secret, token: str | None) -> None:
    if not token:
        return
    try:
        payload = decode_token(secret, token, REFRESH)
    except InvalidToken:
        return
    jti = payload.get("jti")
    if jti:
        db.run(
            f"UPDATE {_tokens(db.schema_app)} SET revoked = true WHERE id = %s",
            (jti,),
        )


def revoke_all_for_user(db, user_id: int) -> None:
    db.run(
        f"UPDATE {_tokens(db.schema_app)} SET revoked = true WHERE user_id = %s",
        (user_id,),
    )


def set_auth_cookies(response: Response, settings, access: str, refresh: str) -> None:
    secure = settings.cookie_secure
    response.set_cookie(
        COOKIE_ACCESS,
        access,
        max_age=settings.access_ttl_minutes * 60,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        COOKIE_REFRESH,
        refresh,
        max_age=settings.refresh_ttl_days * 86400,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        COOKIE_CSRF,
        secrets.token_urlsafe(32),
        max_age=settings.refresh_ttl_days * 86400,
        httponly=False,
        secure=secure,
        samesite="strict",
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    for name in (COOKIE_ACCESS, COOKIE_REFRESH, COOKIE_CSRF):
        response.delete_cookie(name, path="/")


def _user_from_request(request: Request):
    settings = get_settings(request)
    db = get_app_db(request)
    token = request.cookies.get(COOKIE_ACCESS)
    if not token:
        raise HTTPException(401, "not authenticated")
    try:
        payload = decode_token(settings.secret_key, token, ACCESS)
    except InvalidToken:
        raise HTTPException(401, "invalid or expired token") from None
    user = users.get_by_id(db, int(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(401, "account disabled")
    return user


def require_staff(request: Request):
    return _user_from_request(request)


def require_admin(request: Request):
    user = _user_from_request(request)
    if user["role"] != "admin":
        raise HTTPException(403, "admin role required")
    return user


def require_csrf(request: Request) -> None:
    cookie = request.cookies.get(COOKIE_CSRF)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(403, "csrf token missing or invalid")


def rate_limit(request: Request, user=Depends(require_staff)):
    limiter = request.app.state.rate_limiter
    if not limiter.allow(f"user:{user['id']}"):
        raise HTTPException(429, "rate limit exceeded")
    return user


def login_rate_limit(request: Request) -> None:
    limiter = request.app.state.rate_limiter
    ip = request.client.host if request.client else "anonymous"
    if not limiter.allow(f"ip:{ip}"):
        raise HTTPException(429, "rate limit exceeded")
