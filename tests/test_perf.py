import sqlite3
import time

import pytest

from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine
from conftest import DATA_FILE

P95_BUDGET_SECONDS = 0.2


@pytest.fixture(scope="module")
def engine():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    return SearchEngine(connection)


def measure(engine, query, repeats=20, **kwargs):
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        engine.search(query, **kwargs)
        timings.append(time.perf_counter() - started)
    timings.sort()
    index = max(0, int(round(0.95 * len(timings))) - 1)
    return timings[index]


def test_customer_lookup_is_fast(engine):
    assert measure(engine, "สุรชัย") < P95_BUDGET_SECONDS


def test_barcode_lookup_is_fast(engine):
    assert measure(engine, "8850250001234") < P95_BUDGET_SECONDS


def test_exact_product_is_fast(engine):
    assert measure(engine, "น้ำดื่มสิงห์ 600 มล. x 12") < P95_BUDGET_SECONDS


def test_short_query_is_fast(engine):
    assert measure(engine, "น้ำ") < P95_BUDGET_SECONDS


def test_fuzzy_fallback_is_fast(engine):
    assert measure(engine, "สึงห์") < P95_BUDGET_SECONDS


def test_suggest_is_fast(engine):
    started = time.perf_counter()
    for _ in range(20):
        engine.suggest("น้ำ")
    assert (time.perf_counter() - started) / 20 < P95_BUDGET_SECONDS


def test_search_does_not_write_to_the_database(engine):
    connection = engine.connection
    connection.execute("PRAGMA query_only = ON")
    engine.search("สุรชัย")
    engine.search("น้ำ")
