import { ok, fail, readJson } from './http.js';
import { parseSearchQuery, validateImportRows } from './validate.js';

function queryOf(req) {
  const url = new URL(req.url, 'http://local');
  return Object.fromEntries(url.searchParams.entries());
}

export async function searchHandler(req, res, repo) {
  const p = parseSearchQuery(queryOf(req));
  if (p.errors.length) return fail(res, 400, 'validation_error', p.errors[0].message);
  const data = p.direction === 'product'
    ? await repo.searchProducts(p)
    : await repo.searchCustomers(p);
  return ok(res, data);
}

export async function searchOrdersHandler(req, res, repo) {
  const p = parseSearchQuery(queryOf(req));
  if (p.errors.length) return fail(res, 400, 'validation_error', p.errors[0].message);
  return ok(res, await repo.searchOrders(p));
}

export async function customerHandler(req, res, repo) {
  const name = String(queryOf(req).name ?? '').trim();
  if (!name) return fail(res, 400, 'validation_error', 'กรุณาระบุชื่อลูกค้า');
  const data = await repo.getCustomer(name);
  if (!data) return fail(res, 404, 'not_found', 'ไม่พบลูกค้านี้');
  return ok(res, data);
}

export async function productHandler(req, res, repo) {
  const itemId = String(queryOf(req).item_id ?? '').trim();
  if (!itemId) return fail(res, 400, 'validation_error', 'กรุณาระบุ item_id');
  const data = await repo.getProduct(itemId);
  if (!data) return fail(res, 404, 'not_found', 'ไม่พบสินค้านี้');
  return ok(res, data);
}

export async function filtersHandler(req, res, repo) {
  const q = queryOf(req);
  const dept = q.dept ? Number(q.dept) : null;
  const cls = q.class ? Number(q.class) : null;
  return ok(res, await repo.listFilters({ dept, cls }));
}

export async function statsHandler(req, res, repo) {
  return ok(res, await repo.getStats());
}

export async function importHandler(req, res, repo) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  const url = new URL(req.url, 'http://local');
  const mode = url.searchParams.get('mode') === 'append' ? 'append' : 'replace';
  const filename = String(url.searchParams.get('filename') ?? 'upload.xlsx').slice(0, 255);
  const body = await readJson(req);
  const rows = body.rows;
  const { errors } = validateImportRows(rows);
  if (errors.length) {
    return fail(res, 422, 'bad_file', `ไฟล์มีปัญหา ${errors.length} แถว: ${errors.slice(0, 5).map((e) => `แถว ${e.row} ${e.field}: ${e.message}`).join('; ')}`);
  }
  const data = await repo.importRows({ filename, mode, rows, importedBy: req.user?.username ?? 'admin' });
  return ok(res, data);
}

export async function importsHandler(req, res, repo) {
  return ok(res, await repo.listImports(50));
}

export async function clearHandler(req, res, repo) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  const body = await readJson(req);
  if (body.confirm !== true) return fail(res, 400, 'validation_error', 'ต้องยืนยันการลบ (confirm: true)');
  await repo.clearAll();
  return ok(res, {});
}
