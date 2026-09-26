import sqlite3

import pytest

from order_search.ingest.build import apply_schema
from order_search.ingest.schema_path import SCHEMA_PATH


def fresh_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def table_names(connection):
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
    ).fetchall()
    return {row["name"] for row in rows}


class TestSchema:
    def test_schema_file_exists(self):
        assert SCHEMA_PATH.is_file()

    def test_creates_every_expected_table(self):
        connection = fresh_connection()
        apply_schema(connection)
        names = table_names(connection)
        for expected in [
            "products",
            "product_barcodes",
            "customers",
            "orders",
            "order_items",
            "products_fts",
            "meta",
        ]:
            assert expected in names, f"missing table {expected}"

    def test_products_has_all_search_columns(self):
        connection = fresh_connection()
        apply_schema(connection)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(products)")
        }
        for expected in [
            "id",
            "name",
            "name_norm",
            "name_fold_light",
            "name_fold_heavy",
            "dept",
            "class_code",
            "subclass_code",
            "pack_size",
            "unit",
        ]:
            assert expected in columns, f"missing column products.{expected}"

    def test_unit_defaults_to_null_not_a_guess(self):
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (1, 'x', 'x', 'x', 'x')"
        )
        row = connection.execute("SELECT unit FROM products WHERE id = 1").fetchone()
        assert row["unit"] is None

    def test_fts_table_uses_trigram(self):
        connection = fresh_connection()
        apply_schema(connection)
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'products_fts'"
        ).fetchone()["sql"]
        assert "trigram" in sql

    def test_fts_table_accepts_a_thai_substring_query(self):
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute(
            "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
            " VALUES ('น้ำดื่มสิงห์600มลx12', 'นำดืมสิงห600มลx12', 1)"
        )
        found = connection.execute(
            "SELECT product_id FROM products_fts WHERE name_norm MATCH ?",
            ('"น้ำดื่ม"',),
        ).fetchall()
        assert [row["product_id"] for row in found] == [1]

    def test_barcode_index_is_not_unique(self):
        # a barcode may legitimately appear against two products in real data,
        # so the index must not be UNIQUE or the import would crash
        connection = fresh_connection()
        apply_schema(connection)
        connection.execute(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (1, 'a', 'a', 'a', 'a')"
        )
        connection.execute(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (2, 'b', 'b', 'b', 'b')"
        )
        connection.execute(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (1, '111')"
        )
        connection.execute(
            "INSERT INTO product_barcodes (product_id, barcode) VALUES (2, '111')"
        )
        rows = connection.execute(
            "SELECT product_id FROM product_barcodes WHERE barcode = '111'"
            " ORDER BY product_id"
        ).fetchall()
        assert [row["product_id"] for row in rows] == [1, 2]

    @pytest.mark.parametrize(
        "column", ["name_norm", "name_fold_light", "name_fold_heavy"]
    )
    def test_normalized_columns_reject_missing_values(self, column):
        # A product with no normalized text could never be found by search, so
        # the columns must fail loudly rather than defaulting to empty strings.
        connection = fresh_connection()
        apply_schema(connection)
        values = {"name_norm": "x", "name_fold_light": "x", "name_fold_heavy": "x"}
        values[column] = None
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO products (id, name, name_norm, name_fold_light,"
                " name_fold_heavy) VALUES (1, 'x', :name_norm, :name_fold_light,"
                " :name_fold_heavy)",
                values,
            )

    def test_normalized_columns_have_no_defaults(self):
        # An explicit NULL is rejected even when a DEFAULT is present, so the
        # test above alone would not catch someone re-adding DEFAULT ''.
        # Omitting the columns is the case that distinguishes bare NOT NULL
        # from NOT NULL DEFAULT '': the latter would silently store ''.
        connection = fresh_connection()
        apply_schema(connection)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO products (id, name) VALUES (1, 'a')"
            )
