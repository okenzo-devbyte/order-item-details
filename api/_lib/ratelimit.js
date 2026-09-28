const buckets = new Map();
const WINDOW_MS = 5 * 60 * 1000;
const MAX = 10;

export function clientIp(req) {
  const fwd = req.headers['x-forwarded-for'];
  return fwd ? fwd.split(',')[0].trim() : (req.headers['x-real-ip'] || 'local');
}

export function loginLimiter() {
  return {
    allow(req) {
      const key = clientIp(req);
      const now = Date.now();
      const b = buckets.get(key);
      if (!b || now - b.start > WINDOW_MS) {
        buckets.set(key, { start: now, count: 0 });
        return true;
      }
      return b.count < MAX;
    },
    record(req) {
      const key = clientIp(req);
      const now = Date.now();
      const b = buckets.get(key);
      if (!b || now - b.start > WINDOW_MS) buckets.set(key, { start: now, count: 0 });
      buckets.get(key).count++;
    }
  };
}

export const limiter = loginLimiter();
