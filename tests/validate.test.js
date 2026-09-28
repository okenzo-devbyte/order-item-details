import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDate, parseExpectedRange, parseSearchQuery, validateImportRows } from '../api/_lib/validate.js';

test('parseDate accepts dd-Mon-yyyy', () => {
  assert.equal(parseDate('28-Sep-2026'), '2026-09-28');
  assert.equal(parseDate('03-Oct-2026'), '2026-10-03');
  assert.equal(parseDate('31-Feb-2026'), null);
  assert.equal(parseDate('garbage'), null);
});

test('parseExpectedRange splits on dash', () => {
  const r = parseExpectedRange('28-Sep-2026 - 28-Sep-2026');
  assert.deepEqual(r, { from: '2026-09-28', to: '2026-09-28', raw: '28-Sep-2026 - 28-Sep-2026' });
  assert.equal(parseExpectedRange('nope'), null);
});

test('parseSearchQuery defaults and bounds', () => {
  const q = parseSearchQuery({});
  assert.equal(q.direction, 'customer');
  assert.equal(q.page, 1);
  assert.equal(q.pageSize, 50);
  const big = parseSearchQuery({ page_size: '9999', q: 'x'.repeat(200) });
  assert.equal(big.pageSize, 100);
  assert.equal(big.errors.length, 1);
  assert.equal(big.errors[0].field, 'q');
});

test('validateImportRows rejects missing headers', () => {
  const bad = validateImportRows([{ 'Item Id': '1' }]);
  assert.ok(bad.fatal.some((e) => e.field === '_headers'));
});

test('validateImportRows flags duplicate keys as skipped', () => {
  const mk = () => ({ 'Order Number': 'A', 'Item Id': '1', 'Store Code': '106', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P', 'Item Remark': '', 'VIP Customer Remarks': '', 'VIP Customer Groups': '' });
  const res = validateImportRows([mk(), mk()]);
  assert.equal(res.fatal.length, 0);
  assert.equal(res.skipped.length, 1);
  assert.equal(res.skipped[0].field, 'Order Number');
});

test('validateImportRows flags blank Item Id as skipped', () => {
  const rows = [
    { 'Order Number': 'A', 'Item Id': '', 'Store Code': '106', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P', 'Item Remark': '', 'VIP Customer Remarks': '', 'VIP Customer Groups': '' }
  ];
  const res = validateImportRows(rows);
  assert.equal(res.fatal.length, 0);
  assert.equal(res.skipped.length, 1);
  assert.equal(res.skipped[0].field, 'Item Id');
  assert.equal(rows[0]._skip, true);
});

test('validateImportRows passes clean rows and adds _from/_to', () => {
  const rows = [
    { 'Order Number': 'A', 'Item Id': '1', 'Store Code': '106', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P', 'Item Remark': '', 'VIP Customer Remarks': '', 'VIP Customer Groups': '' }
  ];
  const res = validateImportRows(rows);
  assert.equal(res.fatal.length, 0);
  assert.equal(res.skipped.length, 0);
  assert.equal(rows[0]._from, '2026-09-28');
  assert.equal(rows[0]._to, '2026-09-28');
});
