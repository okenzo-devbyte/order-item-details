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


class TestProductMode:
    def test_full_product_name(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["mode"] == "product"
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_every_customer_bought_water(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["customer_count"] == 20

    def test_order_line_count_for_water(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["order_count"] == 86

    def test_customer_breakdown_is_sorted_by_order_count(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        counts = [
            c["order_count"] for c in result["products"][0]["customers"]
        ]
        assert counts == sorted(counts, reverse=True)
        assert result["products"][0]["customers"][0]["name"] == "เอกชัย"

    def test_short_query_matches_four_products(self):
        engine = make_engine()
        result = engine.search("น้ำ")
        assert result["products"]
        assert len(result["products"]) == 4

    def test_middle_substring_finds_the_product(self):
        engine = make_engine()
        result = engine.search("สิงห์")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_missing_thanthakhat_still_finds_it(self):
        engine = make_engine()
        result = engine.search("สิงห")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_wrong_vowel_and_tone_still_finds_it(self):
        engine = make_engine()
        result = engine.search("สึงห์")
        assert [p["name"] for p in result["products"]] == [
            "น้ำดื่มสิงห์ 600 มล. x 12"
        ]

    def test_product_without_pack_size_is_findable(self):
        engine = make_engine()
        result = engine.search("ทิชชู่")
        product = result["products"][0]
        assert product["name"] == "ทิชชู่ม้วน 24 ม้วน"
        assert product["pack_size"] is None

    def test_product_carries_its_hierarchy(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        product = result["products"][0]
        assert product["dept"] == 1
        assert product["class_code"] == 101
        assert product["subclass_code"] == 5
        assert product["pack_size"] == 12

    def test_nonsense_query_returns_nothing(self):
        engine = make_engine()
        result = engine.search("ซไบเตอร์")
        assert result["products"] == []
        assert result["customers"] == []

    def test_blank_query_is_reported_as_none(self):
        engine = make_engine()
        result = engine.search("   ")
        assert result["detected"] == "none"
        assert result["products"] == []
        assert result["customers"] == []


class TestResponseShape:
    def test_reports_what_it_detected(self):
        engine = make_engine()
        assert engine.search("8850250001234")["detected"] == "barcode"
        assert engine.search("สุรชัย")["detected"] == "customer"
        assert engine.search("โค้ก")["detected"] == "product"

    def test_exposes_the_normalized_query(self):
        engine = make_engine()
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["normalized_query"] == "น้ำดื่มสิงห์600มลx12"

    def test_pagination_splits_without_overlap(self):
        engine = make_engine()
        first = engine.search("น้ำ", limit=2)
        assert len(first["products"]) == 2
        assert first["next_cursor"]
        second = engine.search("น้ำ", limit=2, cursor=first["next_cursor"])
        assert second["products"]
        first_ids = {p["product_id"] for p in first["products"]}
        second_ids = {p["product_id"] for p in second["products"]}
        assert not (first_ids & second_ids)

    def test_last_page_has_no_cursor(self):
        engine = make_engine()
        result = engine.search("น้ำ", limit=50)
        assert result["next_cursor"] is None

    def test_bad_cursor_is_ignored_rather_than_raising(self):
        engine = make_engine()
        result = engine.search("น้ำ", cursor="not-a-cursor")
        assert result["products"]

    def test_limit_is_clamped_to_the_maximum(self):
        engine = make_engine()
        result = engine.search("น้ำ", limit=5000)
        assert len(result["products"]) <= 100

    def test_limit_clamp_is_real_not_vacuous(self):
        # The test above passes with 4 products even if clamping is broken, so
        # this builds 150 products and proves the cap actually engages.
        import sqlite3

        from order_search.ingest.build import apply_schema

        connection = sqlite3.connect(":memory:", isolation_level=None)
        connection.row_factory = sqlite3.Row
        apply_schema(connection)
        connection.execute(
            "INSERT INTO customers (id, name, name_norm, name_fold_light,"
            " name_fold_heavy) VALUES (1, 'c', 'c', 'c', 'c')"
        )
        for i in range(1, 151):
            name = f"สินค้าทดสอบ {i:03d}"
            connection.execute(
                "INSERT INTO products (id, name, name_norm, name_fold_light,"
                " name_fold_heavy) VALUES (?,?,?,?,?)",
                (i, name, name, name, name),
            )
            connection.execute(
                "INSERT INTO orders (id, customer_id) VALUES (?, 1)", (i,)
            )
            connection.execute(
                "INSERT INTO order_items (order_id, product_id) VALUES (?, ?)",
                (i, i),
            )
            connection.execute(
                "INSERT INTO products_fts (name_norm, name_fold_light,"
                " product_id) VALUES (?,?,?)",
                (name, name, i),
            )
        engine = SearchEngine(connection)
        result = engine.search("สินค้าทดสอบ", limit=5000)
        assert len(result["products"]) == 100
        assert result["next_cursor"] is not None


class TestInputRobustness:
    """Untrusted input must degrade or raise clearly, never crash obscurely."""

    def test_numeric_query_does_not_crash(self):
        engine = make_engine()
        result = engine.search(123)
        assert result["detected"] == "product"

    def test_none_query_is_reported_as_none(self):
        engine = make_engine()
        result = engine.search(None)
        assert result["detected"] == "none"

    def test_non_numeric_limit_falls_back_to_default(self):
        engine = make_engine()
        result = engine.search("น้ำ", limit="notanint")
        assert result["products"]

    def test_suggest_with_non_numeric_limit_falls_back(self):
        engine = make_engine()
        suggestions = engine.suggest("น้ำ", limit="abc")
        assert len(suggestions) == 4

    def test_unknown_filter_key_is_ignored(self):
        engine = make_engine()
        result = engine.search("น้ำ", filters={"badkey": "x", "store_code": ["101"]})
        assert result["products"]

    def test_unknown_mode_raises_value_error(self):
        engine = make_engine()
        import pytest

        for bad in ["foo", "", None, "AUTO", "Customer"]:
            with pytest.raises(ValueError):
                engine.search("น้ำ", mode=bad)


class TestFoldLayerPairing:
    """Layers 3 and 3b match a query against a specific pre-computed column.
    The query must be transformed by the same function that built that column.
    Getting this wrong returns zero rows silently rather than raising, so these
    tests exist to make a mismatched pairing fail loudly.

    Measured: norm('สิงห์') against name_fold_light yields 0 rows, while
    fold_light('สิงห์') yields 1.
    """

    def test_light_fold_column_is_reachable_by_a_tone_stripped_query(self):
        engine = make_engine()
        # every one of these loses tone marks or thanthakhat relative to the
        # stored name, so layer 3 misses and layer 3b must catch them
        for query in ["สิงห", "สิงห์", "ขาวหอมมะลิ", "นำดืมสิงห", "นำดื่มสิงห"]:
            result = engine.search(query)
            assert result["products"], f"layer 3b failed to rescue {query!r}"

    def test_base_column_still_served_by_the_base_form(self):
        engine = make_engine()
        # a fully marked query must match through the base column, untouched
        result = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["name"] == "น้ำดื่มสิงห์ 600 มล. x 12"

    def test_three_character_query_that_shrinks_when_light_folded(self):
        engine = make_engine()
        # norm('น้ำ') is 3 characters, so the base column can serve it, but
        # fold_light('น้ำ') is 'นำ', only 2, which the trigram index cannot
        # match. The base column must therefore still carry this query.
        result = engine.search("น้ำ")
        assert len(result["products"]) == 4

    def test_scoped_match_does_not_cross_columns(self):
        engine = make_engine()
        # 'สงห' exists only in the heavy fold, never in the light fold column.
        # Searching the light column with a heavy form must not silently match
        # via the base column instead.
        rows = engine.connection.execute(
            "SELECT COUNT(*) AS n FROM products_fts"
            " WHERE name_fold_light MATCH ?",
            ('"สงห"',),
        ).fetchone()
        assert rows["n"] == 0
        rows = engine.connection.execute(
            "SELECT COUNT(*) AS n FROM products_fts WHERE name_norm MATCH ?",
            ('"สงห"',),
        ).fetchone()
        assert rows["n"] == 0


class TestFilterIntegration:
    def test_store_filter_narrows_the_customer_list(self):
        engine = make_engine()
        unfiltered = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        filtered = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters={"store_code": ["101"]}
        )
        assert filtered["products"]
        assert filtered["products"][0]["order_count"] == 5
        assert filtered["products"][0]["order_count"] < unfiltered["products"][0]["order_count"]

    def test_order_type_filter(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(order_type=("Pickup",))
        )
        assert result["products"]
        assert result["products"][0]["order_count"] == 22

    def test_vip_filter_is_applied_to_the_order_line(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(vip_group=("Gold",))
        )
        assert result["products"]
        assert result["products"][0]["order_count"] == 2
        tiers = set()
        for customer in result["products"][0]["customers"]:
            tiers.update(customer["vip_groups"])
        assert tiers == {"Gold"}

    def test_dept_filter(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(dept=(1,))
        )
        assert result["products"]
        everything = engine.search("น้ำดื่มสิงห์ 600 มล. x 12")
        assert result["products"][0]["order_count"] == everything["products"][0]["order_count"]

    def test_impossible_filter_yields_nothing(self):
        from order_search.search.filters import Filters

        engine = make_engine()
        result = engine.search(
            "น้ำดื่มสิงห์ 600 มล. x 12", filters=Filters(store_code=("101",), order_type=("Pickup",), dept=(9999,))
        )
        assert result["products"] == []
