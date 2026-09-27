from __future__ import annotations

from typing import Any


def record(
    db,
    *,
    user_id: int | None = None,
    action: str,
    query: str | None = None,
    mode: str | None = None,
    result_count: int | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    db.run(
        f'INSERT INTO "{db.schema_app}"."audit_log"'
        " (user_id, action, query, mode, result_count, ip, user_agent)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (user_id, action, query, mode, result_count, ip, user_agent),
    )


def list_entries(
    db,
    *,
    limit: int = 100,
    before_id: int | None = None,
    user_id: int | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        clauses.append("user_id = %s")
        params.append(user_id)
    if action:
        clauses.append("action = %s")
        params.append(action)
    if before_id is not None:
        clauses.append("id < %s")
        params.append(before_id)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = db.all(
        f'SELECT * FROM "{db.schema_app}"."audit_log"'
        + where
        + " ORDER BY id DESC LIMIT %s",
        (*params, limit),
    )
    return [dict(row) for row in rows]