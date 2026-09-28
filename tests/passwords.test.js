import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hashPassword, verifyPassword } from '../api/_lib/passwords.js';

test('hash then verify roundtrip', () => {
  const h = hashPassword('s3cret!');
  assert.ok(h.startsWith('scrypt$'));
  assert.ok(verifyPassword('s3cret!', h));
  assert.ok(!verifyPassword('wrong', h));
});

test('two hashes of same password differ (random salt)', () => {
  assert.notEqual(hashPassword('x'), hashPassword('x'));
});

test('verify rejects malformed stored hash', () => {
  assert.ok(!verifyPassword('x', 'not-a-hash'));
  assert.ok(!verifyPassword('x', 'scrypt$N=1,r=1,p=1$!!$!!'));
});
