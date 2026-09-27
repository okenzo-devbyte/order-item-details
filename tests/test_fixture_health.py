from api.db import Database


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
