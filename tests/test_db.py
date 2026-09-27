from api.db import Database
from order_search.db import Reader

UNREACHABLE_DSN = "postgresql://u:p@localhost:1/none"


def build() -> Database:
    """A Database that has a pool but has never opened a socket.

    Port 1 refuses instantly and `min_size=0` means the pool has no connection
    to open, so nothing here needs a server.
    """
    return Database(UNREACHABLE_DSN, "t_item", "t_sales", "t_app")


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
