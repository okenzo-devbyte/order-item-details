// Local dev server (no Vercel CLI needed).
// Serves public/ statically and routes /api/* to the same handlers Vercel uses.
// Usage: node scripts/dev-server.js [port]   (default 3000)
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadDotEnv } from '../api/_lib/config.js';

const ROOT = join(fileURLToPath(new URL('.', import.meta.url)), '..');
loadDotEnv(ROOT);
const PUBLIC = join(ROOT, 'public');
const PORT = Number(process.argv[2] || process.env.PORT || 3000);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.webmanifest': 'application/manifest+json'
};

// Whitelist: only these files may be loaded as API handlers.
const API_ROUTES = new Set([
  'auth/login', 'auth/logout', 'auth/me',
  'search', 'search/orders', 'customer', 'product', 'filters', 'stats',
  'admin/import', 'admin/imports', 'admin/clear'
]);

const cache = new Map();
async function getHandler(route) {
  if (!cache.has(route)) {
    const mod = await import(`../api/${route}.js`);
    cache.set(route, mod.default);
  }
  return cache.get(route);
}

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://local');
    if (url.pathname.startsWith('/api/')) {
      const route = url.pathname.slice('/api/'.length);
      if (!API_ROUTES.has(route)) {
        res.statusCode = 404;
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.end(JSON.stringify({ ok: false, error: { code: 'not_found', message: 'ไม่พบเส้นทางนี้' } }));
        return;
      }
      await (await getHandler(route))(req, res);
      return;
    }
    const rel = url.pathname === '/' ? 'index.html' : decodeURIComponent(url.pathname.slice(1));
    const safe = normalize(rel).replace(/^(\.\.[\\/])+/, '');
    const full = join(PUBLIC, safe);
    if (!full.startsWith(PUBLIC + sep) && full !== join(PUBLIC, 'index.html')) {
      res.statusCode = 403;
      res.end('forbidden');
      return;
    }
    const body = await readFile(full);
    res.statusCode = 200;
    res.setHeader('Content-Type', MIME[extname(full)] || 'application/octet-stream');
    res.end(body);
  } catch (err) {
    if (err.code === 'ENOENT') {
      res.statusCode = 404;
      res.end('not found');
      return;
    }
    console.error(err);
    if (!res.headersSent) {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.end(JSON.stringify({ ok: false, error: { code: 'internal', message: 'เกิดข้อผิดพลาดในระบบ' } }));
    }
  }
});

server.listen(PORT, () => {
  console.log(`dev server: http://localhost:${PORT}`);
});
