import { normalizeThai } from '../normalize.js';

export function createMemoryAdapter() {
  const state = { orderItems: [], users: [], sessions: [], imports: [] };
  let nextId = 1;

  const adapter = {
    _state: state,

    seedOrderItems(rows) {
      state.orderItems = rows.map((r) => ({
        id: nextId++,
        order_number: r.order_number,
        store_code: r.store_code,
        item_id: r.item_id,
        product_name: r.product_name,
        product_norm: normalizeThai(r.product_name),
        customer_name: r.customer_name,
        customer_norm: normalizeThai(r.customer_name),
        expected_from: r.expected_from,
        expected_to: r.expected_to,
        expected_raw: r.expected_raw,
        dept: r.dept,
        class: r.class,
        subclass: r.subclass,
        item_remark: r.item_remark,
        vip_customer_remarks: r.vip_customer_remarks,
        vip_customer_groups: r.vip_customer_groups
      }));
    },

    seedUser(u) {
      state.users.push({ id: `u${state.users.length + 1}`, username: u.username, password_hash: u.password_hash, role: u.role, active: u.active });
    },

    async queryOrderRows({ q, direction, dept, cls, subclass, customerNorm, itemId, limit }) {
      let rows = state.orderItems;
      if (customerNorm) rows = rows.filter((r) => r.customer_norm === customerNorm);
      else if (itemId) rows = rows.filter((r) => r.item_id === itemId);
      else if (q) {
        const norm = normalizeThai(q);
        rows = rows.filter((r) => (direction === 'product' ? r.product_norm : r.customer_norm).includes(norm));
      }
      if (dept) rows = rows.filter((r) => r.dept === dept);
      if (cls) rows = rows.filter((r) => r.class === cls);
      if (subclass) rows = rows.filter((r) => r.subclass === subclass);
      if (limit) rows = rows.slice(0, limit);
      return rows;
    },

    async countOrderRows(params) {
      return (await adapter.queryOrderRows(params)).length;
    },

    async listFilters({ dept, cls }) {
      const rows = state.orderItems;
      const depts = [...new Set(rows.map((r) => r.dept))].sort();
      const classes = [...new Set(rows.filter((r) => !dept || r.dept === dept).map((r) => r.class))].sort();
      const subclasses = [...new Set(rows.filter((r) => (!dept || r.dept === dept) && (!cls || r.class === cls)).map((r) => r.subclass))].sort();
      return { depts, classes, subclasses };
    },

    async getStats() {
      const rows = state.orderItems;
      return {
        order_count: rows.length,
        customer_count: new Set(rows.map((r) => r.customer_norm)).size,
        product_count: new Set(rows.map((r) => r.item_id)).size,
        group_count: new Set(rows.map((r) => `${r.dept}|${r.class}|${r.subclass}`)).size,
        last_import: state.imports.length ? state.imports[state.imports.length - 1].imported_at : null
      };
    },

    async importRows({ filename, mode, rows, importedBy }) {
      if (mode === 'replace') state.orderItems = [];
      const mapped = rows.map((r) => ({
        id: nextId++,
        order_number: String(r['Order Number'] ?? '').trim(),
        store_code: r['Store Code'] === undefined ? null : String(r['Store Code']).trim(),
        item_id: String(r['Item Id'] ?? '').trim(),
        product_name: String(r['Product Name'] ?? '').trim(),
        product_norm: normalizeThai(r['Product Name']),
        customer_name: String(r['Customer Name'] ?? '').trim(),
        customer_norm: normalizeThai(r['Customer Name']),
        expected_from: r._from,
        expected_to: r._to,
        expected_raw: r['Original Expected Date'],
        dept: r['Dept'] === '' || r['Dept'] === undefined ? null : Number(r['Dept']),
        class: r['Class'] === '' || r['Class'] === undefined ? null : Number(r['Class']),
        subclass: r['Subclass'] === '' || r['Subclass'] === undefined ? null : Number(r['Subclass']),
        item_remark: r['Item Remark'] === undefined ? null : String(r['Item Remark']),
        vip_customer_remarks: r['VIP Customer Remarks'] === undefined ? null : String(r['VIP Customer Remarks']),
        vip_customer_groups: r['VIP Customer Groups'] === undefined ? null : String(r['VIP Customer Groups'])
      }));
      state.orderItems.push(...mapped);
      state.imports.push({ id: nextId++, filename, mode, row_count: mapped.length, imported_by: importedBy, imported_at: new Date().toISOString() });
      return { row_count: mapped.length, warnings: [] };
    },

    async listImports(limit = 50) {
      return state.imports.slice(-limit).reverse();
    },

    async clearAll() {
      state.orderItems = [];
    },

    async findUserByUsername(username) {
      return state.users.find((u) => u.username === username);
    },

    async createSession(userId, tokenHash, expiresAt) {
      state.sessions.push({ token_hash: tokenHash, user_id: userId, expires_at: expiresAt, created_at: new Date() });
    },

    async findSession(tokenHash) {
      const s = state.sessions.find((x) => x.token_hash === tokenHash);
      if (!s) return null;
      const u = state.users.find((x) => x.id === s.user_id);
      if (!u) return null;
      return { user_id: u.id, username: u.username, role: u.role, active: u.active, expires_at: s.expires_at };
    },

    async deleteSession(tokenHash) {
      state.sessions = state.sessions.filter((x) => x.token_hash !== tokenHash);
    },

    async touchSession(tokenHash, expiresAt) {
      const s = state.sessions.find((x) => x.token_hash === tokenHash);
      if (s) s.expires_at = expiresAt;
    }
  };

  return adapter;
}
