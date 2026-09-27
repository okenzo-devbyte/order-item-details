import re

from api.db import (
    MIGRATIONS_DIR,
    _rename_schemas,
    _schema_renames,
    split_statements,
)

TEST_RENAMES = _schema_renames("t_item", "t_sales", "t_app")


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


def test_rename_schemas_rewrites_every_default_schema():
    sql = (
        "CREATE SCHEMA IF NOT EXISTS app;\n"
        "CREATE TABLE IF NOT EXISTS item.products_v1 (id bigint);\n"
        "CREATE OR REPLACE VIEW sales.customers AS SELECT 1;\n"
    )
    renamed = _rename_schemas(sql, TEST_RENAMES)
    assert '"t_app"' in renamed
    assert '"t_item".products_v1' in renamed
    assert '"t_sales".customers' in renamed
    for default in ("app", "item", "sales"):
        assert not re.search(rf"\b{default}\b", renamed), default


def test_rename_schemas_leaves_a_longer_identifier_alone():
    # `item` is a prefix of a column and of a table name in every sales
    # migration, and `app` is a substring of nothing but is still worth
    # pinning: a rename that reached either would fail to run at all.
    sql = (
        "CREATE TABLE sales.orders_v1 (item_remark text, vip_remark text);\n"
        "CREATE TABLE sales.order_items_v1 (order_id bigint);\n"
        "CREATE INDEX idx_order_items_v1_product"
        " ON sales.order_items_v1 (product_id);\n"
    )
    assert _rename_schemas(sql, TEST_RENAMES) == (
        "CREATE TABLE \"t_sales\".orders_v1 (item_remark text, vip_remark text);\n"
        "CREATE TABLE \"t_sales\".order_items_v1 (order_id bigint);\n"
        "CREATE INDEX idx_order_items_v1_product ON \"t_sales\".order_items_v1"
        " (product_id);\n"
    )


def test_rename_schemas_rewrites_inside_a_string_literal():
    # The substitution cannot tell SQL from a literal, so a default name inside
    # one is rewritten as well. This is a known limitation of a text-level
    # rename, pinned here so a migration that relies on it is a deliberate
    # choice rather than an accident.
    sql = "COMMENT ON SCHEMA app IS 'restore app before the cutover';\n"
    assert _rename_schemas(sql, TEST_RENAMES) == (
        "COMMENT ON SCHEMA \"t_app\" IS 'restore \"t_app\" before the cutover';\n"
    )


def test_every_migration_file_renames_onto_the_test_schemas():
    # The files on disk name their schemas bare, so a rename that looked for
    # quoted names would quietly match nothing and migrate() would create the
    # production schemas under a test configuration.
    renamed_files = {
        path.name: _rename_schemas(path.read_text(encoding="utf-8"), TEST_RENAMES)
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
    }
    assert renamed_files
    for name, renamed in renamed_files.items():
        for default in ("app", "item", "sales"):
            assert not re.search(rf"\b{default}\b", renamed), f"{name}: {default}"
    for configured in ("t_app", "t_item", "t_sales"):
        matches = [n for n, s in renamed_files.items() if re.search(rf"\b{configured}\b", s)]
        assert matches, f"no migration creates {configured}"


def test_no_migration_names_a_column_after_a_reserved_word():
    # PostgreSQL only accepts IDENT, unreserved or col_name keywords as a
    # column name, so `window` is a syntax error and stops the whole file.
    # `key`, `role` and `version` are unreserved and are fine as they are.
    reserved = ["window", "order", "group", "user", "table", "select"]
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for word in reserved:
            assert not re.search(rf"\b{word}\b\s+\w", sql), f"{path.name}: {word}"


def test_the_rate_limit_bucket_uses_a_usable_column_name():
    sql = (MIGRATIONS_DIR / "002_app.sql").read_text(encoding="utf-8")
    assert "window_start" in sql
    assert "PRIMARY KEY (key, window_start)" in sql


def test_the_trigram_extension_is_pinned_to_a_schema():
    # Without an explicit schema the extension lands in the first writable
    # schema in search_path, and `gin_trgm_ops` then resolves through
    # search_path too. The moment anything pins search_path to the three data
    # schemas, the operator classes stop resolving and 003 fails to run.
    sql = (MIGRATIONS_DIR / "001_extensions.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;" in sql


def test_the_current_version_index_is_partial_and_unique():
    # A unique index on a boolean where the predicate is `is_current` is how
    # "at most one current version" is written: every indexed row has the key
    # `true`, so the second one collides. See the comment in the migration.
    sql = (MIGRATIONS_DIR / "002_app.sql").read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_current" in sql
    assert "ON app.data_versions(is_current) WHERE is_current;" in sql
