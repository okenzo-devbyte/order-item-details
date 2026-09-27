# Postgres Storage and Search Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sealed SQLite snapshot with Supabase Postgres while keeping search results byte-for-byte identical.

**Architecture:** `src/order_search.search` stops importing `sqlite3` and instead talks to a `Reader` protocol with `one()` and `all()`. `api.db.Database` implements that protocol over a psycopg3 pool and also serves the writable `app` tables. Each import writes into fresh `{table}_v{n}` tables; five views point at the current version, so activating a new dataset is a single `CREATE OR REPLACE VIEW`.

**Tech Stack:** Postgres 15 (Supabase), `psycopg[binary]` 3.2, `pg_trgm`, FastAPI, pytest.

**Design:** `docs/superpowers/specs/2026-09-27-supabase-vercel-redesign-design.md`

---

## Scope of this plan

Covers: configuration, migrations, the database pool, the `Reader` boundary,
the search port, users/audit/security, the routers, the database rate limiter,
a one-shot loader script, and deleting the SQLite snapshot path.

Deliberately **not** covered, and planned separately: the resumable chunked web
import, Supabase Storage, rollback endpoints, and Vercel deployment. The
loader in Task 13 loads a whole workbook in one process, which is enough to get
the system running on Supabase.

## Prerequisites you need before starting

- A Supabase project in region `sin1`
- Its **Transaction pooler** connection string (port 6543), because the direct
  connection is IPv6-only and this code runs on IPv4 networks

Put the connection string in a `.env` file at the repository root. The file is
already gitignored, and `pydantic-settings` already reads it, so the scripts
and the test suite both pick it up without anyone pasting a password into a
chat window or a command line.

```
DATABASE_URL=postgresql://postgres.PROJECT:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres?sslmode=require
```

Create it in Notepad if you prefer, not in PowerShell, so the URL never lands
in your shell history:

```powershell
notepad .env
```

The test suite connects to the same project under the schemas `t_item`,
`t_sales` and `t_app`, so it needs no second credential. It never touches
`item`, `sales` or `app`.

## Ground truth that must keep passing

These are measured facts about the sample workbook. If any of them changes, the
port is wrong.

| query | expected |
|-------|----------|
| `สุรชัย` | mode `customer`, 1 customer, `order_count` 65 |
| `8850250001234` | mode `product`, 1 product, `น้ำดื่มสิงห์ 600 มล. x 12` |
| `น้ำ` | 4 products |
| import report | products 15, customers 20, barcodes 127, orders 1000, rows_skipped 0 |
| `น้ำ` suggest | 4 suggestions |

## Conventions in this codebase

- `from __future__ import annotations` at the top of every module
- Tests live in `tests/`, import from `conftest` for paths
- `tests/conftest.py` puts both the repo root and `src/` on `sys.path`
- Run tests with `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q`
- Run Python with `PYTHONIOENCODING=utf-8` set, because output is Thai
- No comments in code unless a comment explains a non-obvious constraint
- One commit per task, message in the imperative mood

## SQL dialect rules for this port

The old code is SQLite. Postgres differs in ways that matter here.

| SQLite | Postgres | note |
|--------|----------|------|
| `?` | `%s` | every placeholder changes |
| `sqlite3.Row` | `psycopg.rows.dict_row` | same `row["col"]` access |
| `GROUP_CONCAT(DISTINCT x)` | `string_agg(DISTINCT x, ',' ORDER BY x)` | ORDER BY keeps it deterministic |
| `INTEGER 0/1` | `boolean` | returns Python `bool` |
| ISO text timestamps | `timestamptz` | returns `datetime`, not `str` |
| `products_fts MATCH` | `name_norm LIKE '%q%'` | substring, not word match |
| `executescript` | one statement per `execute` | see the splitter in Task 2 |

---

### Task 1: Dependencies and configuration

**Files:**
- Modify: `requirements.txt`
- Modify: `api/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_database_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@pooler:6543/postgres")
    monkeypatch.setenv("DB_SCHEMA_ITEM", "t_item")
    monkeypatch.setenv("DB_SCHEMA_SALES", "t_sales")
    monkeypatch.setenv("DB_SCHEMA_APP", "t_app")
    settings = Settings()
    assert settings.database_url.startswith("postgresql://")
    assert settings.schema_item == "t_item"
    assert settings.schema_sales == "t_sales"
    assert settings.schema_app == "t_app"


def test_snapshot_settings_are_gone():
    fields = Settings.model_fields
    assert "data_key" not in fields
    assert "snapshot_path" not in fields
    assert "disk_path" not in fields
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_config.py -o addopts="" -q`
Expected: FAIL, `Settings` has no attribute `database_url`

- [ ] **Step 3: Swap the dependencies**

In `requirements.txt`, remove the `cryptography>=42` line and add:

```
psycopg[binary]>=3.2
```

Then install:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

- [ ] **Step 4: Rewrite the settings**

Replace the snapshot fields in `api/config.py` with:

```python
    database_url: str = ""
    schema_item: str = "item"
    schema_sales: str = "sales"
    schema_app: str = "app"
```

Delete `data_key`, `data_key_id`, `snapshot_path`, `disk_path`, the
`persistent` property, the `data_dir` property, `app_db_path`, `versions_dir`
and `snapshot_file`. Keep `secret_key`, `admin_username`, `admin_password`,
`cookie_secure`, `allowed_hosts`, the three TTL settings,
`idle_timeout_minutes`, `rate_limit_per_minute` and `max_upload_bytes`.
`Path` and `tempfile` imports are no longer needed, so drop them.

- [ ] **Step 5: Run the config tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_config.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add requirements.txt api/config.py tests/test_config.py
git commit -m "feat(config): replace snapshot settings with a Postgres connection"
```

---

### Task 2: Migrations, the pool, and the Reader boundary

**Files:**
- Create: `src/order_search/db.py`
- Create: `api/db.py`
- Create: `migrations/001_extensions.sql`
- Create: `migrations/002_app.sql`
- Create: `migrations/003_item.sql`
- Create: `migrations/004_sales.sql`
- Create: `migrations/005_views.sql`
- Create: `migrations/006_grants.sql`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: Write the failing test for the statement splitter**

`tests/test_migrations.py`:

```python
from api.db import split_statements


def test_splits_on_semicolons_outside_dollar_quotes():
    sql = "CREATE TABLE a (id int);\nSELECT 1;\n"
    assert split_statements(sql) == ["CREATE TABLE a (id int)", "SELECT 1"]


