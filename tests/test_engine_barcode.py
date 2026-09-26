from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


class TestBarcodeMode:
    def test_known_barcode_finds_its_product(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["detected"] == "barcode"
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_barcode_result_includes_the_customer_list(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["products"][0]["customer_count"] == 20

    def test_barcode_with_dashes(self):
        engine = make_engine()
        result = engine.search("8850-250001-234")
        assert result["products"]

    def test_short_barcode_cell_value_is_searchable(self):
        # '21464546' appears as the first half of a multi-barcode cell
        engine = make_engine()
        result = engine.search("21464546")
        assert result["products"]

    def test_unknown_barcode_returns_nothing(self):
        engine = make_engine()
        result = engine.search("0000000000000")
        assert result["products"] == []

    def test_barcode_never_searches_customer_names(self):
        engine = make_engine()
        result = engine.search("8850250001234")
        assert result["customers"] == []
