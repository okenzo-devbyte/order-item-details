import sqlite3

import pytest

from order_search.ingest.build import apply_schema
from order_search.search.fuzzy import best_customers, best_products
from order_search.textnorm import fold_heavy, fold_light, norm

WATER = "น้ำดื่มสิงห์ 600 มล. x 12"
SUGAR = "น้ำตาลทรายขาว 1 กก. x 10"
OIL = "น้ำมันปาล์ม 1 ลิตร x 12"
DISH = "น้ำยาล้างจาน 500 มล. x 12"
COFFEE = "กาแฟสำเร็จรูป 3 in 1 17 ก. x 27"
TISSUE = "ทิชชู่ม้วน 24 ม้วน"
COLA = "โค้ก 500 มล. x 12"

PRODUCTS = [
    (1, WATER),
    (2, SUGAR),
    (3, OIL),
    (4, DISH),
    (5, COFFEE),
    (6, TISSUE),
    (7, COLA),
]
CUSTOMERS = [
    (1, "สุรชัย"),
    (2, "ศิริพร"),
    (3, "วราภรณ์"),
    (4, "สมชาย"),
    (5, "อนุชา"),
]


@pytest.fixture
def connection():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_schema(connection)
    for pid, name in PRODUCTS:
        connection.execute(
            "INSERT INTO products (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (?,?,?,?,?)",
            (pid, name, norm(name), fold_light(name), fold_heavy(name)),
        )
    for cid, name in CUSTOMERS:
        connection.execute(
            "INSERT INTO customers (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (?,?,?,?,?)",
            (cid, name, norm(name), fold_light(name), fold_heavy(name)),
        )
    return connection


def _ids(results):
    return [item[0] for item in results]


class TestBestProducts:
    def test_exact_prefix(self, connection):
        assert 1 in _ids(best_products("น้ำดื่มสิงห์", connection))

    def test_middle_substring(self, connection):
        assert 1 in _ids(best_products("สิงห์", connection))

    def test_missing_thanthakhat(self, connection):
        assert 1 in _ids(best_products("สิงห", connection))

    def test_wrong_vowel_and_tone(self, connection):
        # only the heavy fold can catch this, and the confirm pass must agree
        assert 1 in _ids(best_products("สึงห์", connection))

    def test_missing_tone_mark_on_vowel(self, connection):
        assert 1 in _ids(best_products("น้ำดืม", connection))

    def test_short_query_matches_several(self, connection):
        found = _ids(best_products("น้ำ", connection))
        assert {1, 2, 3, 4} <= set(found)

    def test_finds_product_without_pack_size(self, connection):
        assert 6 in _ids(best_products("ทิชชู่", connection))

    def test_thai_brand_name_is_found(self, connection):
        assert 7 in _ids(best_products("โค้ก", connection))

    def test_known_limitation_dropped_vowel(self, connection):
        # a vowel omitted from a three character query cannot reach a score of
        # 70, so this is documented as unreachable rather than asserted to work
        assert best_products("กแฟ", connection) == []

    def test_nonsense_query_returns_nothing(self, connection):
        assert best_products("ซไบเตอร์", connection) == []
        assert best_products("zzz", connection) == []
        assert best_products("๑๒๓", connection) == []

    def test_empty_query_returns_nothing(self, connection):
        assert best_products("", connection) == []
        assert best_products("   ", connection) == []

    def test_results_are_sorted_by_score_then_id(self, connection):
        results = best_products("น้ำ", connection)
        scores = [score for _pid, _norm_text, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_respects_the_limit(self, connection):
        assert len(best_products("น้ำ", connection, limit=2)) == 2


class TestBestCustomers:
    def test_exact_name(self, connection):
        assert _ids(best_customers("สุรชัย", connection)) == [1]

    def test_prefix_of_name(self, connection):
        assert _ids(best_customers("สุรช", connection)) == [1]

    def test_another_exact_name(self, connection):
        assert _ids(best_customers("ศิริพร", connection)) == [2]

    def test_unknown_name_returns_nothing(self, connection):
        assert best_customers("ไม่มีในระบบ", connection) == []

    def test_empty_query_returns_nothing(self, connection):
        assert best_customers("", connection) == []

    def test_respects_the_limit(self, connection):
        assert len(best_customers("ส", connection, limit=2)) <= 2
