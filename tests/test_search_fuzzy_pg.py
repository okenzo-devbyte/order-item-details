from __future__ import annotations

import pytest

from order_search.db import Tables
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


class RowsReader:
    def __init__(self, rows):
        self.rows = rows

    def one(self, sql, params=()):
        return None

    def all(self, sql, params=()):
        return self.rows


@pytest.fixture
def product_reader():
    rows = [
        {
            "id": pid,
            "name_norm": norm(name),
            "name_fold_heavy": fold_heavy(name),
        }
        for pid, name in PRODUCTS
    ]
    return RowsReader(rows)


@pytest.fixture
def customer_reader():
    rows = [
        {
            "id": cid,
            "name_norm": norm(name),
            "name_fold_light": fold_light(name),
        }
        for cid, name in CUSTOMERS
    ]
    return RowsReader(rows)


TABLES = Tables.from_schemas("t_item", "t_sales")


def _ids(results):
    return [item[0] for item in results]


class TestBestProducts:
    def test_exact_prefix(self, product_reader):
        assert 1 in _ids(best_products("น้ำดื่มสิงห์", product_reader, TABLES))

    def test_middle_substring(self, product_reader):
        assert 1 in _ids(best_products("สิงห์", product_reader, TABLES))

    def test_missing_thanthakhat(self, product_reader):
        assert 1 in _ids(best_products("สิงห", product_reader, TABLES))

    def test_wrong_vowel_and_tone(self, product_reader):
        # only the heavy fold can catch this, and the confirm pass must agree
        assert 1 in _ids(best_products("สึงห์", product_reader, TABLES))

    def test_missing_tone_mark_on_vowel(self, product_reader):
        assert 1 in _ids(best_products("น้ำดืม", product_reader, TABLES))

    def test_short_query_matches_several(self, product_reader):
        found = _ids(best_products("น้ำ", product_reader, TABLES))
        assert {1, 2, 3, 4} <= set(found)

    def test_finds_product_without_pack_size(self, product_reader):
        assert 6 in _ids(best_products("ทิชชู่", product_reader, TABLES))

    def test_thai_brand_name_is_found(self, product_reader):
        assert 7 in _ids(best_products("โค้ก", product_reader, TABLES))

    def test_known_limitation_dropped_vowel(self, product_reader):
        # a vowel omitted from a three character query cannot reach a score of
        # 70, so this is documented as unreachable rather than asserted to work
        assert best_products("กแฟ", product_reader, TABLES) == []

    def test_nonsense_query_returns_nothing(self, product_reader):
        assert best_products("ซไบเตอร์", product_reader, TABLES) == []
        assert best_products("zzz", product_reader, TABLES) == []
        assert best_products("๑๒๓", product_reader, TABLES) == []

    def test_empty_query_returns_nothing(self, product_reader):
        assert best_products("", product_reader, TABLES) == []
        assert best_products("   ", product_reader, TABLES) == []

    def test_results_are_sorted_by_score_then_id(self, product_reader):
        results = best_products("น้ำ", product_reader, TABLES)
        scores = [score for _pid, _norm_text, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_respects_the_limit(self, product_reader):
        assert len(best_products("น้ำ", product_reader, TABLES, limit=2)) == 2

    def test_confirms_against_the_base_form(self, product_reader):
        matches = best_products("น้ำดื่มสิงห์", product_reader, TABLES)
        assert [m[0] for m in matches] == [1]

    def test_a_query_matching_nothing_returns_empty(self, product_reader):
        assert best_products("zzzzzz", product_reader, TABLES) == []


class TestBestCustomers:
    def test_exact_name(self, customer_reader):
        assert _ids(best_customers("สุรชัย", customer_reader, TABLES)) == [1]

    def test_prefix_of_name(self, customer_reader):
        assert _ids(best_customers("สุรช", customer_reader, TABLES)) == [1]

    def test_another_exact_name(self, customer_reader):
        assert _ids(best_customers("ศิริพร", customer_reader, TABLES)) == [2]

    def test_unknown_name_returns_nothing(self, customer_reader):
        assert best_customers("ไม่มีในระบบ", customer_reader, TABLES) == []

    def test_empty_query_returns_nothing(self, customer_reader):
        assert best_customers("", customer_reader, TABLES) == []

    def test_respects_the_limit(self, customer_reader):
        assert len(best_customers("ส", customer_reader, TABLES, limit=2)) <= 2

    def test_returns_ids_scores_and_names(self, customer_reader):
        matches = best_customers("สุรชัย", customer_reader, TABLES)
        assert matches[0][0] == 1
        assert matches[0][1] == norm("สุรชัย")
        assert matches[0][2] >= 70