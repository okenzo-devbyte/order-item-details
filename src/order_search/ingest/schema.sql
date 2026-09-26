-- Read-only snapshot of imported order data.
-- Every text column the search engine touches has a pre-normalized companion
-- column; see src/order_search/textnorm.py for the rules.

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS products_fts;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS product_barcodes;
DROP TABLE IF EXISTS meta;

CREATE TABLE products (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    name_norm       TEXT    NOT NULL DEFAULT '',
    name_fold_light TEXT    NOT NULL DEFAULT '',
    name_fold_heavy TEXT    NOT NULL DEFAULT '',
    dept            INTEGER,
    class_code      INTEGER,
    subclass_code   INTEGER,
    pack_size       INTEGER,
    unit            TEXT
);

-- Standalone FTS5 table rather than an external-content table: the build runs
-- once, so there is no sync problem to get wrong. The product text is
-- duplicated, which is irrelevant at this data size.
CREATE VIRTUAL TABLE products_fts USING fts5(
    name_norm,
    name_fold_light,
    product_id UNINDEXED,
    tokenize='trigram'
);

CREATE TABLE product_barcodes (
    product_id INTEGER NOT NULL REFERENCES products(id),
    barcode    TEXT    NOT NULL,
    PRIMARY KEY (product_id, barcode)
) WITHOUT ROWID;

-- Deliberately NOT unique: a barcode may legitimately map to two products,
-- and a UNIQUE index would abort the import.
CREATE INDEX idx_barcodes_barcode ON product_barcodes(barcode);

CREATE TABLE customers (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL,
    name_norm       TEXT    NOT NULL,
    name_fold_light TEXT    NOT NULL,
    name_fold_heavy TEXT    NOT NULL
);

-- Names are the only customer key available in the source file, so two people
-- sharing a name would collide here. Documented as a known limitation.
CREATE UNIQUE INDEX idx_customers_name_norm ON customers(name_norm);

CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    order_no    TEXT,
    store_code  TEXT,
    customer_id INTEGER REFERENCES customers(id),
    order_type  TEXT,
    date_from   TEXT,
    date_to     TEXT,
    item_remark TEXT,
    vip_remark  TEXT,
    vip_group   TEXT
);

-- vip_group and vip_remark stay on the order line on purpose: in the real data
-- every one of the 20 customers carries several different tiers across their
-- own orders, so they cannot be lifted to the customer level.
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_store    ON orders(store_code);
CREATE INDEX idx_orders_type     ON orders(order_type);
CREATE INDEX idx_orders_vip      ON orders(vip_group);
CREATE INDEX idx_orders_dates    ON orders(date_from, date_to);

CREATE TABLE order_items (
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    qty        INTEGER,
    price      REAL,
    PRIMARY KEY (order_id, product_id)
) WITHOUT ROWID;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
) WITHOUT ROWID;
