import { normalizeThai } from '../normalize.js';

export function createSupabaseAdapter(sb) {
  return {
    async queryOrderRows({ q, direction, dept, cls, subclass, customerNorm, itemId, limit }) {
      let b = sb.from('order_items').select('*');
      if (customerNorm) b = b.eq('customer_norm', customerNorm);
      else if (itemId) b = b.eq('item_id', itemId);
      else if (q) {
        const norm = normalizeThai(q);
        b = b.ilike(direction === 'product' ? 'product_norm' : 'customer_norm', `%${norm}%`);
      }
      if (dept) b = b.eq('dept', dept);
      if (cls) b = b.eq('class', cls);
      if (subclass) b = b.eq('subclass', subclass);
      if (limit) b = b.limit(limit);
      const { data, error } = await b;
      if (error) throw new Error(`queryOrderRows: ${error.message}`);
      return data;
    },

    async countOrderRows(params) {
      let b = sb.from('order_items').select('*', { count: 'exact', head: true });
      if (params.customerNorm) b = b.eq('customer_norm', params.customerNorm);
      else if (params.itemId) b = b.eq('item_id', params.itemId);
      else if (params.q) {
        const norm = normalizeThai(params.q);
        b = b.ilike(params.direction === 'product' ? 'product_norm' : 'customer_norm', `%${norm}%`);
      }
      if (params.dept) b = b.eq('dept', params.dept);
      if (params.cls) b = b.eq('class', params.cls);
      if (params.subclass) b = b.eq('subclass', params.subclass);
      const { count, error } = await b;
      if (error) throw new Error(`countOrderRows: ${error.message}`);
      return count;
    },

    async listFilters({ dept, cls }) {
      const out = { depts: [], classes: [], subclasses: [] };
      const d = await sb.from('order_items').select('dept').order('dept').limit(1000);
      if (d.error) throw new Error(`listFilters depts: ${d.error.message}`);
      out.depts = [...new Set(d.data.map((r) => r.dept))];
      let c = sb.from('order_items').select('class').order('class').limit(1000);
      if (dept) c = c.eq('dept', dept);
      const cr = await c;
      if (cr.error) throw new Error(`listFilters classes: ${cr.error.message}`);
      out.classes = [...new Set(cr.data.map((r) => r.class))];
      let s = sb.from('order_items').select('subclass').order('subclass').limit(1000);
      if (dept) s = s.eq('dept', dept);
      if (cls) s = s.eq('class', cls);
      const sr = await s;
      if (sr.error) throw new Error(`listFilters subclasses: ${sr.error.message}`);
      out.subclasses = [...new Set(sr.data.map((r) => r.subclass))];
      return out;
    },

    async getStats() {
      const o = await sb.from('order_items').select('*', { count: 'exact', head: true });
      if (o.error) throw new Error(`getStats orders: ${o.error.message}`);
      const d = await sb.from('order_items').select('customer_norm,item_id,dept,class,subclass').limit(10000);
      if (d.error) throw new Error(`getStats distincts: ${d.error.message}`);
      const imp = await sb.from('imports').select('imported_at').order('imported_at', { ascending: false }).limit(1);
      if (imp.error) throw new Error(`getStats imports: ${imp.error.message}`);
      return {
        order_count: o.count,
        customer_count: new Set(d.data.map((r) => r.customer_norm)).size,
        product_count: new Set(d.data.map((r) => r.item_id)).size,
        group_count: new Set(d.data.map((r) => `${r.dept}|${r.class}|${r.subclass}`)).size,
        last_import: imp.data.length ? imp.data[0].imported_at : null
      };
    },

    async importRows({ filename, mode, rows, importedBy }) {
      const fn = mode === 'replace' ? 'replace_all' : 'append_rows';
      const { data, error } = await sb.rpc(fn, { p_rows: rows, p_filename: filename, p_imported_by: importedBy });
      if (error) throw new Error(`importRows: ${error.message}`);
      return { row_count: data.row_count, warnings: [] };
    },

    async listImports(limit = 50) {
      const { data, error } = await sb.from('imports').select('*').order('imported_at', { ascending: false }).limit(limit);
      if (error) throw new Error(`listImports: ${error.message}`);
      return data;
    },

    async clearAll() {
      const { error } = await sb.from('order_items').delete().neq('id', 0);
      if (error) throw new Error(`clearAll: ${error.message}`);
    },

    async findUserByUsername(username) {
      const { data, error } = await sb.from('users').select('*').eq('username', username).limit(1);
      if (error) throw new Error(`findUserByUsername: ${error.message}`);
      return data.length ? data[0] : null;
    },

    async createSession(userId, tokenHash, expiresAt) {
      const { error } = await sb.from('sessions').insert({ token_hash: tokenHash, user_id: userId, expires_at: expiresAt.toISOString() });
      if (error) throw new Error(`createSession: ${error.message}`);
    },

    async findSession(tokenHash) {
      const { data, error } = await sb.from('sessions').select('token_hash,user_id,expires_at,users!inner(username,role,active)').eq('token_hash', tokenHash).limit(1);
      if (error) throw new Error(`findSession: ${error.message}`);
      if (!data.length) return null;
      const s = data[0];
      return { user_id: s.user_id, username: s.users.username, role: s.users.role, active: s.users.active, expires_at: new Date(s.expires_at) };
    },

    async deleteSession(tokenHash) {
      const { error } = await sb.from('sessions').delete().eq('token_hash', tokenHash);
      if (error) throw new Error(`deleteSession: ${error.message}`);
    },

    async touchSession(tokenHash, expiresAt) {
      const { error } = await sb.from('sessions').update({ expires_at: expiresAt.toISOString() }).eq('token_hash', tokenHash);
      if (error) throw new Error(`touchSession: ${error.message}`);
    }
  };
}
