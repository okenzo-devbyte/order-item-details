import sqlite3

import pytest

from api.crypto import DecryptionError, seal
from api.snapshot import SnapshotStore
from order_search.ingest.build import build_database
from order_search.ingest.excel_reader import read_order_rows
from order_search.search.engine import SearchEngine

from conftest import DATA_FILE

RAW_KEY = bytes(range(32))
KEY_ID = "v1"


def make_plaintext_snapshot() -> bytes:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    blob = connection.serialize()
    connection.close()
    return blob


def make_store(tmp_path, plaintext):
    path = tmp_path / "snapshot.enc"
    path.write_bytes(seal(plaintext, RAW_KEY, KEY_ID))
    store = SnapshotStore({KEY_ID: RAW_KEY}, KEY_ID)
    store.load_file(path)
    return store


def _damaged_snapshot() -> bytes:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    build_database(read_order_rows(DATA_FILE), connection)
    connection.execute("DELETE FROM products_fts_data")
    connection.execute("DELETE FROM products_fts_idx")
    connection.execute("DELETE FROM products_fts_docsize")
    blob = connection.serialize()
    connection.close()
    return blob


def test_rebuild_recovers_a_damaged_fts_index(tmp_path):
    store = make_store(tmp_path, _damaged_snapshot())
    assert len(store.search("น้ำ")["products"]) == 4
    assert store.search("สิงห์")["products"]


def test_without_rebuild_a_damaged_index_stays_broken():
    bare = sqlite3.connect(":memory:")
    bare.row_factory = sqlite3.Row
    bare.deserialize(_damaged_snapshot())
    hits = 0
    try:
        hits = bare.execute(
            "SELECT count(*) AS n FROM products_fts WHERE name_norm MATCH ?",
            ("น้ำ",),
        ).fetchone()["n"]
    except sqlite3.DatabaseError:
        hits = 0
    bare.close()
    assert hits == 0


def _reference_connection(plaintext):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.deserialize(plaintext)
    connection.execute("INSERT INTO products_fts(products_fts) VALUES('rebuild')")
    connection.execute("PRAGMA query_only=ON")
    return connection


def test_customer_search_matches_direct_engine(tmp_path):
    plaintext = make_plaintext_snapshot()
    store = make_store(tmp_path, plaintext)
    through_store = store.search("สุรชัย")
    reference = SearchEngine(_reference_connection(plaintext)).search("สุรชัย")
    assert through_store["customers"][0]["name"] == "สุรชัย"
    assert (
        through_store["customers"][0]["order_count"]
        == reference["customers"][0]["order_count"]
    )


def test_barcode_search_works_after_load(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    result = store.search("8850250001234")
    assert result["products"]
    assert result["products"][0]["name"].startswith("น้ำดื่มสิงห์")


def test_short_thai_query_works_after_load(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    assert len(store.search("น้ำ")["products"]) == 4


def test_connection_is_read_only(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    with pytest.raises(sqlite3.OperationalError):
        store.connection.execute("DELETE FROM products")


def test_customer_history_and_product_customers(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    history = store.customer_history(1)
    assert history and history[0]["products"]
    buyers = store.product_customers(1)
    assert buyers and buyers[0]["customers"]


def test_facets_and_counts(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    facets = store.facets()
    assert len(facets["store_code"]) == 15
    assert "Standard delivery" in facets["order_type"]
    counts = store.counts()
    assert counts["products"] == 15
    assert counts["customers"] == 20


def test_replace_with_bytes_swaps_data(tmp_path):
    store = make_store(tmp_path, make_plaintext_snapshot())
    empty = sqlite3.connect(":memory:", isolation_level=None)
    empty.row_factory = sqlite3.Row
    empty.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT)")
    empty.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    empty.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")
    empty.execute("CREATE TABLE order_items (order_id INTEGER, product_id INTEGER)")
    empty.execute("CREATE TABLE product_barcodes (product_id INTEGER, barcode TEXT)")
    empty.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    empty.execute(
        "CREATE VIRTUAL TABLE products_fts USING fts5("
        "name_norm, name_fold_light, product_id UNINDEXED, tokenize='trigram')"
    )
    empty.execute("INSERT INTO products (id, name) VALUES (1, 'ของใหม่')")
    empty.execute(
        "INSERT INTO products_fts (name_norm, name_fold_light, product_id)"
        " VALUES ('ของใหม่', 'ของใหม่', 1)"
    )
    store.replace_with_bytes(empty.serialize())
    empty.close()
    row = store.connection.execute("SELECT name FROM products").fetchone()
    assert row["name"] == "ของใหม่"


def test_wrong_key_fails_to_load(tmp_path):
    path = tmp_path / "snapshot.enc"
    path.write_bytes(seal(make_plaintext_snapshot(), RAW_KEY, KEY_ID))
    store = SnapshotStore({"v1": bytes(32)}, KEY_ID)
    with pytest.raises(DecryptionError):
        store.load_file(path)
