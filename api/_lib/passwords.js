import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';

const N = 16384, R = 8, P = 1, KEY_LEN = 32;

export function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = scryptSync(password, salt, KEY_LEN, { N, r: R, p: P });
  return `scrypt$N=${N},r=${R},p=${P}$` + salt.toString('base64') + '$' + hash.toString('base64');
}

export function verifyPassword(password, stored) {
  const parts = String(stored ?? '').split('$');
  if (parts.length !== 4 || parts[0] !== 'scrypt') return false;
  const params = Object.fromEntries(parts[1].split(',').map((kv) => kv.split('=')));
  const salt = Buffer.from(parts[2], 'base64');
  const expected = Buffer.from(parts[3], 'base64');
  if (expected.length === 0) return false;
  const actual = scryptSync(password, salt, expected.length, { N: +params.N, r: +params.r, p: +params.p });
  return timingSafeEqual(actual, expected);
}
