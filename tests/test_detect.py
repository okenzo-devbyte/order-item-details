from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.detect import (
    BARCODE,
    BOTH,
    CUSTOMER,
    NONE,
    PRODUCT,
    detect,
)
from conftest import DATA_FILE


def make_engine():
    import sqlite3

    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return connection


def test_blank_query():
    connection = make_engine()
    assert detect("   ", connection).kind == NONE
    assert detect("", connection).kind == NONE


def test_barcode_is_recognised():
    connection = make_engine()
    result = detect("8850250001234", connection)
    assert result.kind == BARCODE
    assert result.normalized_query == "8850250001234"


def test_barcode_with_dashes():
    connection = make_engine()
    assert detect("8850-250001-234", connection).kind == BARCODE


def test_exact_customer_name():
    connection = make_engine()
    result = detect("สุรชัย", connection)
    assert result.kind == CUSTOMER
    assert result.customer_id is not None


def test_customer_name_with_spaces_is_still_a_customer():
    connection = make_engine()
    assert detect("  สุรชัย  ", connection).kind == CUSTOMER


def test_exact_product_name():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์ 600 มล. x 12", connection)
    assert result.kind == PRODUCT
    # product_ids stays empty here; the engine resolves product matches via
    # FTS. Only the BOTH case carries IDs, because only it matched exactly.


def test_partial_product_text_is_a_product_query():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์", connection)
    assert result.kind == PRODUCT
    assert not result.too_short


def test_short_query_is_flagged_too_short():
    connection = make_engine()
    result = detect("น้", connection)
    assert result.too_short is True
    assert result.kind == PRODUCT


def test_query_matching_both_a_customer_and_a_product():
    connection = make_engine()
    connection.execute(
        "INSERT INTO customers (id, name, name_norm, name_fold_light, name_fold_heavy)"
        " VALUES (999, 'น้ำดื่มสิงห์', 'น้ำดื่มสิงห์', 'นาดมสงห', 'นาดมสงห')"
    )
    result = detect("น้ำดื่มสิงห์", connection)
    assert result.kind == BOTH
    assert result.customer_id == 999
    assert result.product_ids


def test_unknown_text_is_still_a_product_query():
    connection = make_engine()
    assert detect("ซไบเตอร์", connection).kind == PRODUCT


def test_normalized_query_is_exposed():
    connection = make_engine()
    result = detect("น้ำดื่มสิงห์ 600 มล. x 12", connection)
    assert result.normalized_query == "น้ำดื่มสิงห์600มลx12"
