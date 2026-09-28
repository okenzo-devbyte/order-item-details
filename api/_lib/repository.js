import { normalizeThai } from './normalize.js';

function paginate(items, page, pageSize) {
  const total = items.length;
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total };
}

function groupKey(r) {
  return `${r.dept}|${r.class}|${r.subclass}`;
}

function aggregateCustomers(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = r.customer_norm;
    if (!by.has(key)) {
      by.set(key, { customer_name: r.customer_name, order_count: 0, product_count: 0, groups: new Map(), vip: new Set(), last_expected: null });
    }
    const c = by.get(key);
    c.order_count++;
    if (!c.groups.has(groupKey(r))) c.groups.set(groupKey(r), { dept: r.dept, class: r.class, subclass: r.subclass, count: 0 });
    c.groups.get(groupKey(r)).count++;
    if (r.vip_customer_groups) c.vip.add(r.vip_customer_groups);
    if (r.expected_from && (!c.last_expected || r.expected_from > c.last_expected)) c.last_expected = r.expected_from;
  }
  return [...by.values()].map((c) => ({
    customer_name: c.customer_name,
    order_count: c.order_count,
    product_count: c.groups.size,
    groups: [...c.groups.values()],
    vip_groups: [...c.vip],
    last_expected: c.last_expected
  })).sort((a, b) => b.order_count - a.order_count);
}

function aggregateProducts(rows) {
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

export function createRepository(adapter) {
  return {
    findUserByUsername: (u) => adapter.findUserByUsername(u),
    createSession: (userId, tokenHash, expiresAt) => adapter.createSession(userId, tokenHash, expiresAt),
    findSession: (tokenHash) => adapter.findSession(tokenHash),
    deleteSession: (tokenHash) => adapter.deleteSession(tokenHash),
    touchSession: (tokenHash, expiresAt) => adapter.touchSession(tokenHash, expiresAt),

    async searchCustomers({ q, dept, cls, subclass, page, pageSize }) {
      const rows = await adapter.queryOrderRows({ q, direction: 'customer', dept, cls, subclass, limit: 10000 });
      return paginate(aggregateCustomers(rows), page, pageSize);
    },

    async searchProducts({ q, dept, cls, subclass, page, pageSize }) {
      const rows = await adapter.queryOrderRows({ q, direction: 'product', dept, cls, subclass, limit: 10000 });
      return paginate(aggregateProducts(rows), page, pageSize);
    },

    async searchOrders({ q, direction, dept, cls, subclass, page, pageSize }) {
      const params = { q, direction, dept, cls, subclass };
      const total = await adapter.countOrderRows(params);
      const rows = await adapter.queryOrderRows({ ...params, limit: pageSize });
      return { items: rows, total };
    },

    async getCustomer(name) {
      const rows = await adapter.queryOrderRows({ customerNorm: normalizeThai(name), limit: 10000 });
      if (rows.length === 0) return null;
      const agg = aggregateCustomers(rows)[0];
      return { ...agg, orders: rows };
    },

    async getProduct(itemId) {
      const rows = await adapter.queryOrderRows({ itemId, limit: 10000 });
      if (rows.length === 0) return null;
      const agg = aggregateProducts(rows)[0];
      return { ...agg, customers: [...new Set(rows.map((r) => r.customer_name))] };
    },

    listFilters: (p) => adapter.listFilters(p),
    getStats: () => adapter.getStats(),
    importRows: (p) => adapter.importRows(p),
    listImports: (limit) => adapter.listImports(limit),
    clearAll: () => adapter.clearAll()
  };
}
