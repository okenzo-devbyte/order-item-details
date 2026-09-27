from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Database
from .db_helpers import get_db
from .ratelimit import RateLimiter
from .users import bootstrap_admin

WEB_DIR = Path(__file__).resolve().parents[1] / "web"
logger = logging.getLogger("order_search")
INSECURE_SECRET = "dev-insecure-secret-change-me"


def _assert_trgm_supported(database) -> None:
    try:
        database.one("SELECT similarity('abc', 'abd')")
    except psycopg.Error as exc:
        raise RuntimeError("this database lacks the pg_trgm extension") from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    if settings.cookie_secure and settings.secret_key == INSECURE_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the insecure default; set a strong random value"
        )
    database = getattr(app.state, "db", None)
    owns_database = database is None
    if owns_database:
        database = Database(
            settings.database_url,
            settings.schema_item,
            settings.schema_sales,
            settings.schema_app,
        )
        app.state.db = database
    _assert_trgm_supported(database)
    bootstrap_admin(database, settings.admin_username, settings.admin_password)
    app.state.rate_limiter = RateLimiter(
        database, settings.rate_limit_per_minute
    )
    if settings.admin_password == "change-me-now":
        logger.warning(
            "bootstrap admin uses the default password; change it before use"
        )
    try:
        yield
    finally:
        if owns_database:
            database.close()


def create_app(
    settings: Settings | None = None, database=None
) -> FastAPI:
    if database is None and settings is not None and not isinstance(
        settings, Settings
    ):
        database = settings
        settings = None
    settings = settings or Settings()
    app = FastAPI(
        title="Order Search",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    if database is not None:
        app.state.db = database

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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'"
        )
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
            if origin is not None:
                origin_host = urlsplit(origin).hostname
                if origin_host is not None and origin_host != request.url.hostname:
                    return JSONResponse(
                        {"detail": "cross-origin request blocked"},
                        status_code=403,
                    )
        return await call_next(request)

    @app.get("/healthz")
    def healthz(request: Request):
        db = get_db(request)
        row = db.one(
            f"SELECT product_count, customer_count, order_count"
            f' FROM "{db.schema_app}"."data_versions" WHERE is_current'
        )
        if row is None:
            return JSONResponse(
                {"status": "no data", "products": 0}, status_code=503
            )
        return {
            "status": "ok",
            "products": row["product_count"],
            "customers": row["customer_count"],
            "orders": row["order_count"],
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
