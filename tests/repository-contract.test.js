import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { hashPassword } from '../api/_lib/passwords.js';

function seed() {
  const a = createMemoryAdapter();
  a.seedOrderItems([
    { order_number: 'A1', item_id: '146454', product_name: 'เด็กสมบูรณ์ ซีอิ๊วขาว', customer_name: 'สุนีย์ บุญมี', expected_from: '2026-09-28', expected_to: '2026-09-28', dept: 8, class: 312, subclass: 29, vip_customer_groups: 'Platinum' },
    { order_number: 'A2', item_id: '840325', product_name: 'อัมพวา กะทิขวด', customer_name: 'สุนีย์ บุญมี', expected_from: '2026-09-21', expected_to: '2026-09-21', dept: 8, class: 696, subclass: 12, vip_customer_groups: 'Gold' },
    { order_number: 'B1', item_id: '146454', product_name: 'เด็กสมบูรณ์ ซีอิ๊วขาว', customer_name: 'รัตนา ทองดี', expected_from: '2026-10-03', expected_to: '2026-10-03', dept: 8, class: 312, subclass: 29, vip_customer_groups: 'Silver' }
  ]);
  a.seedUser({ username: 'admin', password_hash: hashPassword('pw'), role: 'admin', active: true });
  return createRepository(a);
}

test('searchCustomers groups by customer with counts and vip', async () => {
  const repo = seed();
  const res = await repo.searchCustomers({ q: 'สุนีย์', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(res.total, 1);
  const c = res.items[0];
  assert.equal(c.customer_name, 'สุนีย์ บุญมี');
  assert.equal(c.order_count, 2);
  assert.equal(c.product_count, 2);
  assert.deepEqual(c.vip_groups.sort(), ['Gold', 'Platinum']);
  assert.equal(c.groups.length, 2);
});

test('searchProducts groups by item', async () => {
  const repo = seed();
  const res = await repo.searchProducts({ q: 'กะทิ', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(res.total, 1);
  assert.equal(res.items[0].item_id, '840325');
  assert.equal(res.items[0].customer_count, 1);
});

test('searchOrders returns flat rows with pagination', async () => {
  const repo = seed();
  const res = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 2 });
  assert.equal(res.total, 3);
  assert.equal(res.items.length, 2);
});

test('getCustomer aggregates one customer', async () => {
  const repo = seed();
  const c = await repo.getCustomer('สุนีย์ บุญมี');
  assert.equal(c.order_count, 2);
  assert.equal(c.orders.length, 2);
});

test('getCustomer ignores spacing differences', async () => {
  const repo = seed();
  const c = await repo.getCustomer('สุนีย์บุญมี');
  assert.equal(c.order_count, 2);
});

test('getProduct lists customers', async () => {
  const repo = seed();
  const p = await repo.getProduct('146454');
  assert.equal(p.customer_count, 2);
  assert.equal(p.customers.length, 2);
});

test('filters cascade', async () => {
  const repo = seed();
  const f = await repo.listFilters({ dept: 8, cls: null });
  assert.deepEqual(f.depts, [8]);
  assert.deepEqual(f.classes, [312, 696]);
  assert.deepEqual(f.subclasses, [12, 29]);
});

test('import replace then clear', async () => {
  const repo = seed();
  const rows = [
    { 'Order Number': 'X1', 'Item Id': '9', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': '01-Jan-2026 - 01-Jan-2026', '_from': '2026-01-01', '_to': '2026-01-01', 'Dept': '1', 'Class': '2', 'Subclass': '3' }
  ];
  const r = await repo.importRows({ filename: 't.xlsx', mode: 'replace', rows, importedBy: 'admin' });
  assert.equal(r.row_count, 1);
  const after = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(after.total, 1);
  await repo.clearAll();
  const cleared = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(cleared.total, 0);
});

test('auth: session lifecycle', async () => {
  const repo = seed();
  const user = await repo.findUserByUsername('admin');
  assert.ok(user);
  const tokenHash = 'abc123';
  await repo.createSession(user.id, tokenHash, new Date(Date.now() + 10000));
  const s = await repo.findSession(tokenHash);
  assert.equal(s.username, 'admin');
  assert.equal(s.role, 'admin');
  await repo.deleteSession(tokenHash);
  assert.equal(await repo.findSession(tokenHash), null);
});
