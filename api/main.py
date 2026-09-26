from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import crypto
from .app_db import AppDB
from .config import Settings
from .ratelimit import RateLimiter
from .snapshot import SnapshotStore
from .users import bootstrap_admin

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
logger = logging.getLogger("order_search")
INSECURE_SECRET = "dev-insecure-secret-change-me"


def _assert_fts5_supported() -> None:
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        probe.execute("INSERT INTO t VALUES ('ทดสอบ')")
        probe.execute("SELECT rowid FROM t WHERE x MATCH 'ทดสอบ'").fetchall()
    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "this SQLite build lacks FTS5 trigram support"
        ) from exc
    finally:
        probe.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    if settings.cookie_secure and settings.secret_key == INSECURE_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the insecure default; set a strong random value"
        )
    _assert_fts5_supported()

    keyring = {settings.data_key_id: crypto.load_key(settings.data_key)}
    snapshot = SnapshotStore(keyring, settings.data_key_id)
    snapshot.load_file(settings.snapshot_file)
    app.state.snapshot = snapshot

    db = AppDB(settings.app_db_path)
    app.state.app_db = db
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    if bootstrap_admin(db, settings.admin_username, settings.admin_password):
        logger.info("bootstrap admin account created")
    try:
        yield
    finally:
        snapshot.close()
        db.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(
        title="Order Search",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings

    if settings.allowed_hosts and settings.allowed_hosts != "*":
        from starlette.middleware.trustedhost import TrustedHostMiddleware

        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=[
                host.strip()
                for host in settings.allowed_hosts.split(",")
                if host.strip()
            ],
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.middleware("http")
    async def csrf_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin is not None and request.url.hostname not in origin:
                return JSONResponse(
                    {"detail": "cross-origin request blocked"}, status_code=403
                )
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        snapshot = getattr(app.state, "snapshot", None)
        return {
            "status": "ok",
            "snapshot": snapshot is not None and snapshot.loaded,
        }

    from .routers import admin, auth, filters, search

    app.include_router(auth.router)
    app.include_router(search.router)
    app.include_router(filters.router)
    app.include_router(admin.router)

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
