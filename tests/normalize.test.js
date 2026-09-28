import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeThai } from '../api/_lib/normalize.js';

test('removes all whitespace and lowercases', () => {
  assert.equal(normalizeThai('เด็ก สมบูรณ์ ซีอิ๊วขาว'), 'เด็กสมบูรณ์ซีอิ๊วขาว');
  assert.equal(normalizeThai('  A B  C '), 'abc');
});

test('handles null/undefined', () => {
  assert.equal(normalizeThai(null), '');
  assert.equal(normalizeThai(undefined), '');
  assert.equal(normalizeThai(123), '123');
});
