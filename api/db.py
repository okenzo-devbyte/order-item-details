from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from order_search.db import Tables, app_table

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

# The ledger is also declared in 002_app.sql, so the app schema reads as one
# piece. This copy exists because migrate() has to consult the ledger before
# any migration file has run, including on a database with no schemas at all.
LEDGER_DDL = """\
CREATE SCHEMA IF NOT EXISTS "app";
CREATE TABLE IF NOT EXISTS "app"."schema_migrations" (
    name       text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""


COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _is_code(statement: str) -> bool:
    return bool(COMMENT.sub("", statement).strip(" \t\r\n;"))


def split_statements(sql: str) -> list[str]:
    """Splits a migration file into single statements.

    psycopg's extended protocol refuses multiple statements in one execute, so
    migrations are fed one at a time. A semicolon only ends a statement when it
    stands on its own, which is why this scans instead of splitting: a semicolon
    inside a dollar-quoted body, a string literal or a comment belongs to its
    text, and splitting on it would send a fragment to the server.

    Two forms are still not tracked, and both are absent from the migrations: a
    tagged dollar quote such as `$body$ ... $body$`, which this reads as code,
    and a `$$` inside a string literal, which it reads as the start of a body.
    """
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        pair = sql[index : index + 2]
        if pair == "$$":
            closing = sql.find("$$", index + 2)
            end = length if closing == -1 else closing + 2
        elif pair == "--":
            newline = sql.find("\n", index)
            end = length if newline == -1 else newline
        elif pair == "/*":
            closing = sql.find("*/", index + 2)
            end = length if closing == -1 else closing + 2
        elif sql[index] == "'":
            end = index + 1
            while end < length:
                if sql[end] != "'":
                    end += 1
                    continue
                if sql[end + 1 : end + 2] == "'":
                    end += 2
                    continue
                end += 1
                break
        else:
            character = sql[index]
            buffer.append(character)
            if character == ";":
                statements.append("".join(buffer))
                buffer = []
            index += 1
            continue
        buffer.append(sql[index:end])
        index = end
    tail = "".join(buffer)
    if tail.strip():
        statements.append(tail)
    stripped = [
        statement.strip().removesuffix(";").strip() for statement in statements
    ]
    return [statement for statement in stripped if statement and _is_code(statement)]


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

    @contextmanager
    def _connection(self, conn: Connection | None) -> Iterator[Connection]:
        """The caller's connection, or a pooled one this call owns.

        A pooled connection commits when its block ends, which is why a caller
        that supplies its own connection is responsible for the commit.
        """
        if conn is not None:
            yield conn
            return
        with self.pool.connection() as pooled:
            yield pooled

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Runs several calls as one transaction.

        `pool.connection()` commits as soon as it is returned to the pool, so
        each call is a transaction of its own by default. Activating an imported
        dataset is not one statement but has to be all of nothing: repoint the
        views, clear the old current flag, set the new one. Committed separately
        a crash in the middle leaves the views serving a version that no row
        calls current, so the import path composes its writes through here.
        """
        with self.pool.connection() as conn:
            with conn.transaction():
                yield conn

    def one(
        self, sql: str, params: Sequence[Any] = (), conn: Connection | None = None
    ) -> dict[str, Any] | None:
        with self._connection(conn) as active:
            with active.cursor() as cur:
                cur.execute(sql, params or None)
                return cur.fetchone()

    def all(
        self, sql: str, params: Sequence[Any] = (), conn: Connection | None = None
    ) -> list[dict[str, Any]]:
        with self._connection(conn) as active:
            with active.cursor() as cur:
                cur.execute(sql, params or None)
                return list(cur.fetchall() or [])

    def run(
        self, sql: str, params: Sequence[Any] = (), conn: Connection | None = None
    ) -> int:
        with self._connection(conn) as active:
            with active.cursor() as cur:
                cur.execute(sql, params or None)
                return cur.rowcount

    def copy(
        self,
        table: str,
        columns: Sequence[str],
        rows: Iterable[Sequence[Any]],
        conn: Connection | None = None,
    ) -> int:
        column_list = ", ".join(columns)
        statement = f"COPY {table} ({column_list}) FROM STDIN"
        written = 0
        with self._connection(conn) as active:
            with active.cursor() as cur:
                with cur.copy(statement) as copy:
                    for row in rows:
                        copy.write_row(tuple(row))
                        written += 1
        return written

    def execute_script(self, sql: str, conn: Connection | None = None) -> None:
        with self._connection(conn) as active:
            with active.cursor() as cur:
                for statement in split_statements(sql):
                    cur.execute(statement)

    def _migration_files(self) -> list[Path]:
        """The migration files, or a loud failure explaining their absence.

        `glob` on a directory that is not there yields nothing, so without this
        the service would boot and every query would fail on a missing relation,
        which points at the schema rather than at the packaging.
        """
        if not MIGRATIONS_DIR.is_dir():
            raise FileNotFoundError(f"the migrations directory is missing: {MIGRATIONS_DIR}")
        paths = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not paths:
            raise FileNotFoundError(f"no migration file to apply in {MIGRATIONS_DIR}")
        return paths

    def migrate(self) -> list[str]:
        """Applies every migration the ledger does not already record.

        Returns the names this call applied, in order. A name already in
        `app.schema_migrations` is skipped, so the return value is the work this
        boot did and not the work the schema already holds.

        The files are written against the default schema names, so each one is
        rewritten onto the configured names before it runs. That is what lets
        the test suite build `t_item`, `t_sales` and `t_app` without a second
        copy of the schema.

        A file and its ledger row are written in one transaction, so a crash
        leaves the file unapplied rather than applied and unrecorded.
        """
        renames = _schema_renames(self.schema_item, self.schema_sales, self.schema_app)
        paths = self._migration_files()
        ledger = app_table(self.schema_app, "schema_migrations")
        with self._connection(None) as conn:
            self.execute_script(_rename_schemas(LEDGER_DDL, renames), conn=conn)
            recorded = {
                row["name"] for row in self.all(f"SELECT name FROM {ledger}", conn=conn)
            }
        applied: list[str] = []
        for path in paths:
            if path.name in recorded:
                continue
            sql = _rename_schemas(path.read_text(encoding="utf-8"), renames)
            with self.transaction() as conn:
                self.execute_script(sql, conn=conn)
                self.run(f"INSERT INTO {ledger} (name) VALUES (%s)", (path.name,), conn=conn)
            applied.append(path.name)
        return applied

    def close(self) -> None:
        self.pool.close()
