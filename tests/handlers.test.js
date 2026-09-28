import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { hashPassword } from '../api/_lib/passwords.js';
import { issueSession, requireAuth, hashToken } from '../api/_lib/auth.js';
import { getCookie, setCookie } from '../api/_lib/http.js';

function makeReqRes() {
  const req = { method: 'GET', headers: {}, body: '' };
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  return { req, res };
}

function repo() {
  const a = createMemoryAdapter();
  a.seedUser({ username: 'admin', password_hash: hashPassword('pw'), role: 'admin', active: true });
  a.seedUser({ username: 'viewer', password_hash: hashPassword('pw'), role: 'viewer', active: true });
  return createRepository(a);
}

test('issueSession + requireAuth roundtrip', async () => {
  const r = repo();
  const user = await r.findUserByUsername('admin');
  const token = await issueSession(r, user.id);
  const { req, res } = makeReqRes();
  setCookie(res, 'sid', token, { httpOnly: true, path: '/' });
  req.headers.cookie = res.headers['Set-Cookie'].split(';')[0];
  const got = await requireAuth(req, res, r);
  assert.equal(got.username, 'admin');
  assert.equal(got.role, 'admin');
});

test('requireAuth rejects missing cookie', async () => {
  const r = repo();
  const { req, res } = makeReqRes();
  const got = await requireAuth(req, res, r);
  assert.equal(got, null);
  assert.equal(res.statusCode, 401);
});

test('requireAuth rejects expired session', async () => {
  const r = repo();
  const user = await r.findUserByUsername('admin');
  const token = await issueSession(r, user.id);
  const { req, res } = makeReqRes();
  setCookie(res, 'sid', token, { path: '/' });
  req.headers.cookie = res.headers['Set-Cookie'].split(';')[0];
  await r.touchSession(hashToken(token), new Date(Date.now() - 1000));
  const got = await requireAuth(req, res, r);
  assert.equal(got, null);
  assert.equal(res.statusCode, 401);
});

test('getCookie parses header', () => {
  const { req } = makeReqRes();
  req.headers.cookie = 'a=1; sid=abc%2Bdef; b=2';
  assert.equal(getCookie(req, 'sid'), 'abc+def');
});

function makeUrlReq(url) {
  const { req, res } = makeReqRes();
  req.url = url;
  return { req, res };
}

function seedRows() {
  const a = createMemoryAdapter();
  a.seedOrderItems([
    { order_number: 'A1', item_id: '1', product_name: 'P1', customer_name: 'สุนีย์', expected_from: '2026-09-28', expected_to: '2026-09-28', dept: 8, class: 312, subclass: 29 },
    { order_number: 'A2', item_id: '2', product_name: 'P2', customer_name: 'สุนีย์', expected_from: '2026-09-21', expected_to: '2026-09-21', dept: 8, class: 696, subclass: 12 }
  ]);
  return createRepository(a);
}

test('search handler returns grouped customers', async () => {
  const { searchHandler } = await import('../api/_lib/handlers.js');
  const r = seedRows();
  const { req, res } = makeUrlReq('/api/search?direction=customer&q=' + encodeURIComponent('สุนีย์'));
  await searchHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, true);
  assert.equal(body.data.total, 1);
  assert.equal(body.data.items[0].order_count, 2);
});

test('search handler validates bad params', async () => {
  const { searchHandler } = await import('../api/_lib/handlers.js');
  const r = seedRows();
  const { req, res } = makeUrlReq('/api/search?dept=abc');
  await searchHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, false);
  assert.equal(body.error.code, 'validation_error');
});

test('customer handler returns 404 for unknown', async () => {
  const { customerHandler } = await import('../api/_lib/handlers.js');
  const r = seedRows();
  const { req, res } = makeUrlReq('/api/customer?name=' + encodeURIComponent('ไม่มี'));
  await customerHandler(req, res, r);
  assert.equal(JSON.parse(res.body).error.code, 'not_found');
});
