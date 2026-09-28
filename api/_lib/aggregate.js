function groupKey(r) {
  return `${r.dept}|${r.class}|${r.subclass}`;
}

export function aggregateCustomers(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = r.customer_norm;
    if (!by.has(key)) {
      by.set(key, { customer_name: r.customer_name, order_count: 0, items: new Set(), groups: new Map(), vip: new Set(), last_expected: null });
    }
    const c = by.get(key);
    c.order_count++;
    c.items.add(r.item_id);
    if (!c.groups.has(groupKey(r))) c.groups.set(groupKey(r), { dept: r.dept, class: r.class, subclass: r.subclass, count: 0 });
    c.groups.get(groupKey(r)).count++;
    if (r.vip_customer_groups) c.vip.add(r.vip_customer_groups);
    if (r.expected_from && (!c.last_expected || r.expected_from > c.last_expected)) c.last_expected = r.expected_from;
  }
  return [...by.values()].map((c) => ({
    customer_name: c.customer_name,
    order_count: c.order_count,
    product_count: c.items.size,
    groups: [...c.groups.values()],
    vip_groups: [...c.vip],
    last_expected: c.last_expected
  })).sort((a, b) => b.order_count - a.order_count);
}

export function aggregateProducts(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = r.item_id;
    if (!by.has(key)) {
      by.set(key, { item_id: r.item_id, product_name: r.product_name, order_count: 0, customers: new Set(), groups: new Map() });
    }
    const p = by.get(key);
    p.order_count++;
    p.customers.add(r.customer_name);
    if (!p.groups.has(groupKey(r))) p.groups.set(groupKey(r), { dept: r.dept, class: r.class, subclass: r.subclass, count: 0 });
    p.groups.get(groupKey(r)).count++;
  }
  return [...by.values()].map((p) => ({
    item_id: p.item_id,
    product_name: p.product_name,
    order_count: p.order_count,
    customer_count: p.customers.size,
    groups: [...p.groups.values()]
  })).sort((a, b) => b.order_count - a.order_count);
}