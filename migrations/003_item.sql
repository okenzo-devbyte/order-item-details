CREATE SCHEMA IF NOT EXISTS item;

CREATE TABLE IF NOT EXISTS item.products_v1 (
    id              bigint PRIMARY KEY,
    name            text NOT NULL,
    name_norm       text NOT NULL,
    name_fold_light text NOT NULL,
    name_fold_heavy text NOT NULL,
    dept            integer,
    class_code      integer,
    subclass_code   integer,
    pack_size       integer,
    unit            text
);
CREATE INDEX IF NOT EXISTS idx_products_v1_name_norm
    ON item.products_v1 (name_norm text_pattern_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_trgm
    ON item.products_v1 USING gin (name_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_fold_trgm
    ON item.products_v1 USING gin (name_fold_light gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_products_v1_dept ON item.products_v1 (dept);
CREATE INDEX IF NOT EXISTS idx_products_v1_class ON item.products_v1 (class_code);
CREATE INDEX IF NOT EXISTS idx_products_v1_subclass ON item.products_v1 (subclass_code);

CREATE TABLE IF NOT EXISTS item.product_barcodes_v1 (
    product_id bigint NOT NULL,
    barcode    text NOT NULL,
    PRIMARY KEY (product_id, barcode)
);
CREATE INDEX IF NOT EXISTS idx_barcodes_v1_barcode
    ON item.product_barcodes_v1 (barcode);
