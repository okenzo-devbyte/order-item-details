import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { requireAuth, requireRole } from '../_lib/auth.js';
import { importsHandler } from '../_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  if (!requireRole('admin')(user, res)) return;
  return importsHandler(req, res, repo);
}
