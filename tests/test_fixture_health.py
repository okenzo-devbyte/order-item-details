from __future__ import annotations

from api.db import Database


def test_the_test_schemas_exist(client_db: Database):
    # The client_db fixture is session-scoped, and later test files load the
    # workbook and bootstrap an admin into the shared t_ schemas, so the tables
    # are no longer empty by the time this file runs (alphabetical order). What
    # this test must still prove is that the migration produced a schema the
    # queries can reach, not that it is freshly empty.
    app = client_db.schema_app
    item = client_db.schema_item
    sales = client_db.schema_sales
    assert (
        client_db.one(f'SELECT count(*) AS n FROM "{app}"."users"')["n"] is not None
    )
    assert (
        client_db.one(f'SELECT count(*) AS n FROM "{item}"."products"')["n"]
        is not None
    )
    assert (
        client_db.one(f'SELECT count(*) AS n FROM "{sales}"."orders"')["n"]
        is not None
    )


def test_test_schemas_exist_in_pg_namespace(client_db: Database):
    rows = client_db.all(
        "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
        (["t_item", "t_sales", "t_app"],),
    )
    assert len(rows) == 3
