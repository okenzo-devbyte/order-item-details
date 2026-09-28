import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { importHandler, clearHandler, importsHandler } from '../api/_lib/handlers.js';
import { requireRole } from '../api/_lib/auth.js';

function makePostReq(url, body) {
  const req = { method: 'POST', headers: {}, body: JSON.stringify(body), url, user: { username: 'admin', role: 'admin' } };
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  return { req, res };
}

test('import handler validates then imports', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  const rows = [
    { 'Order Number': 'A', 'Item Id': '1', 'Store Code': '106', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Item Remark': '', 'VIP Customer Remarks': '', 'VIP Customer Groups': '' }
  ];
  const { req, res } = makePostReq('/api/admin/import?mode=replace&filename=t.xlsx', { rows });
  await importHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, true);
  assert.equal(body.data.row_count, 1);
  const stats = await r.getStats();
  assert.equal(stats.order_count, 1);
});

test('import handler rejects invalid rows without touching data', async () => {
  const a = createMemoryAdapter();
  a.seedOrderItems([{ order_number: 'KEEP', item_id: '1', product_name: 'P', customer_name: 'C', expected_from: '2026-01-01', expected_to: '2026-01-01', dept: 1, class: 2, subclass: 3 }]);
  const r = createRepository(a);
  const rows = [{ 'Order Number': '', 'Item Id': '1', 'Store Code': '106', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': 'bad', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Item Remark': '', 'VIP Customer Remarks': '', 'VIP Customer Groups': '' }];
  const { req, res } = makePostReq('/api/admin/import?mode=replace&filename=t.xlsx', { rows });
  await importHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, false);
  assert.equal(body.error.code, 'bad_file');
  assert.equal((await r.getStats()).order_count, 1);
});

test('clear handler requires confirm', async () => {
  const a = createMemoryAdapter();
  a.seedOrderItems([{ order_number: 'X', item_id: '1', product_name: 'P', customer_name: 'C', expected_from: '2026-01-01', expected_to: '2026-01-01', dept: 1, class: 2, subclass: 3 }]);
  const r = createRepository(a);
  const bad = makePostReq('/api/admin/clear', {});
  await clearHandler(bad.req, bad.res, r);
  assert.equal(JSON.parse(bad.res.body).error.code, 'validation_error');
  const good = makePostReq('/api/admin/clear', { confirm: true });
  await clearHandler(good.req, good.res, r);
  assert.equal((await r.getStats()).order_count, 0);
});

test('imports handler lists history', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  await r.importRows({ filename: 'a.xlsx', mode: 'replace', rows: [], importedBy: 'admin' });
  const req = { method: 'GET', headers: {}, url: '/api/admin/imports' };
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  await importsHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.data.length, 1);
  assert.equal(body.data[0].filename, 'a.xlsx');
});

test('requireRole blocks viewer from admin', async () => {
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  const check = requireRole('admin');
  assert.equal(check({ role: 'viewer' }, res), false);
  assert.equal(res.statusCode, 403);
  assert.equal(check({ role: 'admin' }, res), true);
});
