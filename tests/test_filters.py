from order_search.search.filters import Filters, order_filter_sql


def params_for(filters: Filters):
    sql, params = order_filter_sql(filters)
    return sql, list(params)


class TestEmptyFilters:
    def test_produces_no_predicate(self):
        sql, params = params_for(Filters())
        assert sql == ""
        assert params == []


class TestEqualityFilters:
    def test_single_store(self):
        sql, params = params_for(Filters(store_code=("135",)))
        assert "o.store_code IN (?)" in sql
        assert params == ["135"]

    def test_multiple_stores_are_or_within_the_group(self):
        sql, params = params_for(Filters(store_code=("135", "140")))
        assert sql.count("?") == 2
        assert params == ["135", "140"]

    def test_order_type(self):
        sql, params = params_for(Filters(order_type=("Pickup",)))
        assert "o.order_type IN (?)" in sql
        assert params == ["Pickup"]

    def test_dept_class_subclass(self):
        sql, params = params_for(Filters(dept=(1, 4), class_code=(101,), subclass_code=(5,)))
        assert "o.dept" not in sql  # dept lives on the product, see below
        assert "p.dept" in sql
        assert "p.class_code" in sql
        assert "p.subclass_code" in sql
        assert params == [1, 4, 101, 5]

    def test_vip_group_filters_on_the_order_line(self):
        sql, params = params_for(Filters(vip_group=("Gold",)))
        assert "o.vip_group" in sql
        assert params == ["Gold"]

    def test_groups_are_anded_together(self):
        sql, _params = params_for(
            Filters(store_code=("135",), order_type=("Pickup",))
        )
        assert sql.count("AND") >= 1
        assert "o.store_code" in sql
        assert "o.order_type" in sql

    def test_blank_values_are_dropped(self):
        sql, params = params_for(Filters(store_code=("", "  ", "135")))
        assert params == ["135"]


class TestDateFilter:
    def test_overlap_semantics(self):
        # an order passes when its own range overlaps the requested range
        sql, params = params_for(
            Filters(date_from="2026-09-01", date_to="2026-09-30")
        )
        assert "o.date_from <= ?" in sql
        assert "o.date_to >= ?" in sql
        assert params == ["2026-09-30", "2026-09-01"]

    def test_orders_without_a_date_are_excluded_when_filtering(self):
        sql, _params = params_for(Filters(date_from="2026-09-01"))
        assert "o.date_from IS NOT NULL" in sql

    def test_no_null_clause_when_not_filtering_by_date(self):
        sql, _params = params_for(Filters(store_code=("135",)))
        assert "IS NOT NULL" not in sql

    def test_only_one_bound_is_allowed(self):
        sql, params = order_filter_sql(Filters(date_from="2026-09-01"))
        assert "o.date_from <= ?" not in sql
        assert "o.date_to >= ?" in sql
        assert list(params) == ["2026-09-01"]

        sql, params = order_filter_sql(Filters(date_to="2026-09-30"))
        assert "o.date_from <= ?" in sql
        assert "o.date_to >= ?" not in sql
        assert list(params) == ["2026-09-30"]

    def test_values_are_iso_comparable_strings(self):
        # ISO YYYY-MM-DD sorts chronologically as text, so plain comparison works
        sql, params = order_filter_sql(
            Filters(date_from="2026-01-05", date_to="2026-11-30")
        )
        assert list(params) == ["2026-11-30", "2026-01-05"]


class TestFiltersValueObject:
    def test_defaults_are_empty(self):
        filters = Filters()
        assert filters.store_code == ()
        assert filters.dept == ()
        assert filters.date_from is None

    def test_is_immutable(self):
        filters = Filters()
        try:
            filters.store_code = ("135",)  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("Filters should be frozen")

    def test_accepts_any_iterable(self):
        filters = Filters(store_code=["135", "140"])
        assert filters.store_code == ("135", "140")
