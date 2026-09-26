import sqlite3

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from conftest import DATA_FILE


def fresh_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def scalar(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()[0]


class TestExcelReader:
    def test_reads_one_thousand_rows(self):
        rows = read_order_rows(DATA_FILE)
        assert len(rows) == 1000

    def test_keys_rows_by_header_name(self):
        row = read_order_rows(DATA_FILE)[0]
        for key in [
            "Store Code",
            "Order Type",
            "Product Name",
            "NO.",
            "Dept",
            "Class",
            "Subclass",
            "Bar_Code",
            "Customer Name",
            "Item Remark",
            "VIP Customer Remarks",
            "VIP Customer Groups",
            "Original Expected Date",
        ]:
            assert key in row

    def test_barcode_cell_becomes_a_list(self):
        rows = read_order_rows(DATA_FILE)
        multi = [r for r in rows if len(r["Bar_Code"]) > 1]
        assert len(multi) == 148
        for row in multi:
            assert isinstance(row["Bar_Code"], list)
            assert all(isinstance(b, str) for b in row["Bar_Code"])

    def test_numeric_columns_become_ints(self):
        row = read_order_rows(DATA_FILE)[0]
        assert isinstance(row["Dept"], int)
        assert isinstance(row["Class"], int)
        assert isinstance(row["Subclass"], int)
        assert isinstance(row["NO."], int)

    def test_date_column_becomes_two_dates(self):
        row = read_order_rows(DATA_FILE)[0]
        assert row["date_from"].isoformat() == "2026-09-26"
        assert row["date_to"].isoformat() == "2026-09-26"

    def test_blank_cells_become_empty_string(self):
        rows = read_order_rows(DATA_FILE)
        blanks = [r for r in rows if r["Item Remark"] == ""]
        assert len(blanks) == 386


class TestBuildDatabase:
    def test_counts_match_the_verified_ground_truth(self):
        connection = fresh_connection()
        report = build_database(read_order_rows(DATA_FILE), connection)
        assert report.rows_read == 1000
        assert report.rows_imported == 1000
        assert report.rows_skipped == 0
        assert report.products == 15
        assert report.customers == 20
        assert report.orders == 1000
        assert report.barcodes == 127

    def test_stores_every_order_row(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM orders") == 1000
        assert scalar(connection, "SELECT COUNT(*) FROM order_items") == 1000

    def test_stores_one_row_per_distinct_product_and_customer(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM products") == 15
        assert scalar(connection, "SELECT COUNT(*) FROM customers") == 20

    def test_barcode_count_drops_after_splitting(self):
        # 139 distinct raw strings collapse to 127 distinct barcodes
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM product_barcodes") == 127
        assert scalar(
            connection, "SELECT COUNT(DISTINCT barcode) FROM product_barcodes"
        ) == 127

    def test_known_barcode_maps_to_known_product(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        row = connection.execute(
            "SELECT p.name AS name FROM product_barcodes b"
            " JOIN products p ON p.id = b.product_id"
            " WHERE b.barcode = '8850250001234'"
        ).fetchone()
        assert row["name"] == "น้ำดื่มสิงห์ 600 มล. x 12"

    def test_pack_size_parsed_and_null_when_absent(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        named = connection.execute(
            "SELECT pack_size FROM products WHERE name = ?",
            ("น้ำดื่มสิงห์ 600 มล. x 12",),
        ).fetchone()
        assert named["pack_size"] == 12
        absent = connection.execute(
            "SELECT pack_size, unit FROM products WHERE name = ?",
            ("ทิชชู่ม้วน 24 ม้วน",),
        ).fetchone()
        assert absent["pack_size"] is None

    def test_unit_is_never_guessed(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM products WHERE unit IS NOT NULL") == 0

    def test_normalized_columns_are_populated(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        row = connection.execute(
            "SELECT name_norm, name_fold_light, name_fold_heavy FROM products"
            " WHERE name = ?",
            ("น้ำดื่มสิงห์ 600 มล. x 12",),
        ).fetchone()
        assert row["name_norm"] == "น้ำดื่มสิงห์600มลx12"
        assert row["name_fold_light"] == "นำดืมสิงห600มลx12"
        assert row["name_fold_heavy"] == "นาดมสงห600มลx12"
        # The three levels must be genuinely different views, not copies. An
        # earlier draft of this plan had light and heavy identical here, which
        # would have made the second level pointless.
        assert row["name_fold_light"] != row["name_fold_heavy"]

    def test_vip_tier_stays_on_the_order_line(self):
        # สุรชัย carries all four tiers across their own orders
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        tiers = connection.execute(
            "SELECT DISTINCT vip_group AS v FROM orders o JOIN customers c"
            " ON c.id = o.customer_id WHERE c.name = ? AND o.vip_group <> ''",
            ("สุรชัย",),
        ).fetchall()
        assert sorted(row["v"] for row in tiers) == [
            "Gold",
            "Platinum",
            "VIP",
            "Wholesale VIP",
        ]

    def test_customers_table_has_no_vip_columns(self):
        # guards against someone 'fixing' the data by lifting VIP to customer level
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(customers)")
        }
        assert "vip_group" not in columns
        assert "vip_remark" not in columns

    def test_fts_index_is_searchable(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        found = connection.execute(
            "SELECT product_id FROM products_fts WHERE name_norm MATCH ?",
            ('"น้ำดื่ม"',),
        ).fetchall()
        assert len(found) == 1

    def test_is_idempotent(self):
        rows = read_order_rows(DATA_FILE)
        first = fresh_connection()
        second = fresh_connection()
        report_a = build_database(rows, first)
        report_b = build_database(rows, second)
        assert report_a.summary() == report_b.summary()
        assert scalar(first, "SELECT COUNT(*) FROM orders") == scalar(
            second, "SELECT COUNT(*) FROM orders"
        )
        assert scalar(first, "SELECT COUNT(*) FROM orders") == 1000

    def test_rerunning_on_the_same_connection_replaces_data(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        build_database(read_order_rows(DATA_FILE), connection)
        assert scalar(connection, "SELECT COUNT(*) FROM orders") == 1000
        assert scalar(connection, "SELECT COUNT(*) FROM products") == 15

    def test_skips_incomplete_rows_and_reports_them(self):
        rows = read_order_rows(DATA_FILE)[:5]
        rows[2]["Product Name"] = ""
        connection = fresh_connection()
        report = build_database(rows, connection)
        assert report.rows_read == 5
        assert report.rows_imported == 4
        assert report.rows_skipped == 1
        assert report.warnings

    def test_records_provenance_in_meta(self):
        connection = fresh_connection()
        build_database(read_order_rows(DATA_FILE), connection)
        stored = dict(
            connection.execute("SELECT key, value FROM meta").fetchall()
        )
        assert stored["rows_imported"] == "1000"
        assert stored["rows_skipped"] == "0"
