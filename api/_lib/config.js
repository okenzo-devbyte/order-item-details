const REQUIRED = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'SESSION_SECRET'];

export function loadConfig(env = process.env) {
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
