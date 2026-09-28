import { createRepository } from './_lib/repository.js';
import { getAdapter } from './_lib/adapters/index.js';
import { requireAuth } from './_lib/auth.js';
import { customerHandler } from './_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return customerHandler(req, res, repo);
}
