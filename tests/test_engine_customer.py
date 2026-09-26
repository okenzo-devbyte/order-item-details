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


class TestCustomerMode:
    def test_exact_customer_name_returns_that_customer(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert result["mode"] == "customer"
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]

    def test_customer_order_line_count(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert result["customers"][0]["order_count"] == 65

    def test_customer_bought_fifteen_distinct_products(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert len(result["customers"][0]["products"]) == 15

    def test_customer_product_counts_are_aggregated(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        products = {
            p["name"]: p["order_count"]
            for p in result["customers"][0]["products"]
        }
        assert products["น้ำดื่มสิงห์ 600 มล. x 12"] == 6

    def test_customer_bought_from_fourteen_distinct_stores(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        stores = set()
        for product in result["customers"][0]["products"]:
            stores.update(product["stores"])
        assert len(stores) == 14

    def test_customer_order_types_are_reported(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        types = set()
        for product in result["customers"][0]["products"]:
            types.update(product["order_types"])
        assert types == {
            "Express delivery",
            "Pickup",
            "Scheduled delivery",
            "Standard delivery",
        }

    def test_vip_tiers_are_reported_per_product(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        tiers = set()
        for product in result["customers"][0]["products"]:
            tiers.update(product["vip_groups"])
        assert tiers == {"Gold", "Platinum", "VIP", "Wholesale VIP"}

    def test_customer_name_with_surrounding_spaces(self):
        engine = make_engine()
        assert engine.search("  สุรชัย  ")["customers"][0]["name"] == "สุรชัย"

    def test_unknown_customer_returns_no_customers(self):
        engine = make_engine()
        result = engine.search("ไม่มีในระบบ")
        assert result["customers"] == []

    def test_customer_result_exposes_an_id(self):
        engine = make_engine()
        result = engine.search("สุรชัย")
        assert isinstance(result["customers"][0]["customer_id"], int)


class TestFuzzyCustomerLookup:
    """Layer 2 of the search: a customer name typed with a mistake still finds
    the customer. The cutoff of 70 was measured against all 20 real names: it
    recognises every genuine typo tested and matched none of the non-name
    queries."""

    def test_prefix_of_a_name_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("สุรช")
        assert result["mode"] == "customer"
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]

    def test_omitted_final_vowel_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("อนุช")
        assert [c["name"] for c in result["customers"]] == ["อนุชา"]

    def test_transposed_vowel_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("อนูชา")
        assert [c["name"] for c in result["customers"]] == ["อนุชา"]

    def test_dropped_tone_mark_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("พงษ์ศักติ์")
        assert [c["name"] for c in result["customers"]] == ["พงษ์ศักดิ์"]

    def test_fuzzy_customer_returns_the_full_purchase_history(self):
        engine = make_engine()
        result = engine.search("สุรช")
        assert result["customers"][0]["order_count"] == 65
        assert len(result["customers"][0]["products"]) == 15

    def test_product_text_does_not_invent_a_customer(self):
        engine = make_engine()
        result = engine.search("น้ำ")
        assert result["customers"] == []
        assert result["products"]

    def test_nonsense_does_not_invent_a_customer(self):
        engine = make_engine()
        assert engine.search("ซไบเตอร์")["customers"] == []
        assert engine.search("zzz")["customers"] == []

    def test_barcode_never_triggers_customer_fuzzy(self):
        engine = make_engine()
        assert engine.search("8850250001234")["customers"] == []

    def test_explicit_product_mode_suppresses_customer_results(self):
        engine = make_engine()
        result = engine.search("สุรช", mode="product")
        assert result["customers"] == []

    def test_explicit_customer_mode_still_finds_the_customer(self):
        engine = make_engine()
        result = engine.search("สุรช", mode="customer")
        assert [c["name"] for c in result["customers"]] == ["สุรชัย"]
