import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { ok, fail, readJson, setCookie } from '../_lib/http.js';
import { verifyPassword } from '../_lib/passwords.js';
import { issueSession } from '../_lib/auth.js';
import { limiter } from '../_lib/ratelimit.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  if (!limiter.allow(req)) return fail(res, 429, 'rate_limited', 'ลองใหม่ในอีกสักครู่');
  const repo = createRepository(getAdapter());
  const body = await readJson(req);
  const username = String(body.username ?? '').trim();
  const password = String(body.password ?? '');
  if (!username || !password) return fail(res, 400, 'validation_error', 'กรุณากรอกชื่อผู้ใช้และรหัสผ่าน');
  const user = await repo.findUserByUsername(username);
  if (!user || !user.active || !verifyPassword(password, user.password_hash)) {
    limiter.record(req);
    return fail(res, 401, 'unauthorized', 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูก');
  }
  const token = await issueSession(repo, user.id);
  setCookie(res, 'sid', token, {
    httpOnly: true, sameSite: 'Lax', secure: process.env.NODE_ENV === 'production', path: '/', maxAge: 7 * 24 * 3600
  });
  return ok(res, { user: { id: user.id, username: user.username, role: user.role } });
}
