import { normalizeThai } from './normalize.js';

function paginate(items, page, pageSize) {
  const total = items.length;
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total };
}

export function createRepository(adapter) {
  return {
    findUserByUsername: (u) => adapter.findUserByUsername(u),
    createSession: (userId, tokenHash, expiresAt) => adapter.createSession(userId, tokenHash, expiresAt),
    findSession: (tokenHash) => adapter.findSession(tokenHash),
    deleteSession: (tokenHash) => adapter.deleteSession(tokenHash),
    touchSession: (tokenHash, expiresAt) => adapter.touchSession(tokenHash, expiresAt),

    async searchCustomers({ q, dept, cls, subclass, page, pageSize }) {
      const items = await adapter.aggregateCustomers({ q, dept, cls, subclass, limit: 10000 });
      return paginate(items, page, pageSize);
    },

    async searchProducts({ q, dept, cls, subclass, page, pageSize }) {
      const items = await adapter.aggregateProducts({ q, dept, cls, subclass, limit: 10000 });
      return paginate(items, page, pageSize);
    },

    async searchOrders({ q, direction, dept, cls, subclass, page, pageSize }) {
      const params = { q, direction, dept, cls, subclass };
      const total = await adapter.countOrderRows(params);
      const rows = await adapter.queryOrderRows({ ...params, limit: pageSize });
      return { items: rows, total };
    },

    async getCustomer(name) {
      const summary = await adapter.customerSummary(name);
      if (!summary) return null;
      const orders = await adapter.queryOrderRows({ customerNorm: normalizeThai(name), limit: 10000 });
      const uniqueOrders = new Set(orders.map((o) => o.order_number).filter(Boolean));
      const uniqueItems = new Set(orders.map((o) => o.item_id).filter(Boolean));
      return {
        ...summary,
        order_count: uniqueOrders.size || summary.order_count,
        product_count: uniqueItems.size || summary.product_count,
        orders
      };
    },

    async getProduct(itemId) {
      const summary = await adapter.productSummary(itemId);
      if (!summary) return null;
      const rows = await adapter.queryOrderRows({ itemId, limit: 10000 });
      return { ...summary, customers: [...new Set(rows.map((r) => r.customer_name))] };
    },

    listFilters: (p) => adapter.listFilters(p),
    getStats: () => adapter.getStats(),
    importRows: (p) => adapter.importRows(p),
    listImports: (limit) => adapter.listImports(limit),
    clearAll: () => adapter.clearAll()
  };
}