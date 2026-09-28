export function json(res, status, body) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(body));
}

export function ok(res, data) {
  json(res, 200, { ok: true, data });
}

export function fail(res, status, code, message) {
  json(res, status, { ok: false, error: { code, message } });
}

export async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  return Buffer.concat(chunks).toString('utf-8');
}

export async function readJson(req) {
  // Vercel pre-parses JSON bodies into req.body; tests pass plain objects too.
  if (req.body !== undefined) {
    if (typeof req.body === 'string') {
      try { return JSON.parse(req.body); } catch { return {}; }
    }
    if (Buffer.isBuffer(req.body)) {
      try { return JSON.parse(req.body.toString('utf-8')); } catch { return {}; }
    }
    if (typeof req.body === 'object' && req.body !== null) return req.body;
  }
  const raw = await readBody(req);
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function getCookie(req, name) {
  const header = req.headers.cookie || '';
  for (const part of header.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const key = part.slice(0, idx).trim();
    if (key === name) return decodeURIComponent(part.slice(idx + 1).trim());
  }
  return null;
}

export function setCookie(res, name, value, opts = {}) {
  const parts = [`${name}=${value}`];
  if (opts.httpOnly) parts.push('HttpOnly');
  if (opts.sameSite) parts.push(`SameSite=${opts.sameSite}`);
  if (opts.secure) parts.push('Secure');
  if (opts.path) parts.push(`Path=${opts.path}`);
  if (opts.maxAge) parts.push(`Max-Age=${opts.maxAge}`);
  res.setHeader('Set-Cookie', parts.join('; '));
}
