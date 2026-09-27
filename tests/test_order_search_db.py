import dataclasses

import pytest

from order_search.db import Tables, app_table

RELATIONS = ("products", "product_barcodes", "customers", "orders", "order_items")


def test_the_item_relations_are_schema_qualified_and_quoted():
    tables = Tables.from_schemas("t_item", "t_sales")
    assert tables.products == '"t_item"."products"'
    assert tables.product_barcodes == '"t_item"."product_barcodes"'


def test_the_sales_relations_are_schema_qualified_and_quoted():
    tables = Tables.from_schemas("t_item", "t_sales")
    assert tables.customers == '"t_sales"."customers"'
    assert tables.orders == '"t_sales"."orders"'
    assert tables.order_items == '"t_sales"."order_items"'


def test_every_relation_is_qualified():
    tables = Tables.from_schemas("t_item", "t_sales")
    for name in RELATIONS:
        value = getattr(tables, name)
        assert value.startswith('"')
        assert value.count(".") == 1
        assert value.endswith('"')


def test_the_default_schemas_are_what_they_were():
    # A test that only ever passes `t_` prefixes would still let a change to the
    # production default through unnoticed.
    assert Tables.from_schemas("item", "sales").products == '"item"."products"'
    assert Tables.from_schemas("item", "sales").order_items == '"sales"."order_items"'


def test_the_tables_are_frozen():
    # The names are resolved once per process, so a query must not be able to
    # rewrite the relation another query will use.
    tables = Tables.from_schemas("t_item", "t_sales")
    with pytest.raises(dataclasses.FrozenInstanceError):
        tables.products = '"public"."products"'


def test_app_table_quotes_the_schema_and_the_name():
    assert app_table("t_app", "users") == '"t_app"."users"'
    assert app_table("app", "schema_migrations") == '"app"."schema_migrations"'


def test_a_schema_name_is_quoted_not_escaped():
    # The mechanism quotes and does not escape, so a quote in the name would
    # close the identifier. What actually keeps that out is SQL_IDENTIFIER in
    # api/config.py, which rejects the name before it can reach a query; this
    # test exists so nobody mistakes the quoting for the control.
    assert app_table("t item", "users") == '"t item"."users"'
    assert app_table('t"item', "users") == '"t"item"."users"'


def test_both_ways_of_quoting_a_relation_name_agree():
    # There is one mechanism, not two that can drift.
    tables = Tables.from_schemas("t_item", "t_sales")
    assert tables.products == app_table("t_item", "products")
    assert tables.orders == app_table("t_sales", "orders")
