from __future__ import annotations

import pytest

from order_search.db import Tables
from order_search.search.detect import (
    BARCODE,
    BOTH,
    CUSTOMER,
    NONE,
    PRODUCT,
    detect,
)
from order_search.search.filters import Filters, order_filter_sql


class RecordingReader:
    """Fakes the Reader and records every query it is asked to run."""

    def __init__(self, tables, one=None, all_rows=None):
        self.tables = tables
        self._one = one
        self._all = all_rows or []
        self.seen = []

    def one(self, sql, params=()):
        self.seen.append((sql, params))
        return self._one

    def all(self, sql, params=()):
        self.seen.append((sql, params))
        return self._all


@pytest.fixture
def reader():
    return RecordingReader(Tables.from_schemas("t_item", "t_sales"))


def test_an_exact_customer_name_that_also_prefixes_products_is_both(reader):
    reader._one = {"id": 7}
    reader._all = [{"id": 3}, {"id": 4}]
    found = detect("กาแฟ", reader, reader.tables)
    assert found.kind == BOTH
    assert found.customer_id == 7
    assert found.product_ids == (3, 4)


def test_the_customer_query_is_schema_qualified_and_uses_percent(reader):
    reader._one = {"id": 7}
    detect("สุรชัย", reader, reader.tables)
    sql, params = reader.seen[0]
    assert 't_sales"."customers' in sql
    assert "name_norm = %s" in sql
    assert params == ("สุรชัย",)


def test_a_both_query_probes_products_with_an_escaped_like(reader):
    reader._one = {"id": 7}
    reader._all = [{"id": 3}, {"id": 4}]
    detect("กาแฟ", reader, reader.tables)
    sql, params = reader.seen[1]
    assert 't_item"."products' in sql
    assert "LIKE %s ESCAPE" in sql
    assert params == ("กาแฟ%",)


def test_an_exact_customer_name_alone_is_a_customer(reader):
    reader._one = {"id": 7}
    reader._all = []
    assert detect("สุรชัย", reader, reader.tables).kind == CUSTOMER


def test_customer_name_with_spaces_is_still_a_customer(reader):
    reader._one = {"id": 7}
    reader._all = []
    assert detect("  สุรชัย  ", reader, reader.tables).kind == CUSTOMER


def test_empty_query_is_none(reader):
    assert detect("   ", reader, reader.tables).kind == NONE


def test_a_three_character_query_is_product_text(reader):
    reader._one = None
    assert detect("น้ำดื่ม", reader, reader.tables).kind == PRODUCT


def test_barcode_is_recognised(reader):
    result = detect("8850250001234", reader, reader.tables)
    assert result.kind == BARCODE
    assert result.normalized_query == "8850250001234"


def test_barcode_with_dashes(reader):
    assert detect("8850-250001-234", reader, reader.tables).kind == BARCODE


def test_short_query_is_flagged_too_short(reader):
    reader._one = None
    result = detect("น้", reader, reader.tables)
    assert result.too_short is True
    assert result.kind == PRODUCT


def test_unknown_text_is_still_a_product_query(reader):
    reader._one = None
    assert detect("ซไบเตอร์", reader, reader.tables).kind == PRODUCT


def test_normalized_query_is_exposed(reader):
    reader._one = None
    result = detect("น้ำดื่มสิงห์ 600 มล. x 12", reader, reader.tables)
    assert result.kind == PRODUCT
    assert result.normalized_query == "น้ำดื่มสิงห์600มลx12"


def test_filter_sql_uses_percent_placeholders():
    where, params = order_filter_sql(Filters(store_code=("101", "102")))
    assert where == "o.store_code IN (%s,%s)"
    assert params == ["101", "102"]


def test_date_filters_still_test_for_overlap():
    where, params = order_filter_sql(
        Filters(date_from="2026-01-01", date_to="2026-02-01")
    )
    assert where == (
        "(o.date_from <= %s AND o.date_to >= %s AND o.date_from IS NOT NULL)"
    )
    assert params == ["2026-02-01", "2026-01-01"]


def test_a_non_iso_date_is_rejected_loudly():
    with pytest.raises(ValueError):
        Filters(date_from="26-Sep-2026")
