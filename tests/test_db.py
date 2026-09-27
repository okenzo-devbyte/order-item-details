import pytest

from api.db import Database
from order_search.db import Reader

UNREACHABLE_DSN = "postgresql://u:p@localhost:1/none"


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = self.connection.rowcount

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql, params=None):
        self.connection.statements.append((sql, params))

    def fetchone(self):
        return self.connection.one_row

    def fetchall(self):
        return list(self.connection.rows)

    def copy(self, statement):
        copy = FakeCopy(self.connection, statement)
        self.connection.copies.append(copy)
        return copy


class FakeCopy:
    def __init__(self, connection, statement):
        self.connection = connection
        self.statement = statement
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def write_row(self, row):
        self.rows.append(row)


class FakeTransaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.connection.commits += 1
        return False


class FakeConnection:
    """Stands in for one psycopg connection.

    Only the surface `Database` touches is implemented, and each counter counts
    exactly one event so a test can say which of the two ways a statement could
    have been committed actually happened.
    """

    def __init__(self, rows=None):
        self.statements = []
        self.copies = []
        self.rows = rows or []
        self.one_row = None
        self.rowcount = 1
        self.commits = 0
        self.pooled_exits = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.pooled_exits += 1
        return False

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        return FakeTransaction(self)

    def sql(self):
        return [statement for statement, _ in self.statements]

    def inserts_into(self, table_fragment):
        return [
            params
            for statement, params in self.statements
            if "INSERT" in statement.upper() and table_fragment in statement
        ]


class FakePool:
    def __init__(self, connection):
        self._connection = connection

    def connection(self):
        return self._connection

    def close(self):
        return None


def build() -> Database:
    """A Database that has a pool but has never opened a socket.

    Port 1 refuses instantly and `min_size=0` means the pool has no connection
    to open, so nothing here needs a server.
    """
    return Database(UNREACHABLE_DSN, "t_item", "t_sales", "t_app")


def offline(rows=None) -> tuple[Database, FakeConnection]:
    """A Database whose pool hands out one recording connection."""
    db = build()
    db.pool.close()
    connection = FakeConnection(rows)
    db.pool = FakePool(connection)
    return db, connection


def test_database_builds_a_pool_without_connecting():
    db = build()
    assert db.pool is not None
    db.close()


def test_the_pool_is_the_psycopg_pool_class():
    # `ConnectionPool` ships in the psycopg_pool distribution, which is only
    # present when the `pool` extra is installed. Reading the attribute off
    # `psycopg` itself raises AttributeError and the app cannot boot.
    import psycopg_pool

    db = build()
    assert isinstance(db.pool, psycopg_pool.ConnectionPool)
    db.close()


def test_database_satisfies_the_reader_protocol():
    db = build()
    assert isinstance(db, Reader)
    db.close()


def test_the_tables_are_resolved_once():
    # `src/order_search/db.py` promises the names are resolved once per
    # process, so the property must hand back the same frozen object.
    db = build()
    assert db.tables is db.tables
    assert db.tables.products == '"t_item"."products"'
    db.close()


def test_database_is_a_context_manager():
    with build() as db:
        assert db.pool.closed is False
    assert db.pool.closed is True


def test_a_supplied_connection_is_used_and_not_committed():
    db, pooled = offline()
    supplied = FakeConnection()
    assert db.run("DELETE FROM x WHERE id = %s", (7,), conn=supplied) == 1
    assert supplied.sql() == ["DELETE FROM x WHERE id = %s"]
    assert supplied.commits == 0
    assert supplied.pooled_exits == 0
    assert pooled.statements == []


def test_a_supplied_connection_carries_a_whole_script():
    db, _ = offline()
    supplied = FakeConnection()
    db.execute_script("CREATE TABLE a (id int);\nSELECT 1;\n", conn=supplied)
    assert supplied.sql() == ["CREATE TABLE a (id int)", "SELECT 1"]
    assert supplied.commits == 0


def test_a_supplied_connection_carries_a_copy():
    db, _ = offline()
    supplied = FakeConnection()
    written = db.copy(
        '"t_item"."products_v1"',
        ("id", "name"),
        iter([(1, "a"), (2, "b")]),
        conn=supplied,
    )
    assert written == 2
    assert [row for copy in supplied.copies for row in copy.rows] == [
        (1, "a"),
        (2, "b"),
    ]
    assert db.copy('"t_item"."products_v1"', ("id",), [], conn=supplied) == 0


def test_without_a_connection_the_pool_is_used_and_committed():
    db, pooled = offline()
    db.run("DELETE FROM x")
    assert pooled.sql() == ["DELETE FROM x"]
    assert pooled.pooled_exits == 1


def test_a_transaction_yields_a_connection_and_commits_it():
    db, pooled = offline()
    with db.transaction() as conn:
        db.run("UPDATE a SET b = 1", conn=conn)
        assert pooled.commits == 0
    assert pooled.commits == 1
    assert pooled.pooled_exits == 1


def test_migrate_raises_when_the_migrations_directory_is_missing(
    tmp_path, monkeypatch
):
    db, _ = offline()
    monkeypatch.setattr("api.db.MIGRATIONS_DIR", tmp_path / "absent")
    with pytest.raises(FileNotFoundError, match="migrations"):
        db.migrate()


def test_migrate_raises_when_the_directory_holds_no_sql(tmp_path, monkeypatch):
    db, _ = offline()
    (tmp_path / "README.txt").write_text("nothing to apply", encoding="utf-8")
    monkeypatch.setattr("api.db.MIGRATIONS_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="no migration"):
        db.migrate()


def test_migrate_creates_the_ledger_before_it_reads_it():
    db, connection = offline()
    db.migrate()
    statements = connection.sql()
    created = next(
        i
        for i, s in enumerate(statements)
        if "schema_migrations" in s and s.lstrip().upper().startswith("CREATE")
    )
    read = next(
        i for i, s in enumerate(statements) if "schema_migrations" in s and "SELECT" in s
    )
    assert created < read


def test_migrate_applies_every_file_and_records_each_name():
    db, connection = offline()
    applied = db.migrate()
    assert applied == [
        "001_extensions.sql",
        "002_app.sql",
        "003_item.sql",
        "004_sales.sql",
        "005_views.sql",
        "006_grants.sql",
    ]
    recorded = connection.inserts_into("schema_migrations")
    assert [params[0] for params in recorded] == applied


def test_migrate_skips_a_file_the_ledger_already_records():
    db, connection = offline(rows=[{"name": "002_app.sql"}])
    applied = db.migrate()
    assert "002_app.sql" not in applied
    assert applied[0] == "001_extensions.sql"
    assert "app.users" not in " ".join(connection.sql())
    recorded = connection.inserts_into("schema_migrations")
    assert "002_app.sql" not in [params[0] for params in recorded]


def test_migrate_records_a_file_in_the_transaction_that_applies_it():
    db, connection = offline()
    db.migrate()
    # One commit per applied file, so a file and its ledger row land together.
    assert connection.commits == 6
