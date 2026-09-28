// Runs ONLY when real Supabase env vars are present; skipped otherwise.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const hasEnv = Boolean(process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY && process.env.SESSION_SECRET);

test('supabase adapter: getStats shape', { skip: !hasEnv }, async () => {
  const { getAdapter } = await import('../api/_lib/adapters/index.js');
  const { createRepository } = await import('../api/_lib/repository.js');
  const repo = createRepository(getAdapter());
  const stats = await repo.getStats();
  assert.ok(typeof stats.order_count === 'number');
  assert.ok(typeof stats.customer_count === 'number');
  assert.ok(typeof stats.product_count === 'number');
  assert.ok(typeof stats.group_count === 'number');
});
