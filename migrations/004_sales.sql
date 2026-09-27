CREATE SCHEMA IF NOT EXISTS sales;

CREATE TABLE IF NOT EXISTS sales.customers_v1 (
    id              bigint PRIMARY KEY,
    name            text NOT NULL,
    name_norm       text NOT NULL,
    name_fold_light text NOT NULL,
    name_fold_heavy text NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_v1_norm
    ON sales.customers_v1 (name_norm);
CREATE INDEX IF NOT EXISTS idx_customers_v1_trgm
    ON sales.customers_v1 USING gin (name_norm gin_trgm_ops);

CREATE TABLE IF NOT EXISTS sales.orders_v1 (
    id          bigint PRIMARY KEY,
    order_no    text,
    store_code  text,
    customer_id bigint NOT NULL,
    order_type  text,
    date_from   date,
    date_to     date,
    item_remark text,
    vip_remark  text,
    vip_group   text
);
CREATE INDEX IF NOT EXISTS idx_orders_v1_customer ON sales.orders_v1 (customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_v1_store    ON sales.orders_v1 (store_code);
CREATE INDEX IF NOT EXISTS idx_orders_v1_type     ON sales.orders_v1 (order_type);
CREATE INDEX IF NOT EXISTS idx_orders_v1_vip      ON sales.orders_v1 (vip_group);
CREATE INDEX IF NOT EXISTS idx_orders_v1_from     ON sales.orders_v1 (date_from);
CREATE INDEX IF NOT EXISTS idx_orders_v1_to       ON sales.orders_v1 (date_to);

CREATE TABLE IF NOT EXISTS sales.order_items_v1 (
    order_id   bigint NOT NULL,
    product_id bigint NOT NULL,
    qty        numeric,
    price      numeric,
    PRIMARY KEY (order_id, product_id)
);
CREATE INDEX IF NOT EXISTS idx_order_items_v1_product
    ON sales.order_items_v1 (product_id);
