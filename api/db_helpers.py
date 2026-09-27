from __future__ import annotations

from fastapi import Request

from .config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_app_db(request: Request):
    return request.app.state.db


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")