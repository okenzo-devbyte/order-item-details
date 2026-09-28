import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { ok, fail, getCookie, setCookie } from '../_lib/http.js';
import { hashToken } from '../_lib/auth.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  const repo = createRepository(getAdapter());
  const token = getCookie(req, 'sid');
  if (token) await repo.deleteSession(hashToken(token));
  setCookie(res, 'sid', '', { httpOnly: true, sameSite: 'Lax', path: '/', maxAge: 0 });
  return ok(res, {});
}
