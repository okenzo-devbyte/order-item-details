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
-- Expose the order_item schema to the Supabase Data API (PostgREST).
-- Run this in the Supabase SQL Editor AFTER 001_schema.sql.
-- You must ALSO add `order_item` to "Exposed schemas" in
-- Project Settings -> Data API, otherwise the API keeps rejecting it.

GRANT USAGE ON SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA order_item TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA order_item TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON ROUTINES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA order_item GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
-- Grouped search + detail summaries in SQL (correct at large row counts).
-- Run this in the Supabase SQL Editor AFTER 001_schema.sql and 002_expose_schema.sql.
-- (Also appended to 001_schema.sql so fresh setups get everything in one file.)

create or replace function order_item.search_customers(
  p_q text, p_dept int, p_class int, p_subclass int, p_limit int
) returns table (
  customer_name text, order_count bigint, product_count bigint,
  groups jsonb, vip_groups text[], last_expected date
) language plpgsql as $$
begin
  return query
    with base as (
      select * from order_item.order_items o
      where (p_q is null or p_q = '' or o.customer_norm ilike '%' || p_q || '%')
        and (p_dept is null or o.dept = p_dept)
        and (p_class is null or o.class = p_class)
        and (p_subclass is null or o.subclass = p_subclass)
    ),
    grp as (
      select customer_norm, dept, class, subclass, count(*)::int as cnt
      from base group by customer_norm, dept, class, subclass
    ),
    agg as (
      select customer_norm,
             max(customer_name) as customer_name,
             count(*)::bigint as order_count,
             count(distinct item_id)::bigint as product_count,
             max(expected_from) as last_expected,
             array_agg(distinct vip_customer_groups) filter (where vip_customer_groups is not null) as vip_groups
      from base group by customer_norm
    )
    select agg.customer_name, agg.order_count, agg.product_count,
           (select jsonb_agg(jsonb_build_object('dept', g.dept, 'class', g.class, 'subclass', g.subclass, 'count', g.cnt))
            from grp g where g.customer_norm = agg.customer_norm) as groups,
           agg.vip_groups, agg.last_expected
    from agg
    order by agg.order_count desc
    limit p_limit;
end $$;

create or replace function order_item.search_products(
  p_q text, p_dept int, p_class int, p_subclass int, p_limit int
) returns table (
  item_id text, product_name text, order_count bigint, customer_count bigint, groups jsonb
) language plpgsql as $$
begin
  return query
    with base as (
      select * from order_item.order_items o
      where (p_q is null or p_q = '' or o.product_norm ilike '%' || p_q || '%')
        and (p_dept is null or o.dept = p_dept)
        and (p_class is null or o.class = p_class)
        and (p_subclass is null or o.subclass = p_subclass)
    ),
    grp as (
      select item_id, dept, class, subclass, count(*)::int as cnt
      from base group by item_id, dept, class, subclass
    ),
    agg as (
      select item_id, max(product_name) as product_name,
             count(*)::bigint as order_count,
             count(distinct customer_name)::bigint as customer_count
      from base group by item_id
    )
    select agg.item_id, agg.product_name, agg.order_count, agg.customer_count,
           (select jsonb_agg(jsonb_build_object('dept', g.dept, 'class', g.class, 'subclass', g.subclass, 'count', g.cnt))
            from grp g where g.item_id = agg.item_id) as groups
    from agg
    order by agg.order_count desc
    limit p_limit;
end $$;

create or replace function order_item.customer_summary(p_name text)
returns table (
  customer_name text, order_count bigint, product_count bigint,
  groups jsonb, vip_groups text[], last_expected date
) language plpgsql as $$
begin
  return query
    with base as (
      select * from order_item.order_items
      where customer_norm = lower(regexp_replace(coalesce(p_name, ''), '\s+', '', 'g'))
    ),
    grp as (
      select dept, class, subclass, count(*)::int as cnt
      from base group by dept, class, subclass
    )
    select max(customer_name) as customer_name,
           count(*)::bigint as order_count,
           count(distinct item_id)::bigint as product_count,
           (select jsonb_agg(jsonb_build_object('dept', g.dept, 'class', g.class, 'subclass', g.subclass, 'count', g.cnt)) from grp g) as groups,
           array_agg(distinct vip_customer_groups) filter (where vip_customer_groups is not null) as vip_groups,
           max(expected_from) as last_expected
    from base;
end $$;

create or replace function order_item.product_summary(p_item_id text)
returns table (
  item_id text, product_name text, order_count bigint, customer_count bigint, groups jsonb
) language plpgsql as $$
begin
  return query
    with base as (
      select * from order_item.order_items where item_id = p_item_id
    ),
    grp as (
      select dept, class, subclass, count(*)::int as cnt
      from base group by dept, class, subclass
    )
    select max(item_id) as item_id,
           max(product_name) as product_name,
           count(*)::bigint as order_count,
           count(distinct customer_name)::bigint as customer_count,
           (select jsonb_agg(jsonb_build_object('dept', g.dept, 'class', g.class, 'subclass', g.subclass, 'count', g.cnt)) from grp g) as groups
    from base;
end $$;
