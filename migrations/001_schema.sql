-- Order Groups Web — schema `order_item` (isolated namespace for this project)
create schema if not exists order_item;

create table order_item.order_items (
  id            bigserial primary key,
  order_number  text not null,
  store_code    text,
  item_id       text not null,
  product_name  text not null,
  product_norm  text not null,
  customer_name text not null,
  customer_norm text not null,
  expected_from date,
  expected_to   date,
  expected_raw  text,
  dept          integer,
  class         integer,
  subclass      integer,
  item_remark          text,
  vip_customer_remarks text,
  vip_customer_groups  text
);

create index order_items_customer_norm_idx on order_item.order_items (customer_norm);
create index order_items_product_norm_idx  on order_item.order_items (product_norm);
create index order_items_group_idx         on order_item.order_items (dept, class, subclass);
create index order_items_order_number_idx  on order_item.order_items (order_number);

create table order_item.users (
  id            uuid primary key default gen_random_uuid(),
  username      text unique not null,
  password_hash text not null,
  role          text not null check (role in ('admin','viewer')),
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table order_item.sessions (
  token_hash text primary key,
  user_id    uuid not null references order_item.users(id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table order_item.imports (
  id          bigserial primary key,
  filename    text,
  mode        text not null check (mode in ('replace','append')),
  row_count   integer not null,
  imported_by text,
  imported_at timestamptz not null default now()
);

-- Atomic import: replace mode (delete all + insert + log) in one transaction.
create or replace function order_item.replace_all(p_rows jsonb, p_filename text, p_imported_by text)
returns jsonb language plpgsql as $$
declare v_count int;
begin
  delete from order_item.order_items;
  insert into order_item.order_items
    (order_number, store_code, item_id, product_name, product_norm,
     customer_name, customer_norm, expected_from, expected_to, expected_raw,
     dept, class, subclass, item_remark, vip_customer_remarks, vip_customer_groups)
  select
    r->>'Order Number', nullif(r->>'Store Code',''), r->>'Item Id', r->>'Product Name',
    lower(regexp_replace(coalesce(r->>'Product Name',''), '\s+', '', 'g')),
    r->>'Customer Name',
    lower(regexp_replace(coalesce(r->>'Customer Name',''), '\s+', '', 'g')),
    (r->>'_from')::date, (r->>'_to')::date, r->>'Original Expected Date',
    nullif(r->>'Dept','')::int, nullif(r->>'Class','')::int, nullif(r->>'Subclass','')::int,
    nullif(r->>'Item Remark',''), nullif(r->>'VIP Customer Remarks',''), nullif(r->>'VIP Customer Groups','')
  from jsonb_array_elements(p_rows) r;
  get diagnostics v_count = row_count;
  insert into order_item.imports (filename, mode, row_count, imported_by)
  values (p_filename, 'replace', v_count, p_imported_by);
  return jsonb_build_object('row_count', v_count);
end $$;

-- Atomic import: append mode (insert + log) in one transaction.
create or replace function order_item.append_rows(p_rows jsonb, p_filename text, p_imported_by text)
returns jsonb language plpgsql as $$
declare v_count int;
begin
  insert into order_item.order_items
    (order_number, store_code, item_id, product_name, product_norm,
     customer_name, customer_norm, expected_from, expected_to, expected_raw,
     dept, class, subclass, item_remark, vip_customer_remarks, vip_customer_groups)
  select
    r->>'Order Number', nullif(r->>'Store Code',''), r->>'Item Id', r->>'Product Name',
    lower(regexp_replace(coalesce(r->>'Product Name',''), '\s+', '', 'g')),
    r->>'Customer Name',
    lower(regexp_replace(coalesce(r->>'Customer Name',''), '\s+', '', 'g')),
    (r->>'_from')::date, (r->>'_to')::date, r->>'Original Expected Date',
    nullif(r->>'Dept','')::int, nullif(r->>'Class','')::int, nullif(r->>'Subclass','')::int,
    nullif(r->>'Item Remark',''), nullif(r->>'VIP Customer Remarks',''), nullif(r->>'VIP Customer Groups','')
  from jsonb_array_elements(p_rows) r;
  get diagnostics v_count = row_count;
  insert into order_item.imports (filename, mode, row_count, imported_by)
  values (p_filename, 'append', v_count, p_imported_by);
  return jsonb_build_object('row_count', v_count);
end $$;

-- RLS on, no policies: service role bypasses, browser never holds the key.
alter table order_item.order_items enable row level security;
alter table order_item.users      enable row level security;
alter table order_item.sessions   enable row level security;
alter table order_item.imports    enable row level security;
