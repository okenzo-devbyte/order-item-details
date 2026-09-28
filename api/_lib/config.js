import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const REQUIRED = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SESSION_SECRET'];

// Minimal .env loader (no dependency). Fills only keys missing from process.env,
// so real environment variables (e.g. injected by Vercel) always win.
export function loadDotEnv(cwd = process.cwd()) {
  const path = join(cwd, '.env');
  if (!existsSync(path)) return;
  const text = readFileSync(path, 'utf-8');
  for (const line of text.split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const idx = t.indexOf('=');
    if (idx === -1) continue;
    const key = t.slice(0, idx).trim();
    let val = t.slice(idx + 1).trim();
    if (val.length >= 2 && ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'")))) {
      val = val.slice(1, -1);
    }
    if (key && !(key in process.env)) process.env[key] = val;
  }
}

export function loadConfig(env = process.env) {
  if (env === process.env) loadDotEnv();
  const missing = REQUIRED.filter((k) => !env[k]);
  if (missing.length) throw new Error(`Missing env vars: ${missing.join(', ')}`);
  return {
    supabaseUrl: env.SUPABASE_URL,
    supabaseKey: env.SUPABASE_SERVICE_ROLE_KEY,
    sessionSecret: env.SESSION_SECRET,
    sessionTtlMs: 7 * 24 * 60 * 60 * 1000,
    sessionRefreshMs: 6 * 60 * 60 * 1000
  };
}
