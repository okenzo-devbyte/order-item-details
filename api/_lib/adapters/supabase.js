import { readFileSync, writeFileSync, existsSync, mkdirSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';
import { normalizeThai } from '../normalize.js';
import { aggregateProducts } from '../aggregate.js';

let _indexCache = null;
const CACHE_FILE = join(process.cwd(), '.cache', 'customer_index.json');

async function getOrBuildCustomerIndex(sb) {
  // 1. Get latest import timestamp to see if data changed
  const { data: imp } = await sb.from('imports').select('imported_at, row_count').order('imported_at', { ascending: false }).limit(1);
  const lastImport = imp?.[0]?.imported_at || null;

  if (_indexCache && _indexCache.lastImport === lastImport) {
    return _indexCache;
  }

  // 2. Try loading from disk cache
  if (existsSync(CACHE_FILE)) {
    try {
      const disk = JSON.parse(readFileSync(CACHE_FILE, 'utf-8'));
      if (disk && disk.lastImport === lastImport) {
        _indexCache = disk;
        return _indexCache;
      }
    } catch (_) {}
  }

  // 3. Build index by scanning order_items
  const byCust = new Map();
  const allItems = new Set();
  const allOrders = new Set();
  let totalRows = 0;
  let offset = 0;
  const CHUNK = 1000;

  while (true) {
    const { data, error } = await sb.from('order_items')
      .select('order_number, customer_name, customer_norm, item_id, expected_from, vip_customer_groups')
      .order('id', { ascending: true })
      .range(offset, offset + CHUNK - 1);
    if (error || !data || !data.length) break;

    totalRows += data.length;
    for (const r of data) {
      if (!r.customer_norm) continue;
      if (r.order_number) allOrders.add(r.order_number);
      if (r.item_id) allItems.add(r.item_id);

      let c = byCust.get(r.customer_norm);
      if (!c) {
        c = {
          customer_name: r.customer_name,
          customer_norm: r.customer_norm,
          orders: new Set(),
          items: new Set(),
          last_expected: null,
          vip: new Set()
        };
        byCust.set(r.customer_norm, c);
      }
      if (r.order_number) c.orders.add(r.order_number);
      if (r.item_id) c.items.add(r.item_id);
      if (r.vip_customer_groups) c.vip.add(r.vip_customer_groups);
      if (r.expected_from && (!c.last_expected || r.expected_from > c.last_expected)) {
        c.last_expected = r.expected_from;
      }
    }
    offset += data.length;
    if (data.length < CHUNK) break;
  }

  const customers = Array.from(byCust.values()).map((c) => ({
    customer_name: c.customer_name,
    customer_norm: c.customer_norm,
    order_count: c.orders.size,
    product_count: c.items.size,
    last_expected: c.last_expected,
    vip_groups: Array.from(c.vip)
  })).sort((a, b) => b.order_count - a.order_count);

  _indexCache = {
    lastImport,
    totalOrders: allOrders.size,
    totalRows,
    totalCustomers: customers.length,
    totalItems: allItems.size,
    customers
  };

  try {
    if (!existsSync(join(process.cwd(), '.cache'))) {
      mkdirSync(join(process.cwd(), '.cache'), { recursive: true });
    }
    writeFileSync(CACHE_FILE, JSON.stringify(_indexCache));
  } catch (_) {}

  return _indexCache;
}

function invalidateIndexCache() {
  _indexCache = null;
  try {
    if (existsSync(CACHE_FILE)) unlinkSync(CACHE_FILE);
  } catch (_) {}
}

export function createSupabaseAdapter(sb) {
  const adapter = {
    async queryOrderRows({ q, direction, dept, cls, subclass, customerNorm, itemId, limit }) {
      let b = sb.from('order_items').select('order_number, store_code, dept, class, item_id, product_name, expected_from');
      if (customerNorm) {
        b = b.eq('customer_norm', customerNorm);
      } else if (itemId) {
        b = b.eq('item_id', itemId);
      } else if (q) {
        const norm = normalizeThai(q);
        b = b.ilike('customer_norm', `%${norm}%`);
      }
      if (dept) b = b.eq('dept', dept);
      if (cls) b = b.eq('class', cls);
      if (subclass) b = b.eq('subclass', subclass);
      b = b.order('id', { ascending: false });
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
        b = b.ilike('customer_norm', `%${norm}%`);
      }
      if (params.dept) b = b.eq('dept', params.dept);
      if (params.cls) b = b.eq('class', params.cls);
      if (params.subclass) b = b.eq('subclass', params.subclass);
      const { count, error } = await b;
      if (error) throw new Error(`countOrderRows: ${error.message}`);
      return count;
    },

    async aggregateCustomers({ q }) {
      const idx = await getOrBuildCustomerIndex(sb);
      if (!q) return idx.customers;
      const norm = normalizeThai(q);
      return idx.customers.filter((c) => 
        c.customer_norm.includes(norm) || c.customer_name.toLowerCase().includes(norm)
      );
    },

    async aggregateProducts({ q, dept, cls, subclass, limit }) {
      const rows = await adapter.queryOrderRows({ q, direction: 'product', dept, cls, subclass, limit: limit || 1000 });
      return aggregateProducts(rows);
    },

    async customerSummary(name) {
      const idx = await getOrBuildCustomerIndex(sb);
      const norm = normalizeThai(name);
      const found = idx.customers.find((c) => c.customer_norm === norm);
      return found || null;
    },

    async productSummary(itemId) {
      const rows = await adapter.queryOrderRows({ itemId, limit: 1000 });
      if (!rows.length) return null;
      return aggregateProducts(rows)[0] || null;
    },

    async listFilters({ dept, cls }) {
      const out = { depts: [], classes: [], subclasses: [] };
      return out;
    },

    async getStats() {
      const idx = await getOrBuildCustomerIndex(sb);
      return {
        order_count: idx.totalOrders,
        customer_count: idx.totalCustomers,
        product_count: idx.totalItems,
        group_count: 0,
        last_import: idx.lastImport
      };
    },

    async importRows({ filename, mode = 'replace', rows, importedBy }) {
      // Always replace all existing rows in order_items
      const { error } = await sb.from('order_items').delete().neq('id', 0);
      if (error) throw new Error(`importRows clear: ${error.message}`);

      const formatted = rows.map((r) => ({
        order_number: String(r['Order Number'] || ''),
        store_code: r['Store Code'] || null,
        item_id: String(r['Item Id'] || ''),
        product_name: String(r['Product Name'] || ''),
        product_norm: String(r['Product Name'] || '').toLowerCase().replace(/\s+/g, ''),
        customer_name: String(r['Customer Name'] || ''),
        customer_norm: String(r['Customer Name'] || '').toLowerCase().replace(/\s+/g, ''),
        expected_from: r._from || null,
        expected_to: r._to || null,
        expected_raw: r['Original Expected Date'] || null,
        dept: r['Dept'] ? Number(r['Dept']) : null,
        class: r['Class'] ? Number(r['Class']) : null,
        subclass: r['Subclass'] ? Number(r['Subclass']) : null,
        item_remark: r['Item Remark'] || null,
        vip_customer_remarks: r['VIP Customer Remarks'] || null,
        vip_customer_groups: r['VIP Customer Groups'] || null
      }));

      const CHUNK_SIZE = 3000;
      let totalInserted = 0;
      for (let i = 0; i < formatted.length; i += CHUNK_SIZE) {
        const chunk = formatted.slice(i, i + CHUNK_SIZE);
        const { error } = await sb.from('order_items').insert(chunk);
        if (error) throw new Error(`importRows chunk: ${error.message}`);
        totalInserted += chunk.length;
      }

      const { error: logError } = await sb.from('imports').insert({
        filename, mode, row_count: totalInserted, imported_by: importedBy
      });
      if (logError) throw new Error(`importRows log: ${logError.message}`);

      invalidateIndexCache();
      return { row_count: totalInserted, warnings: [] };
    },

    async listImports(limit = 50) {
      const { data, error } = await sb.from('imports').select('*').order('imported_at', { ascending: false }).limit(limit);
      if (error) throw new Error(`listImports: ${error.message}`);
      return data;
    },

    async clearAll() {
      const { error } = await sb.from('order_items').delete().neq('id', 0);
      if (error) throw new Error(`clearAll: ${error.message}`);
      invalidateIndexCache();
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
  return adapter;
}
