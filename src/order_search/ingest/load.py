from __future__ import annotations

from typing import Any

from .transform import TransformedData, transform

PRODUCT_COLUMNS = (
    "id", "name", "name_norm", "name_fold_light", "name_fold_heavy",
    "dept", "class_code", "subclass_code", "pack_size", "unit",
)
CUSTOMER_COLUMNS = ("id", "name", "name_norm", "name_fold_light", "name_fold_heavy")
ORDER_COLUMNS = (
    "id", "order_no", "store_code", "customer_id", "order_type",
    "date_from", "date_to", "item_remark", "vip_remark", "vip_group",
)
ORDER_ITEM_COLUMNS = ("order_id", "product_id", "qty", "price")
BARCODE_COLUMNS = ("product_id", "barcode")

VIEW_COLUMNS = {
    "products": (
        "id, name, name_norm, name_fold_light, name_fold_heavy,"
        " dept, class_code, subclass_code, pack_size, unit"
    ),
    "product_barcodes": "product_id, barcode",
    "customers": "id, name, name_norm, name_fold_light, name_fold_heavy",
    "orders": (
        "id, order_no, store_code, customer_id, order_type,"
        " date_from, date_to, item_remark, vip_remark, vip_group"
    ),
    "order_items": "order_id, product_id, qty, price",
}


def load_into_version(
    database, rows: list[dict[str, Any]], version: int
) -> TransformedData:
    """Fills the `{table}_v{version}` tables and repoints the views at them.

    The views move only after every copy has landed, so a failure anywhere in
    this function leaves the previous version serving traffic.
    """
    data = transform(rows)
    item = database.schema_item
    sales = database.schema_sales

    for ddl in _version_ddl(version, item, sales).values():
        database.execute_script(ddl)
    database.run(f'TRUNCATE "{item}"."products_v{version}" CASCADE')
    database.run(f'TRUNCATE "{item}"."product_barcodes_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."customers_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."orders_v{version}" CASCADE')
    database.run(f'TRUNCATE "{sales}"."order_items_v{version}" CASCADE')

    database.copy(f'"{item}"."products_v{version}"', PRODUCT_COLUMNS, data.products)
    database.copy(f'"{sales}"."customers_v{version}"', CUSTOMER_COLUMNS, data.customers)
    database.copy(f'"{sales}"."orders_v{version}"', ORDER_COLUMNS, data.orders)
    database.copy(
        f'"{sales}"."order_items_v{version}"', ORDER_ITEM_COLUMNS, data.order_items
    )
    database.copy(
        f'"{item}"."product_barcodes_v{version}"', BARCODE_COLUMNS, data.barcodes
    )

    for name, columns in VIEW_COLUMNS.items():
        schema = item if name in ("products", "product_barcodes") else sales
        database.execute_script(
            f'CREATE OR REPLACE VIEW "{schema}"."{name}" AS'
            f" SELECT {columns} FROM \"{schema}\".\"{name}_v{version}\";"
        )

    database.run(
        f'UPDATE "{database.schema_app}"."data_versions" SET is_current = false'
        " WHERE is_current"
    )
    database.run(
        f'INSERT INTO "{database.schema_app}"."data_versions"'
        " (version, source_filename, row_count, product_count, customer_count,"
        " order_count, barcode_count, is_current)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,true)",
        (
            version,
            "load",
            data.report.rows_imported,
            data.report.products,
            data.report.customers,
            data.report.orders,
            data.report.barcodes,
        ),
    )
    return data


def _version_ddl(version: int, item: str, sales: str) -> dict[str, str]:
    return {
        "products": f"""
            CREATE TABLE IF NOT EXISTS "{item}"."products_v{version}" (
                id bigint PRIMARY KEY, name text NOT NULL, name_norm text NOT NULL,
                name_fold_light text NOT NULL, name_fold_heavy text NOT NULL,
                dept integer, class_code integer, subclass_code integer,
                pack_size integer, unit text);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_norm"
                ON "{item}"."products_v{version}" (name_norm text_pattern_ops);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_trgm"
                ON "{item}"."products_v{version}" USING gin (name_norm gin_trgm_ops);
            CREATE INDEX IF NOT EXISTS "{item}_products_v{version}_fold"
                ON "{item}"."products_v{version}" USING gin (name_fold_light gin_trgm_ops);
        """,
        "product_barcodes": f"""
            CREATE TABLE IF NOT EXISTS "{item}"."product_barcodes_v{version}" (
                product_id bigint NOT NULL, barcode text NOT NULL,
                PRIMARY KEY (product_id, barcode));
            CREATE INDEX IF NOT EXISTS "{item}_barcodes_v{version}_code"
                ON "{item}"."product_barcodes_v{version}" (barcode);
        """,
        "customers": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."customers_v{version}" (
                id bigint PRIMARY KEY, name text NOT NULL, name_norm text NOT NULL,
                name_fold_light text NOT NULL, name_fold_heavy text NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS "{sales}_customers_v{version}_norm"
                ON "{sales}"."customers_v{version}" (name_norm);
            CREATE INDEX IF NOT EXISTS "{sales}_customers_v{version}_trgm"
                ON "{sales}"."customers_v{version}" USING gin (name_norm gin_trgm_ops);
        """,
        "orders": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."orders_v{version}" (
                id bigint PRIMARY KEY, order_no text, store_code text,
                customer_id bigint NOT NULL, order_type text, date_from date,
                date_to date, item_remark text, vip_remark text, vip_group text);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_customer"
                ON "{sales}"."orders_v{version}" (customer_id);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_from"
                ON "{sales}"."orders_v{version}" (date_from);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_to"
                ON "{sales}"."orders_v{version}" (date_to);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_store"
                ON "{sales}"."orders_v{version}" (store_code);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_type"
                ON "{sales}"."orders_v{version}" (order_type);
            CREATE INDEX IF NOT EXISTS "{sales}_orders_v{version}_vip"
                ON "{sales}"."orders_v{version}" (vip_group);
        """,
        "order_items": f"""
            CREATE TABLE IF NOT EXISTS "{sales}"."order_items_v{version}" (
                order_id bigint NOT NULL, product_id bigint NOT NULL,
                qty numeric, price numeric, PRIMARY KEY (order_id, product_id));
            CREATE INDEX IF NOT EXISTS "{sales}_order_items_v{version}_product"
                ON "{sales}"."order_items_v{version}" (product_id);
        """,
    }