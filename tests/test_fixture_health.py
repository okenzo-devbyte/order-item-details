from __future__ import annotations

from api.db import Database


def test_the_test_schemas_exist(client_db: Database):
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
