CREATE OR REPLACE VIEW item.products AS
    SELECT id, name, name_norm, name_fold_light, name_fold_heavy,
           dept, class_code, subclass_code, pack_size, unit
    FROM item.products_v1;

CREATE OR REPLACE VIEW item.product_barcodes AS
    SELECT product_id, barcode FROM item.product_barcodes_v1;

CREATE OR REPLACE VIEW sales.customers AS
    SELECT id, name, name_norm, name_fold_light, name_fold_heavy
    FROM sales.customers_v1;

CREATE OR REPLACE VIEW sales.orders AS
    SELECT id, order_no, store_code, customer_id, order_type,
           date_from, date_to, item_remark, vip_remark, vip_group
    FROM sales.orders_v1;

CREATE OR REPLACE VIEW sales.order_items AS
    SELECT order_id, product_id, qty, price FROM sales.order_items_v1;
