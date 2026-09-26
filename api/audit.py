from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .app_db import AppDB


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(
    db: AppDB,
    *,
    action: str,
    user_id: int | None = None,
    query: str | None = None,
    mode: str | None = None,
    result_count: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.run(
        "INSERT INTO audit_log (user_id, action, query, mode, result_count, ip,"
        " user_agent, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (user_id, action, query, mode, result_count, ip, user_agent, _now()),
    )


def list_entries(
    db: AppDB,
    *,
    limit: int = 100,
    before_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if action:
        clauses.append("action = ?")
        params.append(action)
    if before_id is not None:
        clauses.append("id < ?")
        params.append(before_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.query_all(
        "SELECT * FROM audit_log" + where + " ORDER BY id DESC LIMIT ?",
        (*params, limit),
    )
    return [dict(row) for row in rows]
