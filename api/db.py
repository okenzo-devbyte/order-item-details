from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from order_search.db import Tables

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def split_statements(sql: str) -> list[str]:
    """Splits a migration file into single statements.

    psycopg's extended protocol refuses multiple statements in one execute, so
    migrations are fed one at a time. Semicolons inside a dollar-quoted body
    belong to the body, which is why this cannot be a plain `sql.split(";")`.
    """
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    while index < len(sql):
        if sql.startswith("$$", index):
            closing = sql.find("$$", index + 2)
            end = len(sql) if closing == -1 else closing + 2
            buffer.append(sql[index:end])
            index = end
            continue
        character = sql[index]
        buffer.append(character)
        if character == ";":
            statements.append("".join(buffer))
            buffer = []
        index += 1
    tail = "".join(buffer)
    if tail.strip():
        statements.append(tail)
    return [
        statement.strip().removesuffix(";").strip()
        for statement in statements
        if statement.strip()
    ]


def _schema_renames(
    schema_item: str, schema_sales: str, schema_app: str
) -> dict[str, str]:
    return {
        "app": f'"{schema_app}"',
        "item": f'"{schema_item}"',
        "sales": f'"{schema_sales}"',
    }


def _rename_schemas(sql: str, renames: dict[str, str]) -> str:
    """Rewrites the default schema names in a migration onto the configured ones.

    The migrations name their schemas bare, as `app.users` and `item.products`,
    so the match is on the bare word. A word boundary is required: `item` is a
    prefix of `item_remark` and of `order_items`, and renaming those would
    produce a migration that fails to run.

    This cannot tell SQL from a string literal, so a default name inside one is
    rewritten too. A new migration must not mention a default schema name in
    text.
    """
    for original, replacement in renames.items():
        pattern = rf"\b{re.escape(original)}\b"
        sql = re.sub(pattern, replacement.replace("\\", "\\\\"), sql)
    return sql


class Database:
    """Every database call the application makes.

    The pool is created once per process and shared. `one` and `all` return
    plain dicts so calling code keeps the `row["col"]` style it had with
    sqlite3.Row.

    The pool holds a single connection, so an import owns the whole service for
    the length of its COPY. That is deliberate: the admin path gets its own
    `Database` when the resumable import lands, so a long import cannot stall a
    search request. Nothing in the request path is written to, so the read pool
    and the import pool do not contend.
    """

    def __init__(self, dsn: str, schema_item: str, schema_sales: str, schema_app: str):
        self.pool = ConnectionPool(
            dsn,
            min_size=0,
            # Supabase runs PgBouncer in transaction mode, which multiplexes
            # many client connections onto one backend. One app-side connection
            # is the conservative side of that trade, not a typo.
            max_size=1,
            kwargs={
                "row_factory": dict_row,
                # Transaction mode can re-bind a named prepared statement to a
                # different backend, which turns a plan into a crash rather than
                # a slow query. No server-side prepare at all.
                "prepare_threshold": 0,
            },
            open=False,
        )
        self.pool.open()
        self.schema_item = schema_item
        self.schema_sales = schema_sales
        self.schema_app = schema_app
        self.tables = Tables.from_schemas(schema_item, schema_sales)

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                return cur.fetchone()

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                return list(cur.fetchall() or [])

    def run(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or None)
                return cur.rowcount

    def copy(self, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
        column_list = ", ".join(columns)
        statement = f"COPY {table} ({column_list}) FROM STDIN"
        written = 0
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                with cur.copy(statement) as copy:
                    for row in rows:
                        copy.write_row(tuple(row))
                        written += 1
        return written

    def execute_script(self, sql: str) -> None:
        with self.pool.connection() as conn:
            with conn.cursor() as cur:
                for statement in split_statements(sql):
                    cur.execute(statement)

    def migrate(self) -> list[str]:
        """Applies every migration file in name order and returns the names.

        The files are written against the default schema names, so each one is
        rewritten onto the configured names before it runs. That is what lets
        the test suite build `t_item`, `t_sales` and `t_app` without a second
        copy of the schema.
        """
        renames = _schema_renames(self.schema_item, self.schema_sales, self.schema_app)
        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            sql = _rename_schemas(path.read_text(encoding="utf-8"), renames)
            self.execute_script(sql)
            applied.append(path.name)
        return applied

    def close(self) -> None:
        self.pool.close()
