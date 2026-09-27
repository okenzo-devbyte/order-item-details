from __future__ import annotations

from order_search.ingest.excel_reader import read_order_rows
from order_search.ingest.transform import transform
from conftest import DATA_FILE


def test_transform_assigns_dense_ids_in_first_seen_order():
    rows = read_order_rows(DATA_FILE)
    data = transform(rows)
    assert data.report.products == 15
    assert data.report.customers == 20
    assert [row[0] for row in data.products] == list(range(1, 16))
    assert [row[0] for row in data.customers] == list(range(1, 21))
    assert len(data.orders) == 1000
    assert len(data.order_items) == 1000
    assert len(data.barcodes) == 127


def test_transform_normalises_every_text_column():
    data = transform(read_order_rows(DATA_FILE))
    first = data.products[0]
    assert first[1] == first[2] or first[2].startswith(first[1][:2])
    assert " " not in first[2]
    assert data.report.missing_pack_size_products == 1