def test_keeps_a_dollar_quoted_body_intact():
    sql = (
        "CREATE FUNCTION f() RETURNS int AS $$\n"
        "  SELECT 1;\n"
        "$$ LANGUAGE sql;\n"
        "SELECT 2;\n"
    )
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "SELECT 1;" in statements[0]
    assert statements[1] == "SELECT 2"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_migrations.py -o addopts="" -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'api.db'`

- [ ] **Step 3: Write the migration files**

`migrations/001_extensions.sql`

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

`migrations/002_app.sql`

```sql
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    role          text NOT NULL CHECK (role IN ('staff','admin')),
    totp_secret   text,
    is_active     boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.refresh_tokens (
    id           text PRIMARY KEY,
    user_id      bigint NOT NULL REFERENCES app.users(id) ON DELETE CASCADE,
    issued_at    timestamptz NOT NULL,
    expires_at   timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL,
    revoked      boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_refresh_user ON app.refresh_tokens(user_id);

CREATE TABLE IF NOT EXISTS app.data_versions (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version        integer NOT NULL,
    source_filename text,
    row_count      integer,
    product_count  integer,
    customer_count integer,
    order_count    integer,
    barcode_count  integer,
    is_current     boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now(),
    created_by     bigint REFERENCES app.users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_current
    ON app.data_versions(is_current) WHERE is_current;

CREATE TABLE IF NOT EXISTS app.audit_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      bigint,
    action       text NOT NULL,
    query        text,
    mode         text,
    result_count integer,
    ip           text,
    user_agent   text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created ON app.audit_log(created_at);

CREATE TABLE IF NOT EXISTS app.rate_buckets (
    key        text NOT NULL,
    window     timestamptz NOT NULL,
    hits       integer NOT NULL DEFAULT 0,
    PRIMARY KEY (key, window)
);
```

The `app.stg_*` staging tables are deliberately absent. They exist only for the
resumable import, which the next plan adds as its own migration.

`migrations/003_item.sql`

```sql
CREATE SCHEMA IF NOT EXISTS item;

CREATE TABLE IF NOT EXISTS item.products_v1 (
    id              bigint PRIMARY KEY,
    name            text NOT NULL,
    name_norm       text NOT NULL,
    name_fold_light text NOT NULL,
    name_fold_heavy text NOT NULL,
    dept            integer,
    class_code      integer,
    subclass_code   integer,
    pack_size       integer,
    unit            text
);
CREATE INDEX IF NOT EXISTS idx_products_v1_name_norm
    ON item.products_v1 (name_norm text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_trgm
    ON item.products_v1 USING gin (name_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_fold_trgm
    ON item.products_v1 USING gin (name_fold_light gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_dept ON item.products_v1 (dept);
CREATE INDEX IF NOT EXISTS idx_products_v1_class ON item.products_v1 (class_code);
CREATE INDEX IF NOT EXISTS idx_products_v1_subclass ON item.products_v1 (subclass_code);

CREATE TABLE IF NOT EXISTS item.product_barcodes_v1 (
    product_id bigint NOT NULL,
    barcode    text NOT NULL,
    PRIMARY KEY (product_id, barcode)
);
CREATE INDEX IF NOT EXISTS idx_barcodes_v1_barcode
    ON item.product_barcodes_v1 (barcode);
```

`migrations/004_sales.sql`

```sql
CREATE SCHEMA IF NOT EXISTS sales;

CREATE TABLE IF NOT EXISTS sales.customers_v1 (
    id              bigint PRIMARY KEY,
    name            text NOT NULL,
    name_norm       text NOT NULL,
    name_fold_light text NOT NULL,
    name_fold_heavy text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_v1_norm
    ON sales.customers_v1 (name_norm);
CREATE INDEX IF NOT EXISTS idx_customers_v1_trgm
    ON sales.customers_v1 USING gin (name_norm gin_trgm_ops);

CREATE TABLE IF NOT EXISTS sales.orders_v1 (
    id          bigint PRIMARY KEY,
    order_no    text,
    store_code  text,
    customer_id bigint NOT NULL,
    order_type  text,
    date_from   date,
    date_to     date,
    item_remark text,
    vip_remark  text,
    vip_group   text
);
CREATE INDEX IF NOT EXISTS idx_orders_v1_customer ON sales.orders_v1 (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_v1_store    ON sales.orders_v1 (store_code);
CREATE INDEX IF NOT EXISTS idx_orders_v1_type     ON sales.orders_v1 (order_type);
CREATE INDEX IF NOT EXISTS idx_orders_v1_vip      ON sales.orders_v1 (vip_group);
CREATE INDEX IF NOT EXISTS idx_orders_v1_from     ON sales.orders_v1 (date_from);
CREATE INDEX IF NOT EXISTS idx_orders_v1_to       ON sales.orders_v1 (date_to);

CREATE TABLE IF NOT EXISTS sales.order_items_v1 (
    order_id   bigint NOT NULL,
    product_id bigint NOT NULL,
    qty        numeric,
    price      numeric,
    PRIMARY KEY (order_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_order_items_v1_product
    ON sales.order_items_v1 (product_id);
```

`migrations/005_views.sql`

```sql
CREATE OR REPLACE VIEW item.products AS
    SELECT id, name, name_norm, name_fold_light, name_fold_heavy,
           dept, class_code, subclass_code, pack_size, unit
    FROM item.products_v1;

CREATE OR REPLACE VIEW item.product_barcodes AS
    SELECT product_id, barcode FROM item.product_barcodes_v1;

CREATE OR REPLACE VIEW sales.customers AS
    SELECT id, name, name_norm, name_fold_light, name_fold_heavy
    FROM sales.customers_v1;

CREATE OR REPLACE VIEW sales.orders AS
    SELECT id, order_no, store_code, customer_id, order_type,
           date_from, date_to, item_remark, vip_remark, vip_group
    FROM sales.orders_v1;

CREATE OR REPLACE VIEW sales.order_items AS
    SELECT order_id, product_id, qty, price FROM sales.order_items_v1;
```

`migrations/006_grants.sql`

```sql
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON SCHEMA item FROM anon;
        REVOKE ALL ON SCHEMA sales FROM anon;
        REVOKE ALL ON SCHEMA app FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON SCHEMA item FROM authenticated;
        REVOKE ALL ON SCHEMA sales FROM authenticated;
        REVOKE ALL ON SCHEMA app FROM authenticated;
    END IF;
END $$;
```

The roles `anon` and `authenticated` exist on Supabase but not on a plain local
Postgres, so the grants are guarded rather than assumed.

- [ ] **Step 4: Write the Reader boundary**

`src/order_search/db.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class Reader(Protocol):
    """The only database surface the search core is allowed to use.

    It exists so `order_search` never imports psycopg and the search logic can
    be exercised against any Postgres, including a test schema.
    """

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        ...

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class Tables:
    """Schema-qualified relation names, resolved once per process.

    Every query in the search core interpolates these instead of writing bare
    table names, because the schemas are configurable so tests can run against
    `t_item`, `t_sales` and `t_app` without touching production data.
    """

    products: str
    product_barcodes: str
    customers: str
    orders: str
    order_items: str

    @classmethod
    def from_schemas(cls, item: str, sales: str) -> "Tables":
        return cls(
            products=f'"{item}"."products"',
            product_barcodes=f'"{item}"."product_barcodes"',
            customers=f'"{sales}"."customers"',
            orders=f'"{sales}"."orders"',
            order_items=f'"{sales}"."order_items"',
        )


def app_table(schema: str, name: str) -> str:
    return f'"{schema}"."{name}"'
```

- [ ] **Step 5: Write the pool**

`api/db.py`

```python
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def split_statements(sql: str) -> list[str]:
    """Splits a migration file into single statements.

    psycopg's extended protocol refuses multiple statements in one execute, so
    migrations are fed one at a time. Semicolons inside a dollar-quoted body
    belong to the body, which is why this cannot be a plain `sql.split(";")`.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_body = False
    for line in sql.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("$$"):
            in_body = not in_body
        buffer.append(line)
        if not in_body and stripped.endswith(";"):
            statements.append("".join(buffer).strip().rstrip(";").strip())
            buffer = []
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


class Database:
    """Every database call the application makes.

    The pool is created once per process and shared. `one` and `all` return
    plain dicts so calling code keeps the `row["col"]` style it had with
    sqlite3.Row.
    """

    def __init__(self, dsn: str, schema_item: str, schema_sales: str, schema_app: str):
        self.pool = psycopg.ConnectionPool(
            dsn,
            min_size=0,
            max_size=1,
            kwargs={"row_factory": dict_row, "prepare_threshold": 0},
            open=False,
        )
        self.pool.open()
        self.schema_item = schema_item
        self.schema_sales = schema_sales
        self.schema_app = schema_app

    @property
    def tables(self):
        from order_search.db import Tables

        return Tables.from_schemas(self.schema_item, self.schema_sales)

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

    def close(self) -> None:
        self.pool.close()
```

- [ ] **Step 6: Write the migration runner**

Append to `api/db.py`:

```python
    def migrate(self) -> list[str]:
        """Applies every migration file in name order and returns the names.

        The files are written against the default schema names, so each one is
        rewritten onto the configured names before it runs. That is what lets
        the test suite build `t_item`, `t_sales` and `t_app` without a second
        copy of the schema.
        """
        renames = {
            '"app"': f'"{self.schema_app}"',
            '"item"': f'"{self.schema_item}"',
            '"sales"': f'"{self.schema_sales}"',
        }
        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            sql = path.read_text(encoding="utf-8")
            for original, replacement in renames.items():
                sql = sql.replace(original, replacement)
            self.execute_script(sql)
            applied.append(path.name)
        return applied
```

- [ ] **Step 7: Run the splitter tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_migrations.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 8: Commit**

```powershell
git add src/order_search/db.py api/db.py migrations tests/test_migrations.py
git commit -m "feat(db): add the Postgres pool, migrations and the Reader boundary"
```

---

### Task 3: A test fixture that runs against a real database

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_fixture_health.py`

- [ ] **Step 1: Write the failing test**

`tests/test_fixture_health.py`

```python
def test_the_test_schemas_exist(client_db: Database):
    app = client_db.schema_app
    item = client_db.schema_item
    sales = client_db.schema_sales
    assert client_db.one(f'SELECT count(*) AS n FROM "{app}"."users"')["n"] == 0
    assert client_db.one(f'SELECT count(*) AS n FROM "{item}"."products"')["n"] == 0
    assert client_db.one(f'SELECT count(*) AS n FROM "{sales}"."orders"')["n"] == 0


def test_production_schemas_are_untouched(client_db: Database):
    rows = client_db.all(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
        (["t_item", "t_sales", "t_app"],),
    )
    assert len(rows) == 3
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_fixture_health.py -o addopts="" -q`
Expected: FAIL, fixture `client_db` not found

- [ ] **Step 3: Add the fixtures**

Append to `tests/conftest.py`:

```python
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEST_SCHEMAS = ("t_item", "t_sales", "t_app")


def _test_dsn() -> str:
    """The test suite shares one credential with the application.

    It connects to the same project but under the `t_` schemas, so there is no
    second secret to manage. `.env` is read here because `pydantic-settings`
    reads it for `Settings`, and a password should never have to be passed on
    a command line to run the tests.
    """
    explicit = os.environ.get("TEST_DATABASE_URL", "")
    if explicit:
        return explicit
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


TEST_URL = _test_dsn()


def pytest_collection_modifyitems(config, items):
    if TEST_URL:
        return
    skip = pytest.mark.skip(reason="no DATABASE_URL in the environment or .env")
    for item in items:
        if "client_db" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def client_db():
    from api.db import Database

    database = Database(TEST_URL, *TEST_SCHEMAS)
    for schema in TEST_SCHEMAS:
        database.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
    database.migrate()
    yield database
    for schema in TEST_SCHEMAS:
        database.execute_script(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
    database.close()
```

The fixture calls `database.migrate()`, the same code path production uses, so
a migration that works in the test schemas works in the real ones.

- [ ] **Step 4: Run it to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_fixture_health.py -o addopts="" -q`
Expected: PASS. Without the environment variable it skips, and the skip is
itself correct behaviour.

- [ ] **Step 5: Commit**

```powershell
git add tests/conftest.py tests/test_fixture_health.py
git commit -m "test: run the suite against isolated Postgres schemas"
```

---

### Task 4: Extract the row transformation, delete the SQLite builder

**Files:**
- Create: `src/order_search/ingest/transform.py`
- Modify: `src/order_search/ingest/build.py`
- Delete: `src/order_search/ingest/schema.sql`
- Delete: `src/order_search/ingest/schema_path.py`
- Delete: `scripts/import_excel.py`
- Test: `tests/test_transform.py`

- [ ] **Step 1: Write the failing test**

`tests/test_transform.py`

```python
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.transform import transform
from conftest import DATA_FILE


def test_transform_assigns_dense_ids_in_first_seen_order():
    rows = read_order_rows(DATA_FILE)
    data = transform(rows[0])
    assert data.report.products == 15
    assert data.report.customers == 20
    assert [row[0] for row in data.products] == list(range(1, 16))
    assert [row[0] for row in data.customers] == list(range(1, 21))
    assert len(data.orders) == 1000
    assert len(data.order_items) == 1000
    assert len(data.barcodes) == 127


def test_transform_normalises_every_text_column():
    data = transform(read_order_rows(DATA_FILE)[0])
    first = data.products[0]
    assert first[1] == first[2] or first[2].startswith(first[1][:2])
    assert " " not in first[2]
    assert data.report.missing_pack_size_products == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_transform.py -o addopts="" -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'order_search.ingest.transform'`

- [ ] **Step 3: Write the transform**

`src/order_search/ingest/transform.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..textnorm import fold_heavy, fold_light, norm, parse_pack_size
from .validate import ImportReport, validate_rows


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class TransformedData:
    products: list[tuple] = field(default_factory=list)
    customers: list[tuple] = field(default_factory=list)
    orders: list[tuple] = field(default_factory=list)
    order_items: list[tuple] = field(default_factory=list)
    barcodes: list[tuple] = field(default_factory=list)
    report: ImportReport = field(default_factory=ImportReport)


def transform(rows: list[dict[str, Any]]) -> TransformedData:
    """Turns raw workbook rows into five insert-ready batches.

    Ids are assigned here, densely, in first-seen order, so the SQLite and
    Postgres backends agree on every id without either of them owning id logic.
    """
    usable, report = validate_rows(rows)

    product_ids: dict[str, int] = {}
    product_rows: list[tuple] = []
    for row in usable:
        name = str(row["Product Name"]).strip()
        if name in product_ids:
            continue
        product_ids[name] = len(product_ids) + 1
        product_rows.append(
            (
                product_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
                row.get("Dept"),
                row.get("Class"),
                row.get("Subclass"),
                parse_pack_size(name),
                None,
            )
        )

    customer_ids: dict[str, int] = {}
    customer_rows: list[tuple] = []
    for row in usable:
        name = str(row["Customer Name"]).strip()
        if name in customer_ids:
            continue
        customer_ids[name] = len(customer_ids) + 1
        customer_rows.append(
            (
                customer_ids[name],
                name,
                norm(name),
                fold_light(name),
                fold_heavy(name),
            )
        )

    order_rows: list[tuple] = []
    item_rows: list[tuple] = []
    for order_id, row in enumerate(usable, start=1):
        product_id = product_ids[str(row["Product Name"]).strip()]
        customer_id = customer_ids[str(row["Customer Name"]).strip()]
        order_rows.append(
            (
                order_id,
                _text(row.get("NO.")),
                _text(row.get("Store Code")),
                customer_id,
                _text(row.get("Order Type")),
                _iso(row.get("date_from")),
                _iso(row.get("date_to")),
                _text(row.get("Item Remark")),
                _text(row.get("VIP Customer Remarks")),
                _text(row.get("VIP Customer Groups")),
            )
        )
        item_rows.append((order_id, product_id, row.get("qty"), row.get("price")))

    barcode_pairs = _barcode_pairs(usable)

    report.products = len(product_ids)
    report.customers = len(customer_ids)
    report.orders = len(order_rows)
    report.barcodes = len(barcode_pairs)
    report.missing_pack_size_products = sum(1 for row in product_rows if row[8] is None)

    return TransformedData(
        products=product_rows,
        customers=customer_rows,
        orders=order_rows,
        order_items=item_rows,
        barcodes=barcode_pairs,
        report=report,
    )


def _barcode_pairs(usable: list[dict[str, Any]]) -> list[tuple[int, str]]:
    """Distinct (product_id, barcode) pairs, sorted.

    A barcode may appear on many rows of the same product, so the pairs are
    deduplicated. It may also legitimately appear on two different products, so
    the set is keyed on the pair and never on the barcode alone.
    """
    product_ids: dict[str, int] = {}
    for row in usable:
        name = str(row["Product Name"]).strip()
        if name not in product_ids:
            product_ids[name] = len(product_ids) + 1
    pairs: set[tuple[int, str]] = set()
    for row in usable:
        product_id = product_ids[str(row["Product Name"]).strip()]
        for barcode in row.get("Bar_Code") or []:
            pairs.add((product_id, barcode))
    return sorted(pairs)
```

- [ ] **Step 4: Run the transform tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_transform.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 5: Point build.py at the transform and delete the SQLite schema**

Replace the body of `build.py` with a thin `build_database` that calls
`transform` and then executes the SQLite inserts, so the existing SQLite tests
keep passing while Task 13 loads the same data into Postgres. If any test
imports `apply_schema` or `build_database` with a connection, keep both
functions; only the row construction moves.

Then delete `src/order_search/ingest/schema.sql`,
`src/order_search/ingest/schema_path.py` and `scripts/import_excel.py` **only
after** Step 6 passes.

- [ ] **Step 6: Run the whole suite**

Run: `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q`
Expected: every previously passing test still passes, except the ones this plan
deletes on purpose.

- [ ] **Step 7: Commit**

```powershell
git add src/order_search/ingest
git commit -m "refactor(ingest): extract the row transformation from the SQLite writer"
```

---

### Task 5: Port detect.py and filters.py

**Files:**
- Modify: `src/order_search/search/detect.py`
- Modify: `src/order_search/search/filters.py`
- Test: `tests/test_search_detect_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search_detect_pg.py`

```python
import pytest

from order_search.db import Tables
from order_search.search.detect import BOTH, CUSTOMER, NONE, PRODUCT, detect
from order_search.search.filters import Filters, order_filter_sql


class FakeReader:
    def __init__(self, tables: Tables):
        self.tables = tables

    def one(self, sql, params=()):
        if "customers" in sql:
            return {"id": 7}
        return None

    def all(self, sql, params=()):
        if "products" in sql:
            return [{"id": 3}, {"id": 4}]
        return []


@pytest.fixture
def reader():
    return FakeReader(Tables.from_schemas("t_item", "t_sales"))


def test_an_exact_customer_name_that_also_prefixes_products_is_both(reader):
    found = detect("กาแฟ", reader, reader.tables)
    assert found.kind == BOTH
    assert found.customer_id == 7
    assert found.product_ids == (3, 4)


def test_an_exact_customer_name_alone_is_a_customer(reader):
    reader.one = lambda sql, params=(): (
        {"id": 7} if "customers" in sql else None
    )
    reader.all = lambda sql, params=(): []
    assert detect("สุรชัย", reader, reader.tables).kind == CUSTOMER


def test_empty_query_is_none(reader):
    assert detect("   ", reader, reader.tables).kind == NONE


def test_a_three_character_query_is_product_text(reader):
    reader.one = lambda sql, params=(): None
    assert detect("น้ำดื่ม", reader, reader.tables).kind == PRODUCT


def test_filter_sql_uses_percent_placeholders():
    where, params = order_filter_sql(Filters(store_code=("101", "102")))
    assert where == "o.store_code IN (%s,%s)"
    assert params == ["101", "102"]


def test_date_filters_still_test_for_overlap():
    where, params = order_filter_sql(Filters(date_from="2026-01-01", date_to="2026-02-01"))
    assert where == "(o.date_from <= %s AND o.date_to >= %s AND o.date_from IS NOT NULL)"
    assert params == ["2026-02-01", "2026-01-01"]


def test_a_non_iso_date_is_rejected_loudly():
    with pytest.raises(ValueError):
        Filters(date_from="26-Sep-2026")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_detect_pg.py -o addopts="" -q`
Expected: FAIL, `detect()` rejects the third argument

- [ ] **Step 3: Port filters.py**

In `src/order_search/search/filters.py`, change `_in_clause` to:

```python
def _in_clause(column: str, values: tuple) -> tuple[str, list]:
    placeholders = ",".join("%s" for _ in values)
    return f"{column} IN ({placeholders})", list(values)
```

Nothing else changes: the column aliases, the OR-within-group and AND-across
groups semantics, the overlap date test and the `IS NOT NULL` guard are
identical in Postgres.

- [ ] **Step 4: Port detect.py**

Change the signature and the two queries:

```python
def detect(query: str, reader: Reader, tables: Tables) -> Detection:
    text = str(query or "").strip()
    normalized = norm(text)

    if not normalized:
        return Detection(NONE, "")

    if is_barcode_like(text):
        return Detection(BARCODE, normalized)

    exact_customer = reader.one(
        f"SELECT id FROM {tables.customers} WHERE name_norm = %s ORDER BY id LIMIT 1",
        (normalized,),
    )
    if exact_customer is not None:
        prefixed_products = reader.all(
            f"SELECT id FROM {tables.products} WHERE name_norm LIKE %s ESCAPE '\\'"
            " ORDER BY id",
            (_escape_like(normalized) + "%",),
        )
        product_ids = tuple(row["id"] for row in prefixed_products)
        kind = BOTH if product_ids else CUSTOMER
        return Detection(kind, normalized, exact_customer["id"], product_ids)

    if len(normalized) < MIN_TRIGRAM:
        return Detection(PRODUCT, normalized, too_short=True)

    return Detection(PRODUCT, normalized)
```

Update the imports at the top to `from ..db import Reader, Tables` and delete
`import sqlite3`. The docstring's mention of FTS is still accurate for the
engine, so keep the text but replace "FTS" wording with "trigram" where it
describes this function.

- [ ] **Step 5: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_detect_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 6: Commit**

```powershell
git add src/order_search/search/detect.py src/order_search/search/filters.py tests/test_search_detect_pg.py
git commit -m "feat(search): query Postgres from detect and filters"
```

---

### Task 6: Port fuzzy.py

**Files:**
- Modify: `src/order_search/search/fuzzy.py`
- Test: `tests/test_search_fuzzy_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search_fuzzy_pg.py`

```python
from order_search.db import Tables
from order_search.search.fuzzy import best_customers, best_products


class RowsReader:
    def __init__(self, rows):
        self.rows = rows

    def one(self, sql, params=()):
        return None

    def all(self, sql, params=()):
        return self.rows


def test_best_customers_returns_ids_scores_and_names():
    reader = RowsReader(
        [
            {"id": 1, "name_norm": "สมชายใจดี", "name_fold_light": "สมชายใจดี"},
            {"id": 2, "name_norm": "สุรชัยหนู", "name_fold_light": "สุรชัยหนู"},
        ]
    )
    matches = best_customers("สุรชัย", reader, Tables.from_schemas("t_item", "t_sales"))
    assert matches[0][0] == 2
    assert matches[0][1] == "สุรชัยหนู"
    assert matches[0][2] >= 70


def test_best_products_confirms_against_the_base_form():
    reader = RowsReader(
        [
            {"id": 1, "name_norm": "น้ำดื่มสิงห์600มลx12", "name_fold_heavy": "นาดมสงห600มลx12"},
            {"id": 2, "name_norm": "ขนมปัง", "name_fold_heavy": "ขนมปง"},
        ]
    )
    matches = best_products("น้ำดื่มสิงห์", reader, Tables.from_schemas("t_item", "t_sales"))
    assert [m[0] for m in matches] == [1]


def test_a_query_matching_nothing_returns_empty():
    reader = RowsReader([{"id": 1, "name_norm": "กาแฟ", "name_fold_heavy": "กาเฟ"}])
    assert best_products("zzzzzz", reader, Tables.from_schemas("t_item", "t_sales")) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_fuzzy_pg.py -o addopts="" -q`
Expected: FAIL, `best_customers()` takes 2 positional arguments but 3 were given

- [ ] **Step 3: Port the two functions**

```python
def best_customers(
    query: str,
    reader: Reader,
    tables: Tables,
    limit: int = 5,
    score_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    normalized = norm(query)
    if not normalized:
        return []
    rows = reader.all(
        f"SELECT id, name_norm, name_fold_light FROM {tables.customers} ORDER BY id"
    )
    if not rows:
        return []

    keys = [row["name_fold_light"] for row in rows]
    key_to_id = {row["name_fold_light"]: row["id"] for row in rows}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    matches = process.extract(
        normalized, keys, scorer=SCORER, score_cutoff=score_cutoff, limit=limit
    )
    out: list[tuple[int, str, float]] = []
    for value, score, _index in matches:
        customer_id = key_to_id.get(value)
        if customer_id is not None:
            out.append((customer_id, id_to_norm[customer_id], float(score)))
    return out


def best_products(
    query: str,
    reader: Reader,
    tables: Tables,
    limit: int = 5,
    stage1_cutoff: int = STAGE1_CUTOFF,
    final_cutoff: int = FINAL_CUTOFF,
) -> list[tuple[int, str, float]]:
    normalized = norm(query)
    if not normalized:
        return []
    rows = reader.all(
        f"SELECT id, name_norm, name_fold_heavy FROM {tables.products} ORDER BY id"
    )
    if not rows:
        return []

    heavy_keys = [row["name_fold_heavy"] for row in rows]
    index_to_id = {index: row["id"] for index, row in enumerate(rows)}
    id_to_norm = {row["id"]: row["name_norm"] for row in rows}

    widened = process.extract(
        normalized, heavy_keys, scorer=SCORER,
        score_cutoff=stage1_cutoff, limit=STAGE1_POOL,
    )

    confirmed: list[tuple[int, str, float]] = []
    for _value, _score, index in widened:
        product_id = index_to_id.get(index)
        if product_id is None:
            continue
        name_norm = id_to_norm[product_id]
        confirm = SCORER(normalized, name_norm)
        if confirm >= final_cutoff:
            confirmed.append((product_id, name_norm, float(confirm)))

    confirmed.sort(key=lambda item: (-item[2], item[0]))
    return confirmed[:limit]
```

Replace `import sqlite3` with `from ..db import Reader, Tables`. Keep every
comment: the cutoffs are measured, and the WRatio note is load-bearing.

- [ ] **Step 4: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_fuzzy_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/search/fuzzy.py tests/test_search_fuzzy_pg.py
git commit -m "feat(search): rank fuzzy matches through the Reader"
```

---

### Task 7: Port engine.py

**Files:**
- Modify: `src/order_search/search/engine.py`
- Test: `tests/test_search_engine_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_search_engine_pg.py` covers the pure-shape changes with a fake
reader, so it runs without a database:

```python
from order_search.db import Tables
from order_search.search.engine import SearchEngine


class RecordingReader:
    def __init__(self, one=None, all_rows=None):
        self._one = one
        self._all = all_rows or []
        self.seen = []

    def one(self, sql, params=()):
        self.seen.append(sql)
        return self._one

    def all(self, sql, params=()):
        self.seen.append(sql)
        return self._all


def make(reader):
    return SearchEngine(reader, Tables.from_schemas("t_item", "t_sales"))


def test_the_engine_no_longer_mentions_fts():
    reader = RecordingReader(one=None, all_rows=[])
    make(reader).search("น้ำดื่มสิงห์ 600 มล. x 12")
    assert not any("MATCH" in sql for sql in reader.seen)


def test_a_short_query_falls_back_to_a_prefix_scan():
    reader = RecordingReader(one=None, all_rows=[])
    make(reader).search("น้ำ")
    assert any("LIKE %s" in sql and "ESCAPE" in sql for sql in reader.seen)


def test_cursor_survives_a_round_trip():
    from order_search.search.engine import _decode_cursor, _encode_cursor

    assert _decode_cursor(_encode_cursor(40)) == 40
    assert _decode_cursor("not-a-cursor") == 0
    assert _decode_cursor(None) == 0


def test_an_empty_query_returns_an_empty_payload():
    payload = make(RecordingReader()).search("   ")
    assert payload["mode"] == "none"
    assert payload["customers"] == []
    assert payload["products"] == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_engine_pg.py -o addopts="" -q`
Expected: FAIL, `SearchEngine()` takes 1 positional argument but 2 were given

- [ ] **Step 3: Change the constructor and the two lookups**

```python
class SearchEngine:
    def __init__(self, reader: Reader, tables: Tables) -> None:
        self.reader = reader
        self.tables = tables
```

Replace every `self.connection.execute(sql, params).fetchall()` with
`self.reader.all(sql, params)` and every `.fetchone()` with
`self.reader.one(sql, params)`. Then rewrite the three lookups that named real
tables:

```python
    def _product_ids_by_barcode(self, barcode: str) -> list[int]:
        if not barcode:
            return []
        rows = self.reader.all(
            f"SELECT DISTINCT product_id FROM {self.tables.product_barcodes}"
            " WHERE barcode = %s ORDER BY product_id",
            (barcode,),
        )
        return [row["product_id"] for row in rows]

    def _product_ids_by_prefix(self, normalized: str) -> list[int]:
        rows = self.reader.all(
            f"SELECT id FROM {self.tables.products}"
            " WHERE name_norm LIKE %s ESCAPE '\\' ORDER BY name_norm",
            (_escape_like(normalized) + "%",),
        )
        return [row["id"] for row in rows]
```

- [ ] **Step 4: Replace the FTS lookup with a trigram substring lookup**

This is the heart of the port. `MATCH` ranked by BM25 becomes a substring
match that pg_trgm can index, with prefix matches ordered first so that the
`LIMIT` cannot drop a better result:

```python
    def _product_ids_by_trigram(
        self, query: str, column: str, limit: int = 200
    ) -> list[int]:
        """Matches `query` as a substring of one normalised product column.

        pg_trgm indexes `LIKE '%x%'` but only for patterns of at least three
        consecutive characters, so a shorter query falls back to a prefix scan
        on the base column and contributes nothing on the folded column, where
        folding can shorten an already short query further.

        The ordering puts prefix matches first. Without a relevance score to
        sort by, an unordered LIMIT would let the cutoff drop the very rows a
        user typed most of.
        """
        if len(query) < MIN_TRIGRAM:
            if column == "name_norm":
                return self._product_ids_by_prefix(query)
            return []
        pattern = "%" + _escape_like(query) + "%"
        prefix = _escape_like(query) + "%"
        rows = self.reader.all(
            f"SELECT id FROM {self.tables.products}"
            f" WHERE {column} LIKE %s ESCAPE '\\'"
            " ORDER BY ("
            f"   {column} LIKE %s ESCAPE '\\'"
            " ) DESC, id"
            " LIMIT %s",
            (pattern, prefix, limit),
        )
        return [row["id"] for row in rows]
```

Rename every call site of `_product_ids_by_fts` to
`_product_ids_by_trigram` and delete `_phrase`, which existed only to stop FTS5
parsing `:`, `*` and `"` as query operators. Delete the
`except sqlite3.OperationalError` branch: a `LIKE` pattern cannot be malformed,
so that failure mode is gone.

Delete the comment block above the old `_product_ids_by_fts` that explains
column-scoped `MATCH`, and keep a shorter version of it on the new function,
because the pairing rule still matters: `name_norm` pairs with `norm()` and
`name_fold_light` with `fold_light()`.

- [ ] **Step 5: Update every remaining query**

In the aggregation methods, swap `?` for `%s` and qualify the tables:

| old | new |
|-----|-----|
| `FROM order_items oi` | `FROM {self.tables.order_items} oi` |
| `JOIN orders o ON o.id = oi.order_id` | `JOIN {self.tables.orders} o ON o.id = oi.order_id` |
| `JOIN products p ON p.id = oi.product_id` | `JOIN {self.tables.products} p ON p.id = oi.product_id` |
| `JOIN customers c ON c.id = o.customer_id` | `JOIN {self.tables.customers} c ON c.id = o.customer_id` |
| `FROM products WHERE id IN (...)` | `FROM {self.tables.products} WHERE id IN (...)` |
| `"?" for _ in product_ids` | `"%s" for _ in product_ids` |
| `"?"` for limit and offset | `"%s"` |
| `GROUP_CONCAT(DISTINCT o.store_code)` | `string_agg(DISTINCT o.store_code, ',' ORDER BY o.store_code)` |
| `GROUP_CONCAT(DISTINCT o.vip_group)` | `string_agg(DISTINCT o.vip_group, ',' ORDER BY o.vip_group)` |

`MAX(COALESCE(o.date_to, o.date_from))` returns a `date` in Postgres rather
than a string. The API contract says `last_date` is an ISO string, so wrap
those five call sites:

```python
def _iso_date(value):
    return value.isoformat() if value is not None else None
```

and use `"MAX(...) AS last_date"` then `_iso_date(row["last_date"])` in
`_product_results`, `_customer_breakdown`, `_customer_results`,
`_products_for_customer`.

- [ ] **Step 6: Update the three call sites that pass the reader**

```python
        detection = detect(query, self.reader, self.tables)
```
```python
        normalized = detect(text, self.reader, self.tables).normalized_query
```
```python
        matches = best_customers(
            detection.normalized_query, self.reader, self.tables
        )
```
```python
        for product_id, _text, _score in best_products(
            detection.normalized_query, self.reader, self.tables
        ):
```

Replace `import sqlite3` with `from ..db import Reader, Tables`. Rewrite the
class docstring so layer 3 reads "trigram substring match" instead of "FTS5
trigram substring match".

- [ ] **Step 7: Run the engine tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_search_engine_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 8: Commit**

```powershell
git add src/order_search/search/engine.py tests/test_search_engine_pg.py
git commit -m "feat(search): match products by trigram substring instead of FTS5"
```

---

### Task 8: The parity gate

Nothing else in this plan matters if search results change. This task loads the
real workbook into a test database and asserts the ground truth.

**Files:**
- Create: `src/order_search/ingest/load.py`
- Create: `tests/test_parity.py`
- Test: `tests/test_parity.py`

- [ ] **Step 1: Write the failing test**

`tests/test_parity.py`

```python
import pytest

from order_search.db import Tables
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.load import load_into_version
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE


@pytest.fixture
def loaded(client_db):
    data = load_into_version(client_db, read_order_rows(DATA_FILE), 1)
    return client_db, data


def test_the_import_report_matches_the_workbook(loaded):
    _, data = loaded
    assert data.report.products == 15
    assert data.report.customers == 20
    assert data.report.orders == 1000
    assert data.report.barcodes == 127
    assert data.report.rows_skipped == 0


def test_a_customer_name_finds_exactly_one_customer(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    result = engine.search("สุรชัย")
    assert result["mode"] == "customer"
    assert len(result["customers"]) == 1
    assert result["customers"][0]["order_count"] == 65


def test_a_barcode_finds_exactly_one_product(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    result = engine.search("8850250001234")
    assert result["mode"] == "product"
    assert [p["name"] for p in result["products"]] == ["น้ำดื่มสิงห์ 600 มล. x 12"]


def test_a_short_product_query_finds_four_products(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    result = engine.search("น้ำ")
    assert len(result["products"]) == 4


def test_suggestions_match_the_old_count(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    assert len(engine.suggest("น้ำ")) == 4


def test_filters_narrow_a_product_result(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    unfiltered = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
    filtered = engine.search(
        "น้ำดื่มสิงห์ 600 มล. x 12", filters={"store_code": ["101"], "order_type": ["Pickup"]}
    )
    assert filtered["products"][0]["order_count"] < unfiltered["products"][0]["order_count"]


def test_a_customer_detail_lists_that_customers_products(loaded):
    client_db, _ = loaded
    engine = SearchEngine(client_db, Tables.from_schemas("t_item", "t_sales"))
    history = engine.customer_history(1)
    assert history[0]["customer_id"] == 1
    assert history[0]["products"]
    assert history[0]["products"][0]["stores"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_parity.py -o addopts="" -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'order_search.ingest.load'`

- [ ] **Step 3: Write the loader**

`src/order_search/ingest/load.py`

```python
from __future__ import annotations

from typing import Any

from .transform import TransformedData, transform

PRODUCT_COLUMNS = (
    "id", "name", "name_norm", "name_fold_light", "name_fold_heavy",
    "dept", "class_code", "subclass_code", "pack_size", "unit",
)
CUSTOMER_COLUMNS = ("id", "name", "name_norm", "name_fold_light", "name_fold_heavy")
ORDER_COLUMNS = (
    "id", "order_no", "store_code", "customer_id", "order_type",
    "date_from", "date_to", "item_remark", "vip_remark", "vip_group",
)
ORDER_ITEM_COLUMNS = ("order_id", "product_id", "qty", "price")
BARCODE_COLUMNS = ("product_id", "barcode")

VIEW_COLUMNS = {
    "products": (
        "id, name, name_norm, name_fold_light, name_fold_heavy,"
        " dept, class_code, subclass_code, pack_size, unit"
    ),
    "product_barcodes": "product_id, barcode",
    "customers": "id, name, name_norm, name_fold_light, name_fold_heavy",
    "orders": (
        "id, order_no, store_code, customer_id, order_type,"
        " date_from, date_to, item_remark, vip_remark, vip_group"
    ),
    "order_items": "order_id, product_id, qty, price",
}


def load_into_version(
    database, rows: list[dict[str, Any]], version: int
) -> TransformedData:
    """Fills the `{table}_v{version}` tables and repoints the views at them.

    The views move only after every copy has landed, so a failure anywhere in
    this function leaves the previous version serving traffic.
    """
    data = transform(rows)
    item = database.schema_item
    sales = database.schema_sales

    for ddl in _version_ddl(version, item, sales).values():
        database.execute_script(ddl)
    database.run(f'TRUNCATE "{item}"."products_v{version}" CASCADE')
    database.run(f'TRUNCATE "{item}"."product_barcodes_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."customers_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."orders_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."order_items_v{version}" CASCADE')

    database.copy(f'"{item}"."products_v{version}"', PRODUCT_COLUMNS, data.products)
    database.copy(f'"{sales}"."customers_v{version}"', CUSTOMER_COLUMNS, data.customers)
    database.copy(f'"{sales}"."orders_v{version}"', ORDER_COLUMNS, data.orders)
    database.copy(
        f'"{sales}"."order_items_v{version}"', ORDER_ITEM_COLUMNS, data.order_items
    )
    database.copy(
        f'"{item}"."product_barcodes_v{version}"', BARCODE_COLUMNS, data.barcodes
    )

    for name, columns in VIEW_COLUMNS.items():
        schema = item if name in ("products", "product_barcodes") else sales
        database.execute_script(
            f'CREATE OR REPLACE VIEW "{schema}"."{name}" AS'
            f" SELECT {columns} FROM \"{schema}\".\"{name}_v{version}\";"
        )

    database.run(
        f'UPDATE "{database.schema_app}"."data_versions" SET is_current = false'
        " WHERE is_current"
    )
    database.run(
        f'INSERT INTO "{database.schema_app}"."data_versions"'
        " (version, source_filename, row_count, product_count, customer_count,"
        " order_count, barcode_count, is_current)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,true)",
        (
            version,
            "load",
            data.report.rows_imported,
            data.report.products,
            data.report.customers,
            data.report.orders,
            data.report.barcodes,
        ),
    )
    return data


def _version_ddl(version: int, item: str, sales: str) -> dict[str, str]:
    return {
        "products": f"""
            CREATE TABLE IF NOT EXISTS "{item}"."products_v{version}" (
                id bigint PRIMARY KEY, name text NOT NULL, name_norm text NOT NULL,
                name_fold_light text NOT NULL, name_fold_heavy text NOT NULL,
                dept integer, class_code integer, subclass_code integer,
                pack_size integer, unit text);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_norm"
                ON "{item}"."products_v{version}" (name_norm text_pattern_ops);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_trgm"
                ON "{item}"."products_v{version}" USING gin (name_norm gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_fold"
                ON "{item}"."products_v{version}" USING gin (name_fold_light gin_trgm_ops);
        """,
        "product_barcodes": f"""
            CREATE TABLE IF NOT EXISTS "{item}"."product_barcodes_v{version}" (
                product_id bigint NOT NULL, barcode text NOT NULL,
                PRIMARY KEY (product_id, barcode));
            CREATE INDEX IF NOT EXISTS "{item}_barcodes_v{version}_code"
                ON "{item}"."product_barcodes_v{version}" (barcode);
        """,
        "customers": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."customers_v{version}" (
                id bigint PRIMARY KEY, name text NOT NULL, name_norm text NOT NULL,
                name_fold_light text NOT NULL, name_fold_heavy text NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS "{sales}_customers_v{version}_norm"
                ON "{sales}"."customers_v{version}" (name_norm);
            CREATE INDEX IF NOT EXISTS "{sales}_customers_v{version}_trgm"
                ON "{sales}"."customers_v{version}" USING gin (name_norm gin_trgm_ops);
        """,
        "orders": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."orders_v{version}" (
                id bigint PRIMARY KEY, order_no text, store_code text,
                customer_id bigint NOT NULL, order_type text, date_from date,
                date_to date, item_remark text, vip_remark text, vip_group text);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_customer"
                ON "{sales}"."orders_v{version}" (customer_id);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_from"
                ON "{sales}"."orders_v{version}" (date_from);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_to"
                ON "{sales}"."orders_v{version}" (date_to);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_store"
                ON "{sales}"."orders_v{version}" (store_code);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_type"
                ON "{sales}"."orders_v{version}" (order_type);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_vip"
                ON "{sales}"."orders_v{version}" (vip_group);
        """,
        "order_items": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."order_items_v{version}" (
                order_id bigint NOT NULL, product_id bigint NOT NULL,
                qty numeric, price numeric, PRIMARY KEY (order_id, product_id));
            CREATE INDEX IF NOT EXISTS "{sales}_order_items_v{version}_product"
                ON "{sales}"."order_items_v{version}" (product_id);
        """,
    }
```

Note the index names carry the version number, so loading a second version
cannot collide with the first version's index names.

- [ ] **Step 4: Run the parity tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_parity.py -o addopts="" -q`
Expected: PASS, all seven. If `test_a_short_product_query_finds_four_products`
fails, the trigram layer or the `name_fold_light` pairing is wrong; go back to
Task 7 rather than loosening the test.

- [ ] **Step 5: Commit**

```powershell
git add src/order_search/ingest/load.py tests/test_parity.py
git commit -m "feat(ingest): load a workbook into a Postgres version and prove parity"
```

---

### Task 9: Port users, audit and security

**Files:**
- Modify: `api/users.py`
- Modify: `api/audit.py`
- Modify: `api/security.py`
- Delete: `api/app_db.py`
- Delete: `api/db_schema.sql`
- Test: `tests/test_users_pg.py`
- Test: `tests/test_security_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_users_pg.py`

```python
import pytest

from api.users import authenticate, bootstrap_admin, create_user, list_users, update_user


@pytest.fixture
def users_db(client_db):
    yield client_db
    client_db.run('TRUNCATE "app"."users" CASCADE')


def test_create_and_authenticate(users_db):
    create_user(users_db, "boss", "password123", "admin")
    found = authenticate(users_db, "boss", "password123")
    assert found["role"] == "admin"
    assert found["is_active"] is True


def test_a_wrong_password_does_not_authenticate(users_db):
    create_user(users_db, "boss", "password123", "admin")
    assert authenticate(users_db, "boss", "wrong") is None


def test_an_unknown_role_is_rejected(users_db):
    with pytest.raises(ValueError):
        create_user(users_db, "boss", "password123", "wizard")


def test_bootstrap_only_fires_when_no_admin_exists(users_db):
    assert bootstrap_admin(users_db, "root", "password123") is True
    assert bootstrap_admin(users_db, "other", "password123") is False
    assert len(list_users(users_db)) == 1


def test_deactivating_a_user_blocks_login(users_db):
    user_id = create_user(users_db, "staff1", "password123", "staff")
    update_user(users_db, user_id, is_active=False)
    assert authenticate(users_db, "staff1", "password123") is None
```

`tests/test_security_pg.py`

```python
import pytest

from api import security, users


@pytest.fixture
def session_db(client_db):
    create = users.create_user(client_db, "boss", "password123", "admin")
    yield client_db, create
    client_db.run('TRUNCATE "app"."users" CASCADE')


def issue(db):
    user = users.get_by_username(db, "boss")
    return security.issue_session(
        db, "test-secret", user,
        security.timedelta(minutes=15), security.timedelta(days=7),
    )


def test_a_refresh_token_is_single_use(session_db):
    db, _user_id = session_db
    _access, refresh = issue(db)
    security.rotate_refresh(
        db, "test-secret", refresh, security.timedelta(minutes=15),
        security.timedelta(days=7), security.timedelta(minutes=30),
    )
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, "test-secret", refresh, security.timedelta(minutes=15),
            security.timedelta(days=7), security.timedelta(minutes=30),
        )


def test_revoking_everything_blocks_the_user(session_db):
    db, user_id = session_db
    _access, refresh = issue(db)
    security.revoke_all_for_user(db, user_id)
    with pytest.raises(security.InvalidToken):
        security.rotate_refresh(
            db, "test-secret", refresh, security.timedelta(minutes=15),
            security.timedelta(days=7), security.timedelta(minutes=30),
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_users_pg.py tests\test_security_pg.py -o addopts="" -q`
Expected: FAIL, `api.app_db` no longer exists

- [ ] **Step 3: Port users.py**

Every query becomes `%s` and carries the `app` schema. The one that needs care
is `is_active`, which is now a boolean:

```python
from __future__ import annotations

from .passwords import hash_password, verify_password

ROLES = ("staff", "admin")


def _users(schema: str) -> str:
    return f'"{schema}"."users"'


def get_by_username(db, username: str):
    return db.one(
        f"SELECT * FROM {_users(db.schema_app)} WHERE username = %s", (username,)
    )


def get_by_id(db, user_id: int):
    return db.one(f"SELECT * FROM {_users(db.schema_app)} WHERE id = %s", (user_id,))


def create_user(db, username: str, password: str, role: str) -> int:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    db.run(
        f"INSERT INTO {_users(db.schema_app)}"
        " (username, password_hash, role, is_active, created_at)"
        " VALUES (%s,%s,%s,true,now())",
        (username, hash_password(password), role),
    )
    return db.one(
        f"SELECT id FROM {_users(db.schema_app)} WHERE username = %s", (username,)
    )["id"]


def authenticate(db, username: str, password: str):
    row = get_by_username(db, username)
    if row is None or not row["is_active"]:
        return None
    if not verify_password(row["password_hash"], password):
        return None
    return row


def list_users(db):
    return db.all(
        f"SELECT id, username, role, is_active, created_at"
        f" FROM {_users(db.schema_app)} ORDER BY id"
    )


def update_user(db, user_id: int, *, password=None, role=None, is_active=None) -> bool:
    if get_by_id(db, user_id) is None:
        return False
    table = _users(db.schema_app)
    if password is not None:
        db.run(
            f"UPDATE {table} SET password_hash = %s WHERE id = %s",
            (hash_password(password), user_id),
        )
    if role is not None:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        db.run(f"UPDATE {table} SET role = %s WHERE id = %s", (role, user_id))
    if is_active is not None:
        db.run(
            f"UPDATE {table} SET is_active = %s WHERE id = %s", (is_active, user_id)
        )
    return True


def bootstrap_admin(db, username: str, password: str) -> bool:
    row = db.one(
        f"SELECT count(*) AS n FROM {_users(db.schema_app)} WHERE role = 'admin'"
    )
    if row["n"]:
        return False
    create_user(db, username, password, "admin")
    return True
```

Drop the `_now()` helper: `created_at` now defaults to `now()` in the database,
so the application and the database cannot disagree about the clock.

- [ ] **Step 4: Port audit.py**

Same treatment: `%s`, and `created_at` defaults to `now()`.

```python
def record(db, *, user_id, action, query=None, mode=None, result_count=None,
           ip=None, user_agent=None) -> None:
    db.run(
        f'INSERT INTO "{db.schema_app}"."audit_log"'
        " (user_id, action, query, mode, result_count, ip, user_agent)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (user_id, action, query, mode, result_count, ip, user_agent),
    )
```

- [ ] **Step 5: Port security.py**

Four changes, all mechanical:

```python
def _tokens(schema: str) -> str:
    return f'"{schema}"."refresh_tokens"'
```

`issue_session` inserts with `now()` arithmetic and `false` instead of `0`:

```python
    db.run(
        f"INSERT INTO {_tokens(db.schema_app)}"
        " (id, user_id, issued_at, expires_at, last_used_at, revoked)"
        " VALUES (%s,%s,now(),now() + make_interval(secs => %s),now(),false)",
        (jti, user["id"], refresh_ttl.total_seconds()),
    )
```

`rotate_refresh` keeps the single-statement claim, which is the property that
makes rotation safe under concurrency, and drops the string date parsing
because `timestamptz` already returns a `datetime`:

```python
def rotate_refresh(db, secret, token, access_ttl, refresh_ttl, idle_timeout):
    payload = decode_token(secret, token, REFRESH)
    jti = payload.get("jti")
    row = db.one(
        f"SELECT * FROM {_tokens(db.schema_app)} WHERE id = %s", (jti,)
    )
    if row is None:
        raise InvalidToken("refresh token unknown")
    claimed = db.one(
        f"UPDATE {_tokens(db.schema_app)} SET revoked = true, last_used_at = now()"
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
```

`revoke_refresh` and `revoke_all_for_user` become `%s` updates setting
`revoked = true`. Delete `_iso`, `_parse_iso` and the `datetime, timedelta,
timezone` import of `timezone` only where it is now unused; `_now` stays.

Add `from datetime import timedelta` to the module so the test can pass
`security.timedelta`.

- [ ] **Step 6: Run the new tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_users_pg.py tests\test_security_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 7: Delete the SQLite app database**

```powershell
git rm api/app_db.py api/db_schema.sql
```

- [ ] **Step 8: Commit**

```powershell
git add api/users.py api/audit.py api/security.py tests/test_users_pg.py tests/test_security_pg.py
git commit -m "feat(auth): store users, sessions and the audit log in Postgres"
```

---

### Task 10: Port the routers and the lifespan

**Files:**
- Modify: `api/main.py`
- Modify: `api/db_helpers.py`
- Modify: `api/routers/search.py`
- Modify: `api/routers/filters.py`
- Modify: `api/routers/auth.py`
- Modify: `api/routers/admin.py`
- Modify: `api/schemas.py`
- Delete: `api/crypto.py`
- Delete: `api/snapshot.py`
- Delete: `api/imports.py`
- Test: `tests/test_api_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_api_pg.py`

```python
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.load import load_into_version
from conftest import DATA_FILE


@pytest.fixture
def api(client_db, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "false")
    load_into_version(client_db, read_order_rows(DATA_FILE), 1)
    with TestClient(create_app(client_db)) as client:
        yield client


def login(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "test-admin-pass"}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_healthz_reports_a_loaded_database(api):
    body = api.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["products"] == 15


def test_login_then_search_finds_the_customer(api):
    headers = login(api)
    body = api.post("/api/v1/search", json={"q": "สุรชัย"}, headers=headers).json()
    assert body["mode"] == "customer"
    assert len(body["customers"]) == 1


def test_a_search_without_a_session_is_rejected(api):
    assert api.post("/api/v1/search", json={"q": "สุรชัย"}).status_code == 401


def test_the_audit_log_records_a_search(api):
    headers = login(api)
    api.post("/api/v1/search", json={"q": "สุรชัย"}, headers=headers)
    entries = api.get("/api/v1/admin/audit?action=search").json()["entries"]
    assert entries
    assert entries[0]["query"] == "สุรชัย"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_api_pg.py -o addopts="" -q`
Expected: FAIL, `create_app()` takes 0 positional arguments

- [ ] **Step 3: Change the lifespan**

In `api/main.py`, the lifespan becomes:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    if settings.cookie_secure and settings.secret_key == INSECURE_SECRET:
        raise RuntimeError(
            "SECRET_KEY is still the insecure default; set a strong random value"
        )
    _assert_trgm_supported()
    database = Database(
        settings.database_url,
        settings.schema_item,
        settings.schema_sales,
        settings.schema_app,
    )
    app.state.db = database
    users.bootstrap_admin(
        database, settings.admin_username, settings.admin_password
    )
    try:
        yield
    finally:
        database.close()
```

`_assert_fts5_supported` becomes `_assert_trgm_supported` and probes
`SELECT similarity('abc','abd')`, because the SQLite FTS5 probe no longer
applies:

```python
def _assert_trgm_supported() -> None:
    with psycopg.connect("") as probe:
        try:
            probe.execute("SELECT similarity('abc', 'abd')")
        except psycopg.Error as exc:
            raise RuntimeError("this database lacks the pg_trgm extension") from exc
```

Note this probe opens a throwaway connection from the environment's
`PGDATABASE`; if that is inconvenient, drop the probe and rely on migration
`001_extensions.sql` failing loudly instead.

`create_app` gains an optional injection point so tests can pass a pool:

```python
def create_app(settings: Settings | None = None, database=None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Order Search", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    if database is not None:
        app.state.db = database
    ...
```

and the lifespan uses `app.state.db` when it is already set instead of building
its own.

`/healthz` now reports the loaded dataset instead of a boolean, because a
deployed service needs to say what it is actually serving:

```python
@router.get("/healthz")
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
```

- [ ] **Step 4: Point the routers at the database**

In `api/db_helpers.py`, rename `get_app_db` to `get_db` and return
`request.app.state.db`. Update every import of it.

In `api/routers/search.py`, replace `request.app.state.snapshot.search(...)`
with a `SearchEngine` built once per request:

```python
from order_search.db import Tables
from order_search.search.engine import SearchEngine

def _engine(request: Request) -> SearchEngine:
    db = get_db(request)
    return SearchEngine(db, Tables.from_schemas(db.schema_item, db.schema_sales))
```

`suggest`, `customer_history` and `product_customers` use the same helper.
`facets()` and `counts()` are deleted here and re-added as functions in
`api/routers/filters.py` and `api/routers/admin.py` respectively, both reading
through the views.

- [ ] **Step 5: Delete the import and snapshot endpoints**

`api/routers/admin.py` loses `/import`, `/import/versions` and
`/import/rollback`, because those need the resumable pipeline that the next
plan builds. Keep `/users`, `/audit`, and add the version listing as a plain
read over `app.data_versions`:

```python
@router.get("/versions")
def versions(request: Request, user=Depends(security.require_admin)):
    db = get_db(request)
    return {
        "versions": db.all(
            f'SELECT id, version, source_filename, row_count, product_count,'
            f' customer_count, order_count, is_current, created_at'
            f' FROM "{db.schema_app}"."data_versions" ORDER BY id DESC'
        )
    }
```

Delete `api/imports.py`, `api/crypto.py` and `api/snapshot.py`. In
`api/schemas.py`, delete `ImportRequest`, `VersionListResponse` and
`RollbackRequest` if nothing else references them, and keep every schema the
search, auth, user and audit endpoints still use.

- [ ] **Step 6: Run the API tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_api_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 7: Commit**

```powershell
git add api/main.py api/db_helpers.py api/routers api/schemas.py tests/test_api_pg.py
git commit -m "feat(api): serve search and auth from Postgres"
```

---

### Task 11: The database-backed rate limiter

**Files:**
- Modify: `api/ratelimit.py`
- Modify: `api/security.py`
- Test: `tests/test_ratelimit_pg.py`

- [ ] **Step 1: Write the failing test**

`tests/test_ratelimit_pg.py`

```python
from api.ratelimit import RateLimiter


def test_a_key_is_allowed_up_to_the_limit(client_db):
    limiter = RateLimiter(client_db, limit=3, window_seconds=60)
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:1") is False


def test_two_limiters_share_one_budget(client_db):
    """On Vercel each warm instance is a separate object with its own memory.
    The limit only means something if the count lives in the database.
    """
    first = RateLimiter(client_db, limit=2, window_seconds=60)
    second = RateLimiter(client_db, limit=2, window_seconds=60)
    assert first.allow("ip:10.0.0.1") is True
    assert second.allow("ip:10.0.0.1") is True
    assert first.allow("ip:10.0.0.1") is False
    assert second.allow("ip:10.0.0.1") is False


def test_different_keys_do_not_share_a_budget(client_db):
    limiter = RateLimiter(client_db, limit=1, window_seconds=60)
    assert limiter.allow("user:1") is True
    assert limiter.allow("user:2") is True


def test_the_budget_resets_in_the_next_window(client_db):
    from datetime import datetime, timezone

    limiter = RateLimiter(client_db, limit=1, window_seconds=60)
    first = datetime(2026, 9, 27, 10, 0, 30, tzinfo=timezone.utc)
    second = datetime(2026, 9, 27, 10, 1, 30, tzinfo=timezone.utc)
    assert limiter.allow("user:9", now=first) is True
    assert limiter.allow("user:9", now=first) is False
    assert limiter.allow("user:9", now=second) is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ratelimit_pg.py -o addopts="" -q`
Expected: FAIL, `RateLimiter()` takes 1 positional argument but 2 were given

- [ ] **Step 3: Rewrite the limiter**

`api/ratelimit.py`

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone


class RateLimiter:
    """Fixed-window limiter whose counters live in the database.

    An in-process counter is per warm instance on a serverless platform, so
    `limit` requests per minute would quietly become `limit` times the number
    of instances. One upsert per request is the price of a limit that holds.
    """

    def __init__(self, database, limit: int, window_seconds: int = 60) -> None:
        self.db = database
        self.limit = limit
        self.window = window_seconds

    def allow(self, key: str, now: datetime | None = None) -> bool:
        moment = now or datetime.now(timezone.utc)
        window = moment.replace(second=0, microsecond=0)
        table = f'"{self.db.schema_app}"."rate_buckets"'
        row = self.db.one(
            f"INSERT INTO {table} (key, window, hits) VALUES (%s, %s, 1)"
            " ON CONFLICT (key, window) DO UPDATE"
            " SET hits = rate_buckets.hits + 1"
            " RETURNING hits",
            (key, window),
        )
        return row is not None and row["hits"] <= self.limit
```

The window is truncated to the minute, so a caller that supplies a different
`now` still lands in the same bucket. The upsert and the read are one statement,
so a burst of concurrent requests cannot interleave an increment and a read.

- [ ] **Step 4: Wire it up**

In `api/main.py`, replace the `RateLimiter(settings.rate_limit_per_minute)`
construction with `RateLimiter(database, settings.rate_limit_per_minute)`. The
`allow(key)` call sites in `api/security.py` need no change, because the method
signature is unchanged.

- [ ] **Step 5: Run the tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_ratelimit_pg.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 6: Delete the old test and commit**

```powershell
git rm tests/test_ratelimit.py
git add api/ratelimit.py api/security.py api/main.py tests/test_ratelimit_pg.py
git commit -m "feat(ratelimit): count requests in the database so the limit holds"
```

---

### Task 12: The loader script

**Files:**
- Create: `scripts/load_postgres.py`
- Test: `tests/test_load_script.py`

- [ ] **Step 1: Write the failing test**

`tests/test_load_script.py`

```python
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def test_the_script_reports_the_import_counts(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    env["DB_SCHEMA_ITEM"] = "t_item"
    env["DB_SCHEMA_SALES"] = "t_sales"
    env["DB_SCHEMA_APP"] = "t_app"
    result = subprocess.run(
        [
            str(PYTHON), str(ROOT / "scripts" / "load_postgres.py"),
            str(ROOT / "sample_order_data_1000_records.xlsx"),
            "--version", "2",
        ],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "products       : 15" in result.stdout
    assert "customers      : 20" in result.stdout
    assert "orders         : 1000" in result.stdout
    assert "barcodes       : 127" in result.stdout


def test_the_script_writes_into_the_configured_schemas(client_db):
    assert client_db.one('SELECT count(*) AS n FROM "t_item"."products_v2"')["n"] == 15
    assert client_db.one('SELECT count(*) AS n FROM "t_sales"."orders"')["n"] == 1000
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_load_script.py -o addopts="" -q`
Expected: FAIL, the script does not exist

- [ ] **Step 3: Write the script**

`scripts/load_postgres.py`

```python
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.config import Settings
from api.db import Database
from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.load import load_into_version


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load an order workbook into a new Postgres version."
    )
    parser.add_argument("source", help="path to the .xlsx file")
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_file():
        print(f"source file not found: {source}", file=sys.stderr)
        return 2

    settings = Settings()
    if not settings.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    database = Database(
        settings.database_url,
        settings.schema_item,
        settings.schema_sales,
        settings.schema_app,
    )
    try:
        data = load_into_version(
            database, read_order_rows(source), args.version
        )
    finally:
        database.close()

    report = data.report
    print(f"rows read      : {report.rows_read}")
    print(f"rows imported  : {report.rows_imported}")
    print(f"rows skipped   : {report.rows_skipped}")
    print(f"products       : {report.products}")
    print(f"customers      : {report.customers}")
    print(f"orders         : {report.orders}")
    print(f"barcodes       : {report.barcodes}")
    print(f"no pack size   : {report.missing_pack_size_products}")
    print(f"wrote version  : {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_load_script.py -o addopts="" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```powershell
git add scripts/load_postgres.py tests/test_load_script.py
git commit -m "feat(scripts): load a workbook into a new Postgres version"
```

---

### Task 13: Retire the SQLite snapshot path

Only after the parity suite is green.

**Files:**
- Delete: `snapshot.enc`
- Delete: `api/crypto.py`
- Delete: `api/snapshot.py`
- Delete: `src/order_search/ingest/schema.sql`
- Delete: `src/order_search/ingest/schema_path.py`
- Delete: `src/order_search/ingest/build.py`
- Delete: `scripts/build_snapshot.py`
- Delete: `scripts/import_excel.py`
- Delete: `scripts/query_cli.py`
- Delete: `scripts/make_admin.py`
- Delete: `tests/test_crypto.py`
- Delete: `tests/test_snapshot_store.py`
- Delete: `tests/test_container.py`
- Delete: `tests/test_deploy_render.py`
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Confirm parity is green first**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_parity.py -o addopts="" -q`
Expected: PASS. If it is not, stop. Deleting the old path without parity is how
the ground truth is lost.

- [ ] **Step 2: Remove the container deployment**

```powershell
git rm snapshot.enc Dockerfile .dockerignore render.yaml
git rm .github/workflows/docker-publish.yml scripts/deploy_render.py
```

- [ ] **Step 3: Remove the SQLite ingest and the snapshot modules**

```powershell
git rm api/crypto.py api/snapshot.py
git rm src/order_search/ingest/schema.sql src/order_search/ingest/schema_path.py
git rm src/order_search/ingest/build.py
git rm scripts/build_snapshot.py scripts/import_excel.py scripts/query_cli.py scripts/make_admin.py
git rm tests/test_crypto.py tests/test_snapshot_store.py
git rm tests/test_container.py tests/test_deploy_render.py
```

Add a replacement admin CLI so operators are not locked out of the only path
that creates an admin:

`scripts/make_admin.py`

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.config import Settings
from api.db import Database
from api.users import bootstrap_admin, create_user, get_by_username, update_user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create or reset an admin account in Postgres."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=("staff", "admin"))
    args = parser.parse_args()

    settings = Settings()
    if not settings.database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    database = Database(
        settings.database_url,
        settings.schema_item,
        settings.schema_sales,
        settings.schema_app,
    )
    try:
        existing = get_by_username(database, args.username)
        if existing is None:
            create_user(database, args.username, args.password, args.role)
            print(f"created {args.role} {args.username}")
        else:
            update_user(
                database,
                existing["id"],
                password=args.password,
                role=args.role,
                is_active=True,
            )
            print(f"updated {args.role} {args.username}")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Strip the Hugging Face front matter from the README**

Delete the YAML block between the first two `---` lines, and delete the
`#### Deploy to a Hugging Face Space` section.

- [ ] **Step 5: Rewrite the README setup and deploy sections**

Replace the snapshot instructions with:

```markdown
## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:DATABASE_URL = "<your Supabase transaction pooler url>"
```

## Load the data

```powershell
.\.venv\Scripts\python.exe scripts\load_postgres.py sample_order_data_1000_records.xlsx
```

The report must show `products : 15`, `customers : 20`, `barcodes : 127`.
Each run writes a new `{table}_v{n}` set and repoints the views, so the
previous version stays available.

## Run locally

```powershell
$env:PYTHONPATH = "src"
$env:SECRET_KEY = "dev-secret-change-me-please-32-bytes"
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "change-me-now"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload
```
```

Also document that `DATABASE_URL` must be the transaction pooler on port 6543,
and that the direct connection is IPv6-only.

- [ ] **Step 6: Run the full suite**

Run: `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q`
Expected: PASS, with no collection errors from the deleted modules. Fix any
leftover import of `api.crypto` or `api.snapshot`.

- [ ] **Step 7: Commit**

```powershell
git add -A
git commit -m "refactor: retire the sealed SQLite snapshot and the container deployment"
```

---

### Task 14: Prove it end to end

- [ ] **Step 1: Run the whole suite one more time**

```powershell
.\.venv\Scripts\python.exe -m pytest -o addopts="" -q
```
Expected: PASS. Record the count in the commit message.

- [ ] **Step 2: Load the real project**

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts\load_postgres.py sample_order_data_1000_records.xlsx
```
Expected: products 15, customers 20, orders 1000, barcodes 127. The script
reads `DATABASE_URL` from `.env`.

- [ ] **Step 3: Start the app and drive it**

```powershell
$env:SECRET_KEY = "a-long-random-value-for-local-use-only"
$env:ADMIN_PASSWORD = "change-me-now"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Then confirm `GET /healthz` reports `products: 15`, log in, and run the three
ground-truth searches in the browser.

- [ ] **Step 4: Commit any fixes the manual run revealed**

```powershell
git add -A
git commit -m "fix: address what the end-to-end run surfaced"
```

---

## Self-review against the design

| design requirement | task |
|-------------------|------|
| Three namespaces `item`, `sales`, `app` | 2 |
| Version tables plus five views | 2, 8 |
| pg_trgm indexes, prefix-first ordering | 2, 7 |
| Retain one previous version | not in this plan; the views make it a one-line change and the rollback endpoints arrive with the import plan |
| Search results identical | 8 |
| Namespace grants revoked from `anon` | 2 |
| Rate limit moved to the database | 11 |
| `DATA_KEY` removed | 1, 13 |
| One-shot loader | 12 |
| Delete the SQLite snapshot path | 13 |

Deliberately deferred to the next plan: the resumable chunked import, Supabase
Storage, rollback endpoints, and Vercel deployment.
