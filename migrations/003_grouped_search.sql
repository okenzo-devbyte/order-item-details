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
             max(base.customer_name) as customer_name,
             count(*)::bigint as order_count,
             count(distinct base.item_id)::bigint as product_count,
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
      select item_id, max(base.product_name) as product_name,
             count(*)::bigint as order_count,
             count(distinct base.customer_name)::bigint as customer_count
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
    select max(base.customer_name) as customer_name,
           count(*)::bigint as order_count,
           count(distinct base.item_id)::bigint as product_count,
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
    select max(base.item_id) as item_id,
           max(base.product_name) as product_name,
           count(*)::bigint as order_count,
           count(distinct base.customer_name)::bigint as customer_count,
           (select jsonb_agg(jsonb_build_object('dept', g.dept, 'class', g.class, 'subclass', g.subclass, 'count', g.cnt)) from grp g) as groups
    from base;
end $$;