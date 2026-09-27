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