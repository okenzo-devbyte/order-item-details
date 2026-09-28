import { randomBytes, createHash } from 'node:crypto';
import { getCookie, fail } from './http.js';

export function hashToken(token) {
  return createHash('sha256').update(token).digest('hex');
}

export function newToken() {
  return randomBytes(32).toString('base64url');
}

export async function issueSession(repo, userId, ttlMs = 7 * 24 * 3600 * 1000) {
  const token = newToken();
  await repo.createSession(userId, hashToken(token), new Date(Date.now() + ttlMs));
  return token;
}

export async function requireAuth(req, res, repo, refreshMs = 6 * 3600 * 1000, ttlMs = 7 * 24 * 3600 * 1000) {
  const token = getCookie(req, 'sid');
  if (!token) {
    fail(res, 401, 'unauthorized', 'กรุณาเข้าสู่ระบบก่อน');
    return null;
  }
  const session = await repo.findSession(hashToken(token));
  if (!session || session.expires_at <= new Date()) {
    if (session) await repo.deleteSession(hashToken(token));
    fail(res, 401, 'unauthorized', 'เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่');
    return null;
  }
  if (!session.active) {
    fail(res, 403, 'forbidden', 'บัญชีถูกปิด');
    return null;
  }
  if (session.expires_at.getTime() - Date.now() < refreshMs) {
    await repo.touchSession(hashToken(token), new Date(Date.now() + ttlMs));
  }
  return { id: session.user_id, username: session.username, role: session.role };
}

export function requireRole(role) {
  return (user, res) => {
    if (user.role !== role) {
      fail(res, 403, 'forbidden', 'ไม่มีสิทธิ์เข้าถึง');
      return false;
    }
    return true;
  };
}
