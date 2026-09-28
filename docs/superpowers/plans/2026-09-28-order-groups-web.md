# Order Groups Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Thai-language HTML web app (Vercel Serverless Functions + static HTML + Supabase Postgres) that searches which product groups a customer bought and which customers bought a product, with admin/viewer login, admin xlsx import/clear, and a central repository abstraction so the database can be swapped later.

**Architecture:** Browser (vanilla HTML/CSS/JS, no build) → `/api/*` Vercel Node functions → `api/_lib/repository.js` (single contract) → `api/_lib/adapters/supabase.js` (the only file that knows Supabase). A `memory.js` adapter exists for tests and local dev. Aggregation logic lives in the repository (shared, tested once); adapters are dumb row-level CRUD.

**Tech Stack:** Node 26 (ESM, `node --test`), Vercel Functions, `@supabase/supabase-js`, Postgres schema `order_item`, scrypt (built-in `node:crypto`), SheetJS `xlsx` vendored into `public/vendor/` for client-side xlsx parsing.

**Working tree note:** All files from the old FastAPI stack are deleted in the working tree (still in git history). The first commit of this plan retires the old stack and adds the new app. Ask the user before committing whether they want the old files removed in the same commit.

---

## File Structure

```
order-item-details/
├── .env.example
├── .gitignore
├── README.md
├── package.json
├── vercel.json
├── migrations/
│   └── 001_schema.sql
├── scripts/
│   └── create-user.js
├── api/
│   ├── _lib/
│   │   ├── config.js
│   │   ├── http.js
│   │   ├── normalize.js
│   │   ├── passwords.js
│   │   ├── validate.js
│   │   ├── auth.js
│   │   ├── ratelimit.js
│   │   ├── repository.js
│   │   └── adapters/
│   │       ├── index.js
│   │       ├── memory.js
│   │       └── supabase.js
│   ├── auth/
│   │   ├── login.js
│   │   ├── logout.js
│   │   └── me.js
│   ├── search.js
│   ├── search/
│   │   └── orders.js
│   ├── customer.js
│   ├── product.js
│   ├── filters.js
│   ├── stats.js
│   └── admin/
│       ├── import.js
│       ├── imports.js
│       └── clear.js
├── public/
│   ├── index.html
│   ├── login.html
│   ├── admin.html
│   ├── styles.css
│   ├── vendor/xlsx.full.min.js
│   └── js/
│       ├── api.js
│       ├── ui.js
│       ├── index.js
│       ├── login.js
│       └── admin.js
└── tests/
    ├── helpers.js
    ├── test_passwords.js
    ├── test_normalize.js
    ├── test_validate.js
    ├── test_repository_contract.js
    ├── test_handlers.js
    └── test_import_flow.js
```

---

### Task 1: Project scaffold

**Files:**
- Create: `package.json`
- Create: `vercel.json`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `migrations/001_schema.sql`
- Create: `README.md`

- [ ] **Step 1: Write `package.json`**

```json
{
  "name": "order-groups-web",
  "private": true,
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "test": "node --test tests/",
    "dev": "vercel dev"
  },
  "dependencies": {
    "@supabase/supabase-js": "^2.45.0"
  },
  "devDependencies": {
    "xlsx": "^0.18.5"
  }
}
```

- [ ] **Step 2: Write `vercel.json`**

```json
{
  "cleanUrls": true,
  "headers": [
    {
      "source": "/api/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "no-store" }
      ]
    }
  ]
}
```

- [ ] **Step 3: Write `.gitignore`**

```
node_modules/
.vercel/
.env
*.log
```

- [ ] **Step 4: Write `.env.example`**

```
# Supabase project (service role key — NEVER expose to the browser)
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
# Random string used to sign nothing directly but required config; any long random value
SESSION_SECRET=
```

- [ ] **Step 5: Write `migrations/001_schema.sql`**

```sql
-- Order Groups Web — schema `order_item` (isolated namespace for this project)
create schema if not exists order_item;

create table order_item.order_items (
  id            bigserial primary key,
  order_number  text not null,
  store_code    text,
  item_id       text not null,
  product_name  text not null,
  product_norm  text not null,
  customer_name text not null,
  customer_norm text not null,
  expected_from date,
  expected_to   date,
  expected_raw  text,
  dept          integer,
  class         integer,
  subclass      integer,
  item_remark          text,
  vip_customer_remarks text,
  vip_customer_groups  text
);

create index order_items_customer_norm_idx on order_item.order_items (customer_norm);
create index order_items_product_norm_idx  on order_item.order_items (product_norm);
create index order_items_group_idx         on order_item.order_items (dept, class, subclass);
create index order_items_order_number_idx  on order_item.order_items (order_number);

create table order_item.users (
  id            uuid primary key default gen_random_uuid(),
  username      text unique not null,
  password_hash text not null,
  role          text not null check (role in ('admin','viewer')),
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table order_item.sessions (
  token_hash text primary key,
  user_id    uuid not null references order_item.users(id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table order_item.imports (
  id          bigserial primary key,
  filename    text,
  mode        text not null check (mode in ('replace','append')),
  row_count   integer not null,
  imported_by text,
  imported_at timestamptz not null default now()
);

-- Atomic import: replace mode (delete all + insert + log) in one transaction.
create or replace function order_item.replace_all(p_rows jsonb, p_filename text, p_imported_by text)
returns jsonb language plpgsql as $$
declare v_count int;
begin
  delete from order_item.order_items;
  insert into order_item.order_items
    (order_number, store_code, item_id, product_name, product_norm,
     customer_name, customer_norm, expected_from, expected_to, expected_raw,
     dept, class, subclass, item_remark, vip_customer_remarks, vip_customer_groups)
  select
    r->>'Order Number', nullif(r->>'Store Code',''), r->>'Item Id', r->>'Product Name',
    lower(regexp_replace(coalesce(r->>'Product Name',''), '\s+', '', 'g')),
    r->>'Customer Name',
    lower(regexp_replace(coalesce(r->>'Customer Name',''), '\s+', '', 'g')),
    (r->>'_from')::date, (r->>'_to')::date, r->>'Original Expected Date',
    nullif(r->>'Dept','')::int, nullif(r->>'Class','')::int, nullif(r->>'Subclass','')::int,
    nullif(r->>'Item Remark',''), nullif(r->>'VIP Customer Remarks',''), nullif(r->>'VIP Customer Groups','')
  from jsonb_array_elements(p_rows) r;
  get diagnostics v_count = row_count;
  insert into order_item.imports (filename, mode, row_count, imported_by)
  values (p_filename, 'replace', v_count, p_imported_by);
  return jsonb_build_object('row_count', v_count);
end $$;

-- Atomic import: append mode (insert + log) in one transaction.
create or replace function order_item.append_rows(p_rows jsonb, p_filename text, p_imported_by text)
returns jsonb language plpgsql as $$
declare v_count int;
begin
  insert into order_item.order_items
    (order_number, store_code, item_id, product_name, product_norm,
     customer_name, customer_norm, expected_from, expected_to, expected_raw,
     dept, class, subclass, item_remark, vip_customer_remarks, vip_customer_groups)
  select
    r->>'Order Number', nullif(r->>'Store Code',''), r->>'Item Id', r->>'Product Name',
    lower(regexp_replace(coalesce(r->>'Product Name',''), '\s+', '', 'g')),
    r->>'Customer Name',
    lower(regexp_replace(coalesce(r->>'Customer Name',''), '\s+', '', 'g')),
    (r->>'_from')::date, (r->>'_to')::date, r->>'Original Expected Date',
    nullif(r->>'Dept','')::int, nullif(r->>'Class','')::int, nullif(r->>'Subclass','')::int,
    nullif(r->>'Item Remark',''), nullif(r->>'VIP Customer Remarks',''), nullif(r->>'VIP Customer Groups','')
  from jsonb_array_elements(p_rows) r;
  get diagnostics v_count = row_count;
  insert into order_item.imports (filename, mode, row_count, imported_by)
  values (p_filename, 'append', v_count, p_imported_by);
  return jsonb_build_object('row_count', v_count);
end $$;

-- RLS on, no policies: service role bypasses, browser never holds the key.
alter table order_item.order_items enable row level security;
alter table order_item.users      enable row level security;
alter table order_item.sessions   enable row level security;
alter table order_item.imports    enable row level security;
```

- [ ] **Step 6: Write `README.md`** (setup: create Supabase project → run migration in SQL editor → `npm install` → copy `.env.example` to `.env` and fill → `npm run dev` → `node scripts/create-user.js admin <username>` → deploy `vercel`)

- [ ] **Step 7: Install deps and vendor SheetJS**

Run: `npm.cmd install`
Then: `Copy-Item node_modules\xlsx\dist\xlsx.full.min.js public\vendor\xlsx.full.min.js`
Expected: `public/vendor/xlsx.full.min.js` exists.

- [ ] **Step 8: Verify scaffold**

Run: `node --check api/_lib/config.js` (file doesn't exist yet — skip; instead run `node -e "console.log('ok')"`)
Expected: `ok`

- [ ] **Step 9: Commit** (ask user first about including the old-file deletions)

```bash
git add package.json vercel.json .gitignore .env.example migrations/001_schema.sql README.md public/vendor/xlsx.full.min.js
git commit -m "feat: scaffold order-groups-web (Vercel + Supabase)"
```

---

### Task 2: Core libs — config, http, normalize, passwords, validate

**Files:**
- Create: `api/_lib/config.js`
- Create: `api/_lib/http.js`
- Create: `api/_lib/normalize.js`
- Create: `api/_lib/passwords.js`
- Create: `api/_lib/validate.js`
- Test: `tests/test_passwords.js`, `tests/test_normalize.js`, `tests/test_validate.js`

- [ ] **Step 1: Write failing tests**

`tests/test_passwords.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hashPassword, verifyPassword } from '../api/_lib/passwords.js';

test('hash then verify roundtrip', () => {
  const h = hashPassword('s3cret!');
  assert.ok(h.startsWith('scrypt$'));
  assert.ok(verifyPassword('s3cret!', h));
  assert.ok(!verifyPassword('wrong', h));
});

test('two hashes of same password differ (random salt)', () => {
  assert.notEqual(hashPassword('x'), hashPassword('x'));
});

test('verify rejects malformed stored hash', () => {
  assert.ok(!verifyPassword('x', 'not-a-hash'));
  assert.ok(!verifyPassword('x', 'scrypt$N=1,r=1,p=1$!!$!!'));
});
```

`tests/test_normalize.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeThai } from '../api/_lib/normalize.js';

test('removes all whitespace and lowercases', () => {
  assert.equal(normalizeThai('เด็ก สমบูรณ์ ซีอิ๊วขาว'), 'เด็กসমบูรณ์সীই๊วখাও');
  assert.equal(normalizeThai('  A B  C '), 'abc');
});

test('handles null/undefined', () => {
  assert.equal(normalizeThai(null), '');
  assert.equal(normalizeThai(undefined), '');
  assert.equal(normalizeThai(123), '123');
});
```

`tests/test_validate.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDate, parseExpectedRange, parseSearchQuery, validateImportRows } from '../api/_lib/validate.js';

test('parseDate accepts dd-Mon-yyyy', () => {
  assert.equal(parseDate('28-Sep-2026'), '2026-09-28');
  assert.equal(parseDate('03-Oct-2026'), '2026-10-03');
  assert.equal(parseDate('31-Feb-2026'), null);
  assert.equal(parseDate('garbage'), null);
});

test('parseExpectedRange splits on dash', () => {
  const r = parseExpectedRange('28-Sep-2026 - 28-Sep-2026');
  assert.deepEqual(r, { from: '2026-09-28', to: '2026-09-28', raw: '28-Sep-2026 - 28-Sep-2026' });
  assert.equal(parseExpectedRange('nope'), null);
});

test('parseSearchQuery defaults and bounds', () => {
  const q = parseSearchQuery({});
  assert.equal(q.direction, 'customer');
  assert.equal(q.page, 1);
  assert.equal(q.pageSize, 50);
  const big = parseSearchQuery({ page_size: '9999', q: 'x'.repeat(200) });
  assert.equal(big.pageSize, 100);
  assert.equal(big.errors.length, 1);
  assert.equal(big.errors[0].field, 'q');
});

test('validateImportRows rejects missing headers and dup keys', () => {
  const bad = validateImportRows([{ 'Item Id': '1' }]);
  assert.ok(bad.errors.some((e) => e.field === '_headers'));
  const rows = [
    { 'Order Number': 'A', 'Item Id': '1', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P' },
    { 'Order Number': 'A', 'Item Id': '1', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P' }
  ];
  const dup = validateImportRows(rows);
  assert.ok(dup.errors.some((e) => e.field === 'Order Number'));
});

test('validateImportRows passes clean rows and adds _from/_to', () => {
  const rows = [
    { 'Order Number': 'A', 'Item Id': '1', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29', 'Customer Name': 'X', 'Product Name': 'P' }
  ];
  const res = validateImportRows(rows);
  assert.equal(res.errors.length, 0);
  assert.equal(rows[0]._from, '2026-09-28');
  assert.equal(rows[0]._to, '2026-09-28');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/test_passwords.js tests/test_normalize.js tests/test_validate.js`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write `api/_lib/config.js`**

```js
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
```

- [ ] **Step 4: Write `api/_lib/http.js`**

```js
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
```

- [ ] **Step 5: Write `api/_lib/normalize.js`**

```js
export function normalizeThai(s) {
  return String(s ?? '').toLowerCase().replace(/\s+/g, '').trim();
}
```

- [ ] **Step 6: Write `api/_lib/passwords.js`**

```js
import { randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';

const N = 16384, R = 8, P = 1, KEY_LEN = 32;

export function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = scryptSync(password, salt, KEY_LEN, { N, r: R, p: P });
  return `scrypt$N=${N},r=${R},p=${P}$` + salt.toString('base64') + '$' + hash.toString('base64');
}

export function verifyPassword(password, stored) {
  const parts = String(stored ?? '').split('$');
  if (parts.length !== 4 || parts[0] !== 'scrypt') return false;
  const params = Object.fromEntries(parts[1].split(',').map((kv) => kv.split('=')));
  const salt = Buffer.from(parts[2], 'base64');
  const expected = Buffer.from(parts[3], 'base64');
  if (expected.length === 0) return false;
  const actual = scryptSync(password, salt, expected.length, { N: +params.N, r: +params.r, p: +params.p });
  return timingSafeEqual(actual, expected);
}
```

- [ ] **Step 7: Write `api/_lib/validate.js`**

```js
const MONTHS = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };

export function parseDate(d) {
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/.exec(String(d ?? '').trim());
  if (!m) return null;
  const month = MONTHS[m[2]];
  if (!month) return null;
  const day = +m[1], year = +m[3];
  const dt = new Date(Date.UTC(year, month - 1, day));
  if (dt.getUTCFullYear() !== year || dt.getUTCMonth() !== month - 1 || dt.getUTCDate() !== day) return null;
  return dt.toISOString().slice(0, 10);
}

export function parseExpectedRange(raw) {
  const parts = String(raw ?? '').split('-').map((s) => s.trim());
  if (parts.length !== 2) return null;
  const from = parseDate(parts[0]);
  const to = parseDate(parts[1]);
  if (!from || !to) return null;
  return { from, to, raw: String(raw) };
}

export function parseSearchQuery(query) {
  const errors = [];
  const direction = query.direction === 'product' ? 'product' : 'customer';
  const q = String(query.q ?? '').trim();
  if (q.length > 100) errors.push({ field: 'q', message: 'คำค้นยาวเกิน 100 ตัวอักษร' });
  const num = (v) => {
    if (v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isInteger(n) && n > 0 ? n : null;
  };
  const dept = num(query.dept);
  const cls = num(query.class);
  const subclass = num(query.subclass);
  if (query.dept !== undefined && query.dept !== '' && dept === null) errors.push({ field: 'dept', message: 'dept ต้องเป็นตัวเลข' });
  if (query.class !== undefined && query.class !== '' && cls === null) errors.push({ field: 'class', message: 'class ต้องเป็นตัวเลข' });
  if (query.subclass !== undefined && query.subclass !== '' && subclass === null) errors.push({ field: 'subclass', message: 'subclass ต้องเป็นตัวเลข' });
  let page = num(query.page) ?? 1;
  let pageSize = num(query.page_size) ?? 50;
  pageSize = Math.min(Math.max(pageSize, 1), 100);
  page = Math.max(page, 1);
  return { direction, q, dept, cls, subclass, page, pageSize, errors };
}

const REQUIRED_HEADERS = [
  'Order Number', 'Store Code', 'Item Id', 'Product Name', 'Original Expected Date',
  'Dept', 'Class', 'Subclass', 'Customer Name', 'Item Remark', 'VIP Customer Remarks', 'VIP Customer Groups'
];

export function validateImportRows(rows) {
  const errors = [];
  const warnings = [];
  if (!Array.isArray(rows) || rows.length === 0) {
    return { errors: [{ row: 0, field: '_file', message: 'ไฟล์ว่างหรืออ่านไม่ได้' }], warnings };
  }
  const headers = Object.keys(rows[0]);
  const missing = REQUIRED_HEADERS.filter((h) => !headers.includes(h));
  if (missing.length) {
    return { errors: [{ row: 0, field: '_headers', message: `หัวคอลัมน์ไม่ครบ: ${missing.join(', ')}` }], warnings };
  }
  const seen = new Map();
  rows.forEach((r, i) => {
    const rowNo = i + 2;
    const orderNumber = String(r['Order Number'] ?? '').trim();
    const itemId = String(r['Item Id'] ?? '').trim();
    if (!orderNumber) errors.push({ row: rowNo, field: 'Order Number', message: 'ว่าง' });
    if (!itemId) errors.push({ row: rowNo, field: 'Item Id', message: 'ว่าง' });
    const key = `${orderNumber}|${itemId}`;
    if (orderNumber && itemId) {
      if (seen.has(key)) errors.push({ row: rowNo, field: 'Order Number', message: `ซ้ำกับแถว ${seen.get(key)}` });
      else seen.set(key, rowNo);
    }
    const range = parseExpectedRange(r['Original Expected Date']);
    if (!range) errors.push({ row: rowNo, field: 'Original Expected Date', message: 'รูปแบบวันที่ไม่ถูก (ต้องการ dd-Mon-yyyy - dd-Mon-yyyy)' });
    else {
      r._from = range.from;
      r._to = range.to;
    }
    for (const f of ['Dept', 'Class', 'Subclass']) {
      const v = r[f];
      if (v !== undefined && v !== '' && v !== null && !Number.isInteger(Number(v))) {
        errors.push({ row: rowNo, field: f, message: 'ต้องเป็นตัวเลข' });
      }
    }
  });
  return { errors, warnings };
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `node --test tests/test_passwords.js tests/test_normalize.js tests/test_validate.js`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add api/_lib/config.js api/_lib/http.js api/_lib/normalize.js api/_lib/passwords.js api/_lib/validate.js tests/test_passwords.js tests/test_normalize.js tests/test_validate.js
git commit -m "feat: core libs (config, http, normalize, scrypt passwords, validation)"
```

---

### Task 3: Memory adapter + repository contract

**Files:**
- Create: `api/_lib/adapters/memory.js`
- Create: `api/_lib/repository.js`
- Test: `tests/test_repository_contract.js`

- [ ] **Step 1: Write the failing contract test**

`tests/test_repository_contract.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { hashPassword } from '../api/_lib/passwords.js';

function seed() {
  const a = createMemoryAdapter();
  a.seedOrderItems([
    { order_number: 'A1', item_id: '146454', product_name: 'เด็กসমবূর্ন ซีইইঁখাও', customer_name: 'সুনীই বূনমী', expected_from: '2026-09-28', expected_to: '2026-09-28', dept: 8, class: 312, subclass: 29, vip_customer_groups: 'Platinum' },
    { order_number: 'A2', item_id: '840325', product_name: 'অম্পওয়া কঠি', customer_name: 'সুনীই বূনমী', expected_from: '2026-09-21', expected_to: '2026-09-21', dept: 8, class: 696, subclass: 12, vip_customer_groups: 'Gold' },
    { order_number: 'B1', item_id: '146454', product_name: 'เด็กসমবূর্ন ซีইইঁখাও', customer_name: 'রত্না টংদী', expected_from: '2026-10-03', expected_to: '2026-10-03', dept: 8, class: 312, subclass: 29, vip_customer_groups: 'Silver' }
  ]);
  a.seedUser({ username: 'admin', password_hash: hashPassword('pw'), role: 'admin', active: true });
  return createRepository(a);
}

test('searchCustomers groups by customer with counts and vip', async () => {
  const repo = seed();
  const res = await repo.searchCustomers({ q: 'সুনীই', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(res.total, 1);
  const c = res.items[0];
  assert.equal(c.customer_name, 'সুনীই বূনমী');
  assert.equal(c.order_count, 2);
  assert.equal(c.product_count, 2);
  assert.deepEqual(c.vip_groups.sort(), ['Gold', 'Platinum']);
  assert.equal(c.groups.length, 2);
});

test('searchProducts groups by item', async () => {
  const repo = seed();
  const res = await repo.searchProducts({ q: 'কঠি', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(res.total, 1);
  assert.equal(res.items[0].item_id, '840325');
  assert.equal(res.items[0].customer_count, 1);
});

test('searchOrders returns flat rows with pagination', async () => {
  const repo = seed();
  const res = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 2 });
  assert.equal(res.total, 3);
  assert.equal(res.items.length, 2);
});

test('getCustomer aggregates one customer', async () => {
  const repo = seed();
  const c = await repo.getCustomer('সুনীই বূনমী');
  assert.equal(c.order_count, 2);
  assert.equal(c.orders.length, 2);
});

test('getProduct lists customers', async () => {
  const repo = seed();
  const p = await repo.getProduct('146454');
  assert.equal(p.customer_count, 2);
  assert.equal(p.customers.length, 2);
});

test('filters cascade', async () => {
  const repo = seed();
  const f = await repo.listFilters({ dept: 8, cls: null });
  assert.deepEqual(f.depts, [8]);
  assert.deepEqual(f.classes, [312, 696]);
  assert.deepEqual(f.subclasses, [12, 29]);
});

test('import replace then clear', async () => {
  const repo = seed();
  const rows = [
    { 'Order Number': 'X1', 'Item Id': '9', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': '01-Jan-2026 - 01-Jan-2026', '_from': '2026-01-01', '_to': '2026-01-01', 'Dept': '1', 'Class': '2', 'Subclass': '3' }
  ];
  const r = await repo.importRows({ filename: 't.xlsx', mode: 'replace', rows, importedBy: 'admin' });
  assert.equal(r.row_count, 1);
  const after = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(after.total, 1);
  await repo.clearAll();
  const cleared = await repo.searchOrders({ q: '', direction: 'customer', dept: null, cls: null, subclass: null, page: 1, pageSize: 50 });
  assert.equal(cleared.total, 0);
});

test('auth: session lifecycle', async () => {
  const repo = seed();
  const user = await repo.findUserByUsername('admin');
  assert.ok(user);
  const tokenHash = 'abc123';
  await repo.createSession(user.id, tokenHash, new Date(Date.now() + 10000));
  const s = await repo.findSession(tokenHash);
  assert.equal(s.username, 'admin');
  assert.equal(s.role, 'admin');
  await repo.deleteSession(tokenHash);
  assert.equal(await repo.findSession(tokenHash), null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test tests/test_repository_contract.js`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write `api/_lib/adapters/memory.js`**

```js
import { normalizeThai } from '../normalize.js';

export function createMemoryAdapter() {
  const state = { orderItems: [], users: [], sessions: [], imports: [] };
  let nextId = 1;

  const adapter = {
    _state: state,

    seedOrderItems(rows) {
      state.orderItems = rows.map((r) => ({
        id: nextId++,
        order_number: r.order_number,
        store_code: r.store_code,
        item_id: r.item_id,
        product_name: r.product_name,
        product_norm: normalizeThai(r.product_name),
        customer_name: r.customer_name,
        customer_norm: normalizeThai(r.customer_name),
        expected_from: r.expected_from,
        expected_to: r.expected_to,
        expected_raw: r.expected_raw,
        dept: r.dept,
        class: r.class,
        subclass: r.subclass,
        item_remark: r.item_remark,
        vip_customer_remarks: r.vip_customer_remarks,
        vip_customer_groups: r.vip_customer_groups
      }));
    },

    seedUser(u) {
      state.users.push({ id: `u${state.users.length + 1}`, username: u.username, password_hash: u.password_hash, role: u.role, active: u.active });
    },

    async queryOrderRows({ q, direction, dept, cls, subclass, customerNorm, itemId, limit }) {
      let rows = state.orderItems;
      if (customerNorm) rows = rows.filter((r) => r.customer_norm === customerNorm);
      else if (itemId) rows = rows.filter((r) => r.item_id === itemId);
      else if (q) {
        const norm = normalizeThai(q);
        rows = rows.filter((r) => (direction === 'product' ? r.product_norm : r.customer_norm).includes(norm));
      }
      if (dept) rows = rows.filter((r) => r.dept === dept);
      if (cls) rows = rows.filter((r) => r.class === cls);
      if (subclass) rows = rows.filter((r) => r.subclass === subclass);
      if (limit) rows = rows.slice(0, limit);
      return rows;
    },

    async countOrderRows(params) {
      return (await adapter.queryOrderRows(params)).length;
    },

    async listFilters({ dept, cls }) {
      const rows = state.orderItems;
      const depts = [...new Set(rows.map((r) => r.dept))].sort();
      const classes = [...new Set(rows.filter((r) => !dept || r.dept === dept).map((r) => r.class))].sort();
      const subclasses = [...new Set(rows.filter((r) => (!dept || r.dept === dept) && (!cls || r.class === cls)).map((r) => r.subclass))].sort();
      return { depts, classes, subclasses };
    },

    async getStats() {
      const rows = state.orderItems;
      return {
        order_count: rows.length,
        customer_count: new Set(rows.map((r) => r.customer_norm)).size,
        product_count: new Set(rows.map((r) => r.item_id)).size,
        group_count: new Set(rows.map((r) => `${r.dept}|${r.class}|${r.subclass}`)).size,
        last_import: state.imports.length ? state.imports[state.imports.length - 1].imported_at : null
      };
    },

    async importRows({ filename, mode, rows, importedBy }) {
      if (mode === 'replace') state.orderItems = [];
      const mapped = rows.map((r) => ({
        id: nextId++,
        order_number: String(r['Order Number'] ?? '').trim(),
        store_code: r['Store Code'] === undefined ? null : String(r['Store Code']).trim(),
        item_id: String(r['Item Id'] ?? '').trim(),
        product_name: String(r['Product Name'] ?? '').trim(),
        product_norm: normalizeThai(r['Product Name']),
        customer_name: String(r['Customer Name'] ?? '').trim(),
        customer_norm: normalizeThai(r['Customer Name']),
        expected_from: r._from,
        expected_to: r._to,
        expected_raw: r['Original Expected Date'],
        dept: r['Dept'] === '' || r['Dept'] === undefined ? null : Number(r['Dept']),
        class: r['Class'] === '' || r['Class'] === undefined ? null : Number(r['Class']),
        subclass: r['Subclass'] === '' || r['Subclass'] === undefined ? null : Number(r['Subclass']),
        item_remark: r['Item Remark'] === undefined ? null : String(r['Item Remark']),
        vip_customer_remarks: r['VIP Customer Remarks'] === undefined ? null : String(r['VIP Customer Remarks']),
        vip_customer_groups: r['VIP Customer Groups'] === undefined ? null : String(r['VIP Customer Groups'])
      }));
      state.orderItems.push(...mapped);
      state.imports.push({ id: nextId++, filename, mode, row_count: mapped.length, imported_by: importedBy, imported_at: new Date().toISOString() });
      return { row_count: mapped.length, warnings: [] };
    },

    async listImports(limit = 50) {
      return state.imports.slice(-limit).reverse();
    },

    async clearAll() {
      state.orderItems = [];
    },

    async findUserByUsername(username) {
      return state.users.find((u) => u.username === username);
    },

    async createSession(userId, tokenHash, expiresAt) {
      state.sessions.push({ token_hash: tokenHash, user_id: userId, expires_at: expiresAt, created_at: new Date() });
    },

    async findSession(tokenHash) {
      const s = state.sessions.find((x) => x.token_hash === tokenHash);
      if (!s) return null;
      const u = state.users.find((x) => x.id === s.user_id);
      if (!u) return null;
      return { user_id: u.id, username: u.username, role: u.role, active: u.active, expires_at: s.expires_at };
    },

    async deleteSession(tokenHash) {
      state.sessions = state.sessions.filter((x) => x.token_hash !== tokenHash);
    },

    async touchSession(tokenHash, expiresAt) {
      const s = state.sessions.find((x) => x.token_hash === tokenHash);
      if (s) s.expires_at = expiresAt;
    }
  };

  return adapter;
}
```

- [ ] **Step 4: Write `api/_lib/repository.js`**

```js
function paginate(items, page, pageSize) {
  const total = items.length;
  const start = (page - 1) * pageSize;
  return { items: items.slice(start, start + pageSize), total };
}

function groupKey(r) {
  return `${r.dept}|${r.class}|${r.subclass}`;
}

function aggregateCustomers(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = r.customer_norm;
    if (!by.has(key)) {
      by.set(key, { customer_name: r.customer_name, order_count: 0, product_count: 0, groups: new Map(), vip: new Set(), last_expected: null });
    }
    const c = by.get(key);
    c.order_count++;
    if (!c.groups.has(groupKey(r))) c.groups.set(groupKey(r), { dept: r.dept, class: r.class, subclass: r.subclass, count: 0 });
    c.groups.get(groupKey(r)).count++;
    if (r.vip_customer_groups) c.vip.add(r.vip_customer_groups);
    if (r.expected_from && (!c.last_expected || r.expected_from > c.last_expected)) c.last_expected = r.expected_from;
  }
  return [...by.values()].map((c) => ({
    customer_name: c.customer_name,
    order_count: c.order_count,
    product_count: c.groups.size,
    groups: [...c.groups.values()],
    vip_groups: [...c.vip],
    last_expected: c.last_expected
  })).sort((a, b) => b.order_count - a.order_count);
}

function aggregateProducts(rows) {
  const by = new Map();
  for (const r of rows) {
    const key = r.item_id;
    if (!by.has(key)) {
      by.set(key, { item_id: r.item_id, product_name: r.product_name, order_count: 0, customers: new Set(), groups: new Map() });
    }
    const p = by.get(key);
    p.order_count++;
    p.customers.add(r.customer_name);
    if (!p.groups.has(groupKey(r))) p.groups.set(groupKey(r), { dept: r.dept, class: r.class, subclass: r.subclass, count: 0 });
    p.groups.get(groupKey(r)).count++;
  }
  return [...by.values()].map((p) => ({
    item_id: p.item_id,
    product_name: p.product_name,
    order_count: p.order_count,
    customer_count: p.customers.size,
    groups: [...p.groups.values()]
  })).sort((a, b) => b.order_count - a.order_count);
}

export function createRepository(adapter) {
  return {
    findUserByUsername: (u) => adapter.findUserByUsername(u),
    createSession: (userId, tokenHash, expiresAt) => adapter.createSession(userId, tokenHash, expiresAt),
    findSession: (tokenHash) => adapter.findSession(tokenHash),
    deleteSession: (tokenHash) => adapter.deleteSession(tokenHash),
    touchSession: (tokenHash, expiresAt) => adapter.touchSession(tokenHash, expiresAt),

    async searchCustomers({ q, dept, cls, subclass, page, pageSize }) {
      const rows = await adapter.queryOrderRows({ q, direction: 'customer', dept, cls, subclass, limit: 10000 });
      return paginate(aggregateCustomers(rows), page, pageSize);
    },

    async searchProducts({ q, dept, cls, subclass, page, pageSize }) {
      const rows = await adapter.queryOrderRows({ q, direction: 'product', dept, cls, subclass, limit: 10000 });
      return paginate(aggregateProducts(rows), page, pageSize);
    },

    async searchOrders({ q, direction, dept, cls, subclass, page, pageSize }) {
      const params = { q, direction, dept, cls, subclass };
      const total = await adapter.countOrderRows(params);
      const rows = await adapter.queryOrderRows({ ...params, limit: pageSize });
      return { items: rows, total };
    },

    async getCustomer(name) {
      const rows = await adapter.queryOrderRows({ customerNorm: normalizeThai(name), limit: 10000 });
      if (rows.length === 0) return null;
      const agg = aggregateCustomers(rows)[0];
      return { ...agg, orders: rows };
    },

    async getProduct(itemId) {
      const rows = await adapter.queryOrderRows({ itemId, limit: 10000 });
      if (rows.length === 0) return null;
      const agg = aggregateProducts(rows)[0];
      return { ...agg, customers: [...new Set(rows.map((r) => r.customer_name))] };
    },

    listFilters: (p) => adapter.listFilters(p),
    getStats: () => adapter.getStats(),
    importRows: (p) => adapter.importRows(p),
    listImports: (limit) => adapter.listImports(limit),
    clearAll: () => adapter.clearAll()
  };
}
```

Note: `repository.js` needs `normalizeThai` imported — add at top:

```js
import { normalizeThai } from './normalize.js';
```

- [ ] **Step 5: Run test to verify it passes**

Run: `node --test tests/test_repository_contract.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/_lib/adapters/memory.js api/_lib/repository.js tests/test_repository_contract.js
git commit -m "feat: repository contract with in-memory adapter"
```

---

### Task 4: Supabase adapter

**Files:**
- Create: `api/_lib/adapters/index.js`
- Create: `api/_lib/adapters/supabase.js`

- [ ] **Step 1: Write `api/_lib/adapters/index.js`**

```js
import { createClient } from '@supabase/supabase-js';
import { loadConfig } from '../config.js';
import { createSupabaseAdapter } from './supabase.js';

let _adapter;

export function getAdapter(env = process.env) {
  if (!_adapter) {
    const cfg = loadConfig(env);
    const client = createClient(cfg.supabaseUrl, cfg.supabaseKey);
    _adapter = createSupabaseAdapter(client);
  }
  return _adapter;
}
```

- [ ] **Step 2: Write `api/_lib/adapters/supabase.js`**

```js
import { normalizeThai } from '../normalize.js';

export function createSupabaseAdapter(sb) {
  return {
    async queryOrderRows({ q, direction, dept, cls, subclass, customerNorm, itemId, limit }) {
      let b = sb.from('order_items').select('*');
      if (customerNorm) b = b.eq('customer_norm', customerNorm);
      else if (itemId) b = b.eq('item_id', itemId);
      else if (q) {
        const norm = normalizeThai(q);
        b = b.ilike(direction === 'product' ? 'product_norm' : 'customer_norm', `%${norm}%`);
      }
      if (dept) b = b.eq('dept', dept);
      if (cls) b = b.eq('class', cls);
      if (subclass) b = b.eq('subclass', subclass);
      if (limit) b = b.limit(limit);
      const { data, error } = await b;
      if (error) throw new Error(`queryOrderRows: ${error.message}`);
      return data;
    },

    async countOrderRows(params) {
      let b = sb.from('order_items').select('*', { count: 'exact', head: true });
      if (params.customerNorm) b = b.eq('customer_norm', params.customerNorm);
      else if (params.itemId) b = b.eq('item_id', params.itemId);
      else if (params.q) {
        const norm = normalizeThai(params.q);
        b = b.ilike(params.direction === 'product' ? 'product_norm' : 'customer_norm', `%${norm}%`);
      }
      if (params.dept) b = b.eq('dept', params.dept);
      if (params.cls) b = b.eq('class', params.cls);
      if (params.subclass) b = b.eq('subclass', params.subclass);
      const { count, error } = await b;
      if (error) throw new Error(`countOrderRows: ${error.message}`);
      return count;
    },

    async listFilters({ dept, cls }) {
      const out = { depts: [], classes: [], subclasses: [] };
      const d = await sb.from('order_items').select('dept').order('dept').limit(1000);
      if (d.error) throw new Error(`listFilters depts: ${d.error.message}`);
      out.depts = [...new Set(d.data.map((r) => r.dept))];
      let c = sb.from('order_items').select('class').order('class').limit(1000);
      if (dept) c = c.eq('dept', dept);
      const cr = await c;
      if (cr.error) throw new Error(`listFilters classes: ${cr.error.message}`);
      out.classes = [...new Set(cr.data.map((r) => r.class))];
      let s = sb.from('order_items').select('subclass').order('subclass').limit(1000);
      if (dept) s = s.eq('dept', dept);
      if (cls) s = s.eq('class', cls);
      const sr = await s;
      if (sr.error) throw new Error(`listFilters subclasses: ${sr.error.message}`);
      out.subclasses = [...new Set(sr.data.map((r) => r.subclass))];
      return out;
    },

    async getStats() {
      const o = await sb.from('order_items').select('*', { count: 'exact', head: true });
      if (o.error) throw new Error(`getStats orders: ${o.error.message}`);
      const c = await sb.from('order_items').select('customer_norm', { count: 'exact', head: true }).limit(0);
      if (c.error) throw new Error(`getStats customers: ${c.error.message}`);
      const p = await sb.from('order_items').select('item_id', { count: 'exact', head: true }).limit(0);
      if (p.error) throw new Error(`getStats products: ${p.error.message}`);
      const g = await sb.from('order_items').select('dept,class,subclass', { count: 'exact', head: true }).limit(0);
      if (g.error) throw new Error(`getStats groups: ${g.error.message}`);
      const imp = await sb.from('imports').select('imported_at').order('imported_at', { ascending: false }).limit(1);
      if (imp.error) throw new Error(`getStats imports: ${imp.error.message}`);
      return {
        order_count: o.count,
        customer_count: c.count,
        product_count: p.count,
        group_count: g.count,
        last_import: imp.data.length ? imp.data[0].imported_at : null
      };
    },

    async importRows({ filename, mode, rows, importedBy }) {
      const fn = mode === 'replace' ? 'replace_all' : 'append_rows';
      const { data, error } = await sb.rpc(fn, { p_rows: rows, p_filename: filename, p_imported_by: importedBy });
      if (error) throw new Error(`importRows: ${error.message}`);
      return { row_count: data.row_count, warnings: [] };
    },

    async listImports(limit = 50) {
      const { data, error } = await sb.from('imports').select('*').order('imported_at', { ascending: false }).limit(limit);
      if (error) throw new Error(`listImports: ${error.message}`);
      return data;
    },

    async clearAll() {
      const { error } = await sb.from('order_items').delete().neq('id', 0);
      if (error) throw new Error(`clearAll: ${error.message}`);
    },

    async findUserByUsername(username) {
      const { data, error } = await sb.from('users').select('*').eq('username', username).limit(1);
      if (error) throw new Error(`findUserByUsername: ${error.message}`);
      return data.length ? data[0] : null;
    },

    async createSession(userId, tokenHash, expiresAt) {
      const { error } = await sb.from('sessions').insert({ token_hash: tokenHash, user_id: userId, expires_at: expiresAt.toISOString() });
      if (error) throw new Error(`createSession: ${error.message}`);
    },

    async findSession(tokenHash) {
      const { data, error } = await sb.from('sessions').select('token_hash,user_id,expires_at,users!inner(username,role,active)').eq('token_hash', tokenHash).limit(1);
      if (error) throw new Error(`findSession: ${error.message}`);
      if (!data.length) return null;
      const s = data[0];
      return { user_id: s.user_id, username: s.users.username, role: s.users.role, active: s.users.active, expires_at: new Date(s.expires_at) };
    },

    async deleteSession(tokenHash) {
      const { error } = await sb.from('sessions').delete().eq('token_hash', tokenHash);
      if (error) throw new Error(`deleteSession: ${error.message}`);
    },

    async touchSession(tokenHash, expiresAt) {
      const { error } = await sb.from('sessions').update({ expires_at: expiresAt.toISOString() }).eq('token_hash', tokenHash);
      if (error) throw new Error(`touchSession: ${error.message}`);
    }
  };
}
```

- [ ] **Step 3: Verify syntax**

Run: `node --check api/_lib/adapters/supabase.js && node --check api/_lib/adapters/index.js`
Expected: no output (syntax OK).

- [ ] **Step 4: Commit**

```bash
git add api/_lib/adapters/index.js api/_lib/adapters/supabase.js
git commit -m "feat: supabase adapter implementing the repository contract"
```

---

### Task 5: Auth — middleware, ratelimit, login/logout/me

**Files:**
- Create: `api/_lib/auth.js`
- Create: `api/_lib/ratelimit.js`
- Create: `api/auth/login.js`
- Create: `api/auth/logout.js`
- Create: `api/auth/me.js`
- Test: `tests/test_handlers.js` (auth part)

- [ ] **Step 1: Write failing tests**

`tests/test_handlers.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { hashPassword } from '../api/_lib/passwords.js';
import { issueSession, requireAuth } from '../api/_lib/auth.js';
import { getCookie, setCookie } from '../api/_lib/http.js';

function makeReqRes() {
  const req = { method: 'GET', headers: {}, body: '' };
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  return { req, res };
}

function repo() {
  const a = createMemoryAdapter();
  a.seedUser({ username: 'admin', password_hash: hashPassword('pw'), role: 'admin', active: true });
  a.seedUser({ username: 'viewer', password_hash: hashPassword('pw'), role: 'viewer', active: true });
  return createRepository(a);
}

test('issueSession + requireAuth roundtrip', async () => {
  const r = repo();
  const user = await r.findUserByUsername('admin');
  const token = await issueSession(r, user.id);
  const { req, res } = makeReqRes();
  setCookie(res, 'sid', token, { httpOnly: true, path: '/' });
  req.headers.cookie = res.headers['Set-Cookie'].split(';')[0];
  const got = await requireAuth(req, res, r);
  assert.equal(got.username, 'admin');
  assert.equal(got.role, 'admin');
});

test('requireAuth rejects missing cookie', async () => {
  const r = repo();
  const { req, res } = makeReqRes();
  const got = await requireAuth(req, res, r);
  assert.equal(got, null);
  assert.equal(res.statusCode, 401);
});

test('requireAuth rejects expired session', async () => {
  const r = repo();
  const user = await r.findUserByUsername('admin');
  const token = await issueSession(r, user.id);
  const { req, res } = makeReqRes();
  setCookie(res, 'sid', token, { path: '/' });
  req.headers.cookie = res.headers['Set-Cookie'].split(';')[0];
  const s = await r.findSession(require('node:crypto').createHash('sha256').update(token).digest('hex'));
  s.expires_at = new Date(Date.now() - 1000);
  const got = await requireAuth(req, res, r);
  assert.equal(got, null);
  assert.equal(res.statusCode, 401);
});

test('getCookie parses header', () => {
  const { req } = makeReqRes();
  req.headers.cookie = 'a=1; sid=abc%2Bdef; b=2';
  assert.equal(getCookie(req, 'sid'), 'abc+def');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/test_handlers.js`
Expected: FAIL — modules not found.

- [ ] **Step 3: Write `api/_lib/auth.js`**

```js
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
    fail(res, 401, 'unauthorized', 'เซসনหมดอายุ กรุณาเข้าสู่ระบบใหม่');
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
```

- [ ] **Step 4: Write `api/_lib/ratelimit.js`**

```js
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
```

- [ ] **Step 5: Write `api/auth/login.js`**

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { ok, fail, readJson, setCookie } from '../_lib/http.js';
import { verifyPassword } from '../_lib/passwords.js';
import { issueSession } from '../_lib/auth.js';
import { limiter } from '../_lib/ratelimit.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  if (!limiter.allow(req)) return fail(res, 429, 'rate_limited', 'ลองใหม่ในอีกสักครู่');
  const repo = createRepository(getAdapter());
  const body = await readJson(req);
  const username = String(body.username ?? '').trim();
  const password = String(body.password ?? '');
  if (!username || !password) return fail(res, 400, 'validation_error', 'กรุณากรอกชื่อผู้ใช้และรหัสผ่าน');
  const user = await repo.findUserByUsername(username);
  if (!user || !user.active || !verifyPassword(password, user.password_hash)) {
    limiter.record(req);
    return fail(res, 401, 'unauthorized', 'ชื่อผู้ใช้หรือรหัสผ่านไม่ถูก');
  }
  const token = await issueSession(repo, user.id);
  setCookie(res, 'sid', token, {
    httpOnly: true, sameSite: 'Lax', secure: process.env.NODE_ENV === 'production', path: '/', maxAge: 7 * 24 * 3600
  });
  return ok(res, { user: { id: user.id, username: user.username, role: user.role } });
}
```

- [ ] **Step 6: Write `api/auth/logout.js`**

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { ok, fail, getCookie, setCookie } from '../_lib/http.js';
import { hashToken } from '../_lib/auth.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return fail(res, 405, 'method_not_allowed', 'วิธีไม่ถูก');
  const repo = createRepository(getAdapter());
  const token = getCookie(req, 'sid');
  if (token) await repo.deleteSession(hashToken(token));
  setCookie(res, 'sid', '', { httpOnly: true, sameSite: 'Lax', path: '/', maxAge: 0 });
  return ok(res, {});
}
```

- [ ] **Step 7: Write `api/auth/me.js`**

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { ok } from '../_lib/http.js';
import { requireAuth } from '../_lib/auth.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return ok(res, { user });
}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `node --test tests/test_handlers.js`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add api/_lib/auth.js api/_lib/ratelimit.js api/auth/login.js api/auth/logout.js api/auth/me.js tests/test_handlers.js
git commit -m "feat: session auth, login rate limit, login/logout/me endpoints"
```

---

### Task 6: Read endpoints — search, search/orders, customer, product, filters, stats

**Files:**
- Create: `api/search.js`
- Create: `api/search/orders.js`
- Create: `api/customer.js`
- Create: `api/product.js`
- Create: `api/filters.js`
- Create: `api/stats.js`
- Test: extend `tests/test_handlers.js`

- [ ] **Step 1: Write failing tests (append to `tests/test_handlers.js`)**

```js
import { searchHandler, searchOrdersHandler, customerHandler, productHandler, filtersHandler, statsHandler } from '../api/_lib/handlers.js';

test('search handler returns grouped customers', async () => {
  const a = createMemoryAdapter();
  a.seedOrderItems([
    { order_number: 'A1', item_id: '1', product_name: 'P1', customer_name: 'সুনীই', expected_from: '2026-09-28', expected_to: '2026-09-28', dept: 8, class: 312, subclass: 29 },
    { order_number: 'A2', item_id: '2', product_name: 'P2', customer_name: 'সুনীই', expected_from: '2026-09-21', expected_to: '2026-09-21', dept: 8, class: 696, subclass: 12 }
  ]);
  const r = createRepository(a);
  const { req, res } = makeReqRes();
  req.url = '/api/search?direction=customer&q=সুনীই';
  await searchHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, true);
  assert.equal(body.data.total, 1);
  assert.equal(body.data.items[0].order_count, 2);
});

test('search handler validates bad params', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  const { req, res } = makeReqRes();
  req.url = '/api/search?dept=abc';
  await searchHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, false);
  assert.equal(body.error.code, 'validation_error');
});

test('customer handler returns 404 for unknown', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  const { req, res } = makeReqRes();
  req.url = '/api/customer?name=ไม่มี';
  await customerHandler(req, res, r);
  assert.equal(JSON.parse(res.body).error.code, 'not_found');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/test_handlers.js`
Expected: FAIL — `api/_lib/handlers.js` not found.

- [ ] **Step 3: Write `api/_lib/handlers.js`** (shared handler logic so tests can call without HTTP)

```js
import { ok, fail } from './http.js';
import { parseSearchQuery } from './validate.js';

function queryOf(req) {
  const url = new URL(req.url, 'http://local');
  return url.searchParams;
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
  const name = String(queryOf(req).get('name') ?? '').trim();
  if (!name) return fail(res, 400, 'validation_error', 'กรุณาระชื่อลูกค้า');
  const data = await repo.getCustomer(name);
  if (!data) return fail(res, 404, 'not_found', 'ไม่พบลูกค้านี้');
  return ok(res, data);
}

export async function productHandler(req, res, repo) {
  const itemId = String(queryOf(req).get('item_id') ?? '').trim();
  if (!itemId) return fail(res, 400, 'validation_error', 'กรุณาระ item_id');
  const data = await repo.getProduct(itemId);
  if (!data) return fail(res, 404, 'not_found', 'ไม่พบสินค้านี้');
  return ok(res, data);
}

export async function filtersHandler(req, res, repo) {
  const q = queryOf(req);
  const dept = q.get('dept') ? Number(q.get('dept')) : null;
  const cls = q.get('class') ? Number(q.get('class')) : null;
  return ok(res, await repo.listFilters({ dept, cls }));
}

export async function statsHandler(req, res, repo) {
  return ok(res, await repo.getStats());
}
```

- [ ] **Step 4: Write the endpoint files** (each wraps the shared handler with auth + adapter)

`api/search.js`:

```js
import { createRepository } from './_lib/repository.js';
import { getAdapter } from './_lib/adapters/index.js';
import { requireAuth } from './_lib/auth.js';
import { searchHandler } from './_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return searchHandler(req, res, repo);
}
```

`api/search/orders.js`:

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { requireAuth } from '../_lib/auth.js';
import { searchOrdersHandler } from '../_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return searchOrdersHandler(req, res, repo);
}
```

`api/customer.js`:

```js
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
```

`api/product.js`:

```js
import { createRepository } from './_lib/repository.js';
import { getAdapter } from './_lib/adapters/index.js';
import { requireAuth } from './_lib/auth.js';
import { productHandler } from './_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return productHandler(req, res, repo);
}
```

`api/filters.js`:

```js
import { createRepository } from './_lib/repository.js';
import { getAdapter } from './_lib/adapters/index.js';
import { requireAuth } from './_lib/auth.js';
import { filtersHandler } from './_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return filtersHandler(req, res, repo);
}
```

`api/stats.js`:

```js
import { createRepository } from './_lib/repository.js';
import { getAdapter } from './_lib/adapters/index.js';
import { requireAuth } from './_lib/auth.js';
import { statsHandler } from './_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  return statsHandler(req, res, repo);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test tests/test_handlers.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/_lib/handlers.js api/search.js api/search/orders.js api/customer.js api/product.js api/filters.js api/stats.js tests/test_handlers.js
git commit -m "feat: read endpoints (search, orders, customer, product, filters, stats)"
```

---

### Task 7: Admin endpoints — import, imports, clear

**Files:**
- Create: `api/admin/import.js`
- Create: `api/admin/imports.js`
- Create: `api/admin/clear.js`
- Test: extend `tests/test_handlers.js` + `tests/test_import_flow.js`

- [ ] **Step 1: Write failing tests**

`tests/test_import_flow.js`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createMemoryAdapter } from '../api/_lib/adapters/memory.js';
import { createRepository } from '../api/_lib/repository.js';
import { validateImportRows } from '../api/_lib/validate.js';
import { importHandler, clearHandler, importsHandler } from '../api/_lib/handlers.js';

function makeReqRes() {
  const req = { method: 'POST', headers: {}, body: '' };
  const res = { statusCode: 200, headers: {}, body: '', setHeader(k, v) { this.headers[k] = v; }, end(b) { this.body = b; } };
  return { req, res };
}

test('import handler validates then imports', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  const rows = [
    { 'Order Number': 'A', 'Item Id': '1', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': '28-Sep-2026 - 28-Sep-2026', 'Dept': '8', 'Class': '312', 'Subclass': '29' }
  ];
  const { req, res } = makeReqRes();
  req.url = '/api/admin/import?mode=replace&filename=t.xlsx';
  req.body = JSON.stringify({ rows });
  await importHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, true);
  assert.equal(body.data.row_count, 1);
  const stats = await r.getStats();
  assert.equal(stats.order_count, 1);
});

test('import handler rejects invalid rows without touching data', async () => {
  const a = createMemoryAdapter();
  a.seedOrderItems([{ order_number: 'KEEP', item_id: '1', product_name: 'P', customer_name: 'C', expected_from: '2026-01-01', expected_to: '2026-01-01', dept: 1, class: 2, subclass: 3 }]);
  const r = createRepository(a);
  const rows = [{ 'Order Number': '', 'Item Id': '1', 'Product Name': 'P', 'Customer Name': 'C', 'Original Expected Date': 'bad', 'Dept': '8', 'Class': '312', 'Subclass': '29' }];
  const { req, res } = makeReqRes();
  req.url = '/api/admin/import?mode=replace&filename=t.xlsx';
  req.body = JSON.stringify({ rows });
  await importHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.ok, false);
  assert.equal(body.error.code, 'bad_file');
  assert.equal((await r.getStats()).order_count, 1);
});

test('clear handler requires confirm', async () => {
  const a = createMemoryAdapter();
  a.seedOrderItems([{ order_number: 'X', item_id: '1', product_name: 'P', customer_name: 'C', expected_from: '2026-01-01', expected_to: '2026-01-01', dept: 1, class: 2, subclass: 3 }]);
  const r = createRepository(a);
  const { req, res } = makeReqRes();
  req.url = '/api/admin/clear';
  req.body = JSON.stringify({});
  await clearHandler(req, res, r);
  assert.equal(JSON.parse(res.body).error.code, 'validation_error');
  req.body = JSON.stringify({ confirm: true });
  await clearHandler(req, res, r);
  assert.equal((await r.getStats()).order_count, 0);
});

test('imports handler lists history', async () => {
  const a = createMemoryAdapter();
  const r = createRepository(a);
  await r.importRows({ filename: 'a.xlsx', mode: 'replace', rows: [], importedBy: 'admin' });
  const { req, res } = makeReqRes();
  req.url = '/api/admin/imports';
  await importsHandler(req, res, r);
  const body = JSON.parse(res.body);
  assert.equal(body.data.length, 1);
  assert.equal(body.data[0].filename, 'a.xlsx');
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `node --test tests/test_import_flow.js`
Expected: FAIL — handlers not found.

- [ ] **Step 3: Add admin handlers to `api/_lib/handlers.js`** (append)

```js
import { validateImportRows } from './validate.js';

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
```

Note: `importHandler` uses `readJson` — add to the import line at the top of `handlers.js`:

```js
import { ok, fail, readJson } from './http.js';
```

- [ ] **Step 4: Write the endpoint files**

`api/admin/import.js`:

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { requireAuth, requireRole } from '../_lib/auth.js';
import { importHandler } from '../_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  if (!requireRole('admin')(user, res)) return;
  req.user = user;
  return importHandler(req, res, repo);
}
```

`api/admin/imports.js`:

```js
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
```

`api/admin/clear.js`:

```js
import { createRepository } from '../_lib/repository.js';
import { getAdapter } from '../_lib/adapters/index.js';
import { requireAuth, requireRole } from '../_lib/auth.js';
import { clearHandler } from '../_lib/handlers.js';

export default async function handler(req, res) {
  const repo = createRepository(getAdapter());
  const user = await requireAuth(req, res, repo);
  if (!user) return;
  if (!requireRole('admin')(user, res)) return;
  return clearHandler(req, res, repo);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `node --test tests/test_handlers.js tests/test_import_flow.js`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add api/admin/import.js api/admin/imports.js api/admin/clear.js api/_lib/handlers.js tests/test_import_flow.js
git commit -m "feat: admin import/imports/clear endpoints with validation"
```

---

### Task 8: Frontend base — styles, api wrapper, ui helpers, login

**Files:**
- Create: `public/styles.css`
- Create: `public/js/api.js`
- Create: `public/js/ui.js`
- Create: `public/login.html`
- Create: `public/js/login.js`

- [ ] **Step 1: Write `public/js/api.js`**

```js
export async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw { code: 'network', message: 'เชื่อมต่อไม่ได้' };
  }
  let payload = {};
  try { payload = await res.json(); } catch { /* ignore */ }
  if (res.status === 401 && !path.startsWith('/api/auth/login')) {
    window.location.href = '/login.html?next=' + encodeURIComponent(window.location.pathname + window.location.search);
    throw { code: 'unauthorized', message: 'กรุณาเข้าสู่ระบบก่อน' };
  }
  if (!res.ok || !payload.ok) {
    const err = payload.error || { code: 'internal', message: 'เกิดข้อผิดพลาดในระบบ' };
    throw err;
  }
  return payload.data;
}

export async function me() {
  try { return await api('/api/auth/me'); } catch { return null; }
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST', body: {} }); } catch { /* ignore */ }
  window.location.href = '/login.html';
}
```

- [ ] **Step 2: Write `public/js/ui.js`**

```js
export function toast(message, kind = 'error') {
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('show'), 10);
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3500);
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export function skeleton(count = 3) {
  return `<div class="skeleton-card"></div>`.repeat(count);
}

export function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('th-TH', { day: '2-digit', month: 'short', year: 'numeric' });
}
```

- [ ] **Step 3: Write `public/login.html`**

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>เข้าสู่ระบบ — ค้นกลุ่มสินค้า</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body class="auth-body">
  <main class="auth-card">
    <div class="brand">
      <div class="logo">🛍️</div>
      <h1>ค้นกลุ่มสินค้า</h1>
      <p>ระบบค้นข้อมูลลูกค้าและสินค้า</p>
    </div>
    <form id="login-form" novalidate>
      <label for="username">ชื่อผู้ใช้</label>
      <input id="username" name="username" autocomplete="username" required autofocus>
      <label for="password">รหัสผ่าน</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit" class="btn btn-primary btn-block" id="submit-btn">เข้าสู่ระบบ</button>
      <p class="form-error" id="form-error" hidden></p>
    </form>
  </main>
  <script type="module" src="/js/login.js"></script>
</body>
</html>
```

- [ ] **Step 4: Write `public/js/login.js`**

```js
import { api } from './api.js';
import { toast } from './ui.js';

const form = document.getElementById('login-form');
const errorEl = document.getElementById('form-error');
const submitBtn = document.getElementById('submit-btn');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  errorEl.hidden = true;
  submitBtn.disabled = true;
  submitBtn.textContent = 'กำลังเข้าสู่ระบบ…';
  try {
    await api('/api/auth/login', {
      method: 'POST',
      body: { username: form.username.value.trim(), password: form.password.value }
    });
    const next = new URLSearchParams(window.location.search).get('next') || '/';
    window.location.href = next;
  } catch (err) {
    errorEl.hidden = false;
    errorEl.textContent = err.message;
    toast(err.message);
    submitBtn.disabled = false;
    submitBtn.textContent = 'เข้าสู่ระบบ';
  }
});
```

- [ ] **Step 5: Write `public/styles.css`** (complete design system — see Task 9 for the full file; write the full file here)

```css
:root {
  --bg: #f6f7fb;
  --surface: #ffffff;
  --text: #1a1d29;
  --muted: #6b7280;
  --primary: #4f46e5;
  --primary-strong: #4338ca;
  --primary-soft: #eef2ff;
  --danger: #dc2626;
  --danger-soft: #fee2e2;
  --success: #16a34a;
  --border: #e5e7eb;
  --radius: 14px;
  --shadow: 0 1px 3px rgba(16, 24, 40, .08), 0 8px 24px rgba(16, 24, 40, .06);
  --font: 'Noto Sans Thai', 'Segoe UI', system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1117;
    --surface: #171a21;
    --text: #e7e9ee;
    --muted: #9aa3b2;
    --primary: #6366f1;
    --primary-strong: #4f46e5;
    --primary-soft: #1e1b4b;
    --danger: #f87171;
    --danger-soft: #3b0d0d;
    --success: #34d399;
    --border: #2a2f3a;
    --shadow: 0 1px 3px rgba(0,0,0,.4), 0 8px 24px rgba(0,0,0,.3);
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: var(--font); background: var(--bg); color: var(--text); line-height: 1.5; }
a { color: var(--primary); }
.container { max-width: 980px; margin: 0 auto; padding: 16px; }
.btn {
  display: inline-flex; align-items: center; gap: 6px; justify-content: center;
  border: 0; border-radius: 10px; padding: 10px 16px; font-size: 15px; font-weight: 600;
  background: var(--primary); color: #fff; cursor: pointer; transition: transform .15s, background .2s;
}
.btn:hover { background: var(--primary-strong); }
.btn:active { transform: scale(.97); }
.btn:disabled { opacity: .55; cursor: not-allowed; }
.btn-secondary { background: transparent; color: var(--text); border: 1px solid var(--border); }
.btn-danger { background: var(--danger); }
.btn-block { width: 100%; }
input, select {
  width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px;
  background: var(--surface); color: var(--text); font-size: 15px;
}
input:focus, select:focus { outline: 2px solid var(--primary); outline-offset: 1px; }
label { font-size: 13px; font-weight: 600; color: var(--muted); display: block; margin-bottom: 6px; }
.auth-body { min-height: 100vh; display: grid; place-items: center; }
.auth-card {
  width: 100%; max-width: 400px; background: var(--surface); border-radius: 18px;
  padding: 28px; box-shadow: var(--shadow);
}
.brand { text-align: center; margin-bottom: 20px; }
.brand .logo { font-size: 40px; }
.brand h1 { font-size: 22px; margin: 8px 0 2px; }
.brand p { color: var(--muted); font-size: 14px; margin: 0; }
.form-error { color: var(--danger); font-size: 14px; margin-top: 10px; }
.toast {
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: var(--surface); color: var(--text); border: 1px solid var(--border);
  padding: 12px 18px; border-radius: 12px; box-shadow: var(--shadow); opacity: 0; transition: opacity .25s, transform .25s;
  z-index: 999;
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
.toast-error { border-color: var(--danger); color: var(--danger); }
.toast-success { border-color: var(--success); color: var(--success); }
.skeleton-card { height: 96px; border-radius: var(--radius); background: linear-gradient(90deg, var(--surface), var(--border), var(--surface)); animation: shimmer 1.2s infinite; }
@keyframes shimmer { to { background-position: -200% 0; } }
```

- [ ] **Step 6: Verify pages load (static check)**

Run: `node --check public/js/api.js && node --check public/js/ui.js && node --check public/js/login.js`
Expected: no output (syntax OK).

- [ ] **Step 7: Commit**

```bash
git add public/styles.css public/js/api.js public/js/ui.js public/login.html public/js/login.js
git commit -m "feat: frontend base (styles, api wrapper, ui helpers, login page)"
```

---

### Task 9: Frontend — index (search + detail)

**Files:**
- Create: `public/index.html`
- Create: `public/js/index.js`

- [ ] **Step 1: Write `public/index.html`**

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ค้นกลุ่มสินค้า</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header class="topbar">
    <div class="container topbar-inner">
      <a href="/" class="brand-link">🛍️ <span>ค้นกลุ่มสินค้า</span></a>
      <div class="topbar-right">
        <span class="role-badge" id="role-badge" hidden></span>
        <a href="/admin.html" class="admin-link" id="admin-link" hidden>จัดการข้อมูล</a>
        <button class="btn btn-secondary btn-sm" id="logout-btn">ออกจากระบบ</button>
      </div>
    </div>
  </header>

  <main class="container">
    <section class="hero">
      <h1>ค้นกลุ่มสินค้าที่ลูกค้าเคยซื้อ</h1>
      <div class="search-row">
        <div class="dir-toggle" role="tablist">
          <button class="dir-btn active" data-dir="customer" role="tab" aria-selected="true">ค้นด้วยชื่อลูกค้า</button>
          <button class="dir-btn" data-dir="product" role="tab" aria-selected="false">ค้นด้วยชื่อสินค้า</button>
        </div>
        <input id="search-input" type="search" placeholder="พิมพ์ชื่อเพื่อค้น…" autocomplete="off" autofocus>
      </div>
      <div class="filters" id="filters">
        <select id="f-dept" data-kind="dept"><option value="">ทุกฝ่าย (Dept)</option></select>
        <select id="f-class" data-kind="class"><option value="">ทุกกลุ่ม (Class)</option></select>
        <select id="f-subclass" data-kind="subclass"><option value="">ทุกประเภทย่อย (Subclass)</option></select>
        <button class="btn btn-secondary btn-sm" id="clear-filters">ล้างตัวกรอง</button>
      </div>
    </section>

    <section id="results" class="results" aria-live="polite"></section>
    <div id="pagination" class="pagination" hidden></div>
  </main>

  <script type="module" src="/js/index.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `public/js/index.js`**

```js
import { api, me, logout } from './api.js';
import { toast, escapeHtml, debounce, skeleton, formatDate } from './ui.js';

const state = {
  q: '', dir: 'customer', dept: '', cls: '', subclass: '', page: 1,
  view: 'search' // 'search' | 'customer' | 'product'
};

const resultsEl = document.getElementById('results');
const searchInput = document.getElementById('search-input');
const paginationEl = document.getElementById('pagination');

function readUrl() {
  const p = new URLSearchParams(window.location.search);
  state.q = p.get('q') || '';
  state.dir = p.get('dir') === 'product' ? 'product' : 'customer';
  state.dept = p.get('dept') || '';
  state.cls = p.get('class') || '';
  state.subclass = p.get('subclass') || '';
  state.page = Number(p.get('page') || '1');
  state.view = p.get('view') || 'search';
}

function writeUrl() {
  const p = new URLSearchParams();
  if (state.q) p.set('q', state.q);
  p.set('dir', state.dir);
  if (state.dept) p.set('dept', state.dept);
  if (state.cls) p.set('class', state.cls);
  if (state.subclass) p.set('subclass', state.subclass);
  if (state.page > 1) p.set('page', String(state.page));
  if (state.view !== 'search') p.set('view', state.view);
  history.pushState({}, '', '/?' + p.toString());
}

function renderHeader() {
  const u = window.__user;
  const badge = document.getElementById('role-badge');
  const adminLink = document.getElementById('admin-link');
  if (u) {
    badge.hidden = false;
    badge.textContent = u.role === 'admin' ? 'ผู้ดูแล' : 'ผู้ดู';
    adminLink.hidden = u.role !== 'admin';
  }
}

async function loadFilters() {
  const params = new URLSearchParams();
  if (state.dept) params.set('dept', state.dept);
  if (state.cls) params.set('class', state.cls);
  const data = await api('/api/filters?' + params.toString());
  fillSelect('f-dept', data.depts, state.dept, 'ทุกฝ่าย (Dept)');
  fillSelect('f-class', data.classes, state.cls, 'ทุกกลุ่ม (Class)');
  fillSelect('f-subclass', data.subclasses, state.subclass, 'ทุกประเภทย่อย (Subclass)');
}

function fillSelect(id, values, current, placeholder) {
  const el = document.getElementById(id);
  el.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` +
    values.map((v) => `<option value="${v}" ${String(v) === String(current) ? 'selected' : ''}>${v}</option>`).join('');
}

function groupBadges(groups) {
  return groups.map((g) => `<span class="chip">${g.dept}/${g.class}/${g.subclass} ×${g.count}</span>`).join('');
}

function renderSearchResults(data) {
  if (data.total === 0) {
    resultsEl.innerHTML = `<div class="empty"><div class="empty-icon">🔍</div><h2>ไม่พบผลลัพธ์</h2><p>ลองเปลี่ยนคำค้นหรือล้างตัวกรอง</p></div>`;
    paginationEl.hidden = true;
    return;
  }
  const cards = data.items.map((it) => {
    if (state.dir === 'customer') {
      const vip = it.vip_groups.length ? `<span class="vip">⭐ ${escapeHtml(it.vip_groups.join(', '))}</span>` : '';
      return `<article class="card" data-customer="${escapeHtml(it.customer_name)}" tabindex="0">
        <div class="card-main">
          <h3>${escapeHtml(it.customer_name)}</h3>
          <div class="stats">${it.order_count} ออเดอร์ · ${it.product_count} กลุ่มสินค้า · ล่าสุด ${formatDate(it.last_expected)}</div>
          <div class="chips">${groupBadges(it.groups)}</div>
          ${vip}
        </div>
        <div class="card-arrow">→</div>
      </article>`;
    }
    return `<article class="card" data-item="${escapeHtml(it.item_id)}" tabindex="0">
      <div class="card-main">
        <h3>${escapeHtml(it.product_name)}</h3>
        <div class="stats">${it.order_count} ครั้ง · ${it.customer_count} ลูกค้า</div>
        <div class="chips">${groupBadges(it.groups)}</div>
      </div>
      <div class="card-arrow">→</div>
    </article>`;
  }).join('');
  resultsEl.innerHTML = cards;
  const pages = Math.max(1, Math.ceil(data.total / 50));
  paginationEl.hidden = pages <= 1;
  paginationEl.innerHTML = `<button class="btn btn-secondary btn-sm" id="prev-page" ${state.page <= 1 ? 'disabled' : ''}>ก่อนหน้า</button>
    <span>หน้า ${state.page} / ${pages}</span>
    <button class="btn btn-secondary btn-sm" id="next-page" ${state.page >= pages ? 'disabled' : ''}>หน้าถัดไป</button>`;
  document.querySelectorAll('.card').forEach((c) => c.addEventListener('click', () => openDetail(c)));
  document.querySelectorAll('.card').forEach((c) => c.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(c); }));
}

async function doSearch() {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  params.set('direction', state.dir);
  if (state.dept) params.set('dept', state.dept);
  if (state.cls) params.set('class', state.cls);
  if (state.subclass) params.set('subclass', state.subclass);
  params.set('page', String(state.page));
  resultsEl.innerHTML = skeleton(3);
  try {
    const data = await api('/api/search?' + params.toString());
    renderSearchResults(data);
  } catch (err) {
    resultsEl.innerHTML = `<div class="empty"><h2>เชื่อมต่อไม่ได้</h2><button class="btn" onclick="location.reload()">ลองใหม่</button></div>`;
  }
}

async function openDetail(card) {
  if (state.dir === 'customer') {
    state.view = 'customer';
    state.customer = card.dataset.customer;
  } else {
    state.view = 'product';
    state.item = card.dataset.item;
  }
  writeUrl();
  await renderDetail();
}

async function renderDetail() {
  resultsEl.innerHTML = skeleton(2);
  try {
    if (state.view === 'customer') {
      const d = await api('/api/customer?name=' + encodeURIComponent(state.customer));
      resultsEl.innerHTML = detailCustomer(d);
    } else {
      const d = await api('/api/product?item_id=' + encodeURIComponent(state.item));
      resultsEl.innerHTML = detailProduct(d);
    }
  } catch (err) {
    resultsEl.innerHTML = `<div class="empty"><h2>${escapeHtml(err.message)}</h2></div>`;
  }
}

function detailCustomer(d) {
  const rows = d.orders.map((o) => `<tr>
    <td>${escapeHtml(o.order_number)}</td>
    <td>${escapeHtml(o.product_name)}</td>
    <td>${formatDate(o.expected_from)}</td>
    <td>${o.dept}/${o.class}/${o.subclass}</td>
    <td>${escapeHtml(o.item_remark || '')}</td>
  </tr>`).join('');
  return `<div class="detail-head">
      <button class="btn btn-secondary btn-sm" id="back-btn">← กลับ</button>
      <h2>${escapeHtml(d.customer_name)}</h2>
      <div class="stats">${d.order_count} ออเดอร์ · ${d.product_count} กลุ่มสินค้า</div>
      <div class="chips">${groupBadges(d.groups)}</div>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>ออเดอร์</th><th>สินค้า</th><th>วันที่</th><th>กลุ่ม</th><th>หมาย</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function detailProduct(d) {
  const rows = d.customers.map((c) => `<tr><td>${escapeHtml(c)}</td></tr>`).join('');
  return `<div class="detail-head">
      <button class="btn btn-secondary btn-sm" id="back-btn">← กลับ</button>
      <h2>${escapeHtml(d.product_name)}</h2>
      <div class="stats">${d.order_count} ครั้ง · ${d.customer_count} ลูกค้า</div>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>ลูกค้า</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function bindEvents() {
  searchInput.value = state.q;
  document.querySelectorAll('.dir-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.dir === state.dir);
    b.addEventListener('click', () => { state.dir = b.dataset.dir; state.page = 1; writeUrl(); syncInputs(); doSearch(); });
  });
  const onFilter = (key) => (e) => { state[key] = e.target.value; state.page = 1; writeUrl(); loadFilters(); doSearch(); };
  document.getElementById('f-dept').addEventListener('change', onFilter('dept'));
  document.getElementById('f-class').addEventListener('change', onFilter('cls'));
  document.getElementById('f-subclass').addEventListener('change', onFilter('subclass'));
  document.getElementById('clear-filters').addEventListener('click', () => { state.dept = state.cls = state.subclass = ''; state.page = 1; writeUrl(); loadFilters(); doSearch(); });
  document.getElementById('logout-btn').addEventListener('click', logout);
  const debounced = debounce(() => { state.q = searchInput.value.trim(); state.page = 1; writeUrl(); doSearch(); });
  searchInput.addEventListener('input', debounced);
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { state.q = searchInput.value.trim(); state.page = 1; writeUrl(); doSearch(); } });
  document.addEventListener('click', (e) => { if (e.target.id === 'back-btn') { state.view = 'search'; history.back(); } });
  document.addEventListener('click', (e) => {
    if (e.target.id === 'prev-page') { state.page = Math.max(1, state.page - 1); writeUrl(); doSearch(); }
    if (e.target.id === 'next-page') { state.page++; writeUrl(); doSearch(); }
  });
}

function syncInputs() {
  searchInput.value = state.q;
  document.querySelectorAll('.dir-btn').forEach((b) => b.classList.toggle('active', b.dataset.dir === state.dir));
}

async function init() {
  readUrl();
  window.__user = await me();
  renderHeader();
  bindEvents();
  loadFilters().catch(() => {});
  if (state.view === 'customer' || state.view === 'product') {
    state.customer = new URLSearchParams(window.location.search).get('customer') || state.q;
    state.item = new URLSearchParams(window.location.search).get('item') || state.q;
    await renderDetail();
  } else if (state.q) {
    await doSearch();
  }
}

init();
```

- [ ] **Step 3: Append detail styles to `public/styles.css`**

```css
.topbar { position: sticky; top: 0; background: var(--surface); border-bottom: 1px solid var(--border); z-index: 10; }
.topbar-inner { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.brand-link { font-weight: 700; text-decoration: none; color: var(--text); display: inline-flex; align-items: center; gap: 8px; }
.topbar-right { display: flex; align-items: center; gap: 10px; }
.role-badge { font-size: 12px; background: var(--primary-soft); color: var(--primary); padding: 3px 10px; border-radius: 999px; }
.admin-link { font-size: 14px; }
.btn-sm { padding: 6px 12px; font-size: 13px; }
.hero { padding: 24px 0; }
.hero h1 { font-size: 24px; margin: 0 0 16px; }
.search-row { display: flex; flex-direction: column; gap: 12px; }
.dir-toggle { display: inline-flex; gap: 4px; background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 4px; }
.dir-btn { border: 0; background: transparent; padding: 8px 14px; border-radius: 999px; font-size: 14px; cursor: pointer; color: var(--muted); }
.dir-btn.active { background: var(--primary); color: #fff; }
#search-input { font-size: 18px; padding: 14px 16px; border-radius: 12px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.filters select { width: auto; min-width: 140px; }
.results { display: grid; gap: 14px; margin-top: 8px; }
.card { display: flex; align-items: center; gap: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px; box-shadow: var(--shadow); cursor: pointer; transition: transform .15s, box-shadow .2s; }
.card:hover { transform: translateY(-2px); box-shadow: 0 4px 16px rgba(16,24,40,.15); }
.card:focus-visible { outline: 2px solid var(--primary); }
.card-main { flex: 1; }
.card h3 { margin: 0 0 6px; font-size: 17px; }
.stats { color: var(--muted); font-size: 13px; margin-bottom: 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: var(--primary-soft); color: var(--primary); font-size: 12px; padding: 3px 9px; border-radius: 999px; }
.vip { color: #b45309; font-size: 13px; }
.card-arrow { color: var(--muted); font-size: 20px; }
.pagination { display: flex; align-items: center; gap: 12px; justify-content: center; margin: 20px 0; }
.empty { text-align: center; padding: 48px 0; color: var(--muted); }
.empty-icon { font-size: 40px; }
.detail-head { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.detail-head h2 { margin: 0; }
.table-wrap { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; background: var(--surface); border-radius: var(--radius); }
.data-table th, .data-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 14px; }
.data-table th { color: var(--muted); font-weight: 600; }
```

- [ ] **Step 4: Verify syntax**

Run: `node --check public/js/index.js`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add public/index.html public/js/index.js public/styles.css
git commit -m "feat: search-first home with detail views"
```

---

### Task 10: Frontend — admin page

**Files:**
- Create: `public/admin.html`
- Create: `public/js/admin.js`

- [ ] **Step 1: Write `public/admin.html`**

```html
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>จัดการข้อมูล — ค้นกลุ่มสินค้า</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <header class="topbar">
    <div class="container topbar-inner">
      <a href="/" class="brand-link">🛍️ <span>ค้นกลุ่มสินค้า</span></a>
      <div class="topbar-right">
        <span class="role-badge">ผู้ดูแล</span>
        <a href="/" class="admin-link">← กลับไปค้น</a>
        <button class="btn btn-secondary btn-sm" id="logout-btn">ออกจากระบบ</button>
      </div>
    </div>
  </header>

  <main class="container">
    <h1>จัดการข้อมูล</h1>

    <section class="panel">
      <h2>นำเข้าข้อมูล (ไฟล์ xlsx)</h2>
      <div class="import-form">
        <label for="file-input">เลือกไฟล์</label>
        <input id="file-input" type="file" accept=".xlsx">
        <div class="preview" id="preview" hidden>
          <p><strong id="preview-name"></strong> — <span id="preview-rows"></span> แถว</p>
          <p class="muted" id="preview-headers"></p>
        </div>
        <div class="mode-row">
          <label><input type="radio" name="mode" value="replace" checked> แแทนที่ทั้งหมด</label>
          <label><input type="radio" name="mode" value="append"> เพิ่มต่อท้าย</label>
        </div>
        <button class="btn" id="import-btn" disabled>นำเข้าข้อมูล</button>
        <p class="form-error" id="import-error" hidden></p>
      </div>
    </section>

    <section class="panel">
      <h2>ประวัติการนำเข้า</h2>
      <div class="table-wrap"><table class="data-table" id="imports-table">
        <thead><tr><th>ไฟล์</th><th>โหมด</th><th>แถว</th><th>โดย</th><th>เวลา</th></tr></thead>
        <tbody></tbody>
      </table></div>
    </section>

    <section class="panel panel-danger">
      <h2>เขตอันตราย</h2>
      <p class="muted">ลบข้อมูลออเดอร์ทั้งหมดจากระบบ (ไม่สามารถย้อนกลับ)</p>
      <label for="confirm-input">พิมพ์ <code>ลบทั้งหมด</code> เพื่อยืนยัน</label>
      <input id="confirm-input" autocomplete="off">
      <button class="btn btn-danger" id="clear-btn" disabled>ลบข้อมูลทั้งหมด</button>
    </section>
  </main>

  <script src="/vendor/xlsx.full.min.js"></script>
  <script type="module" src="/js/admin.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `public/js/admin.js`**

```js
import { api, me, logout } from './api.js';
import { toast, escapeHtml } from './ui.js';

const fileInput = document.getElementById('file-input');
const preview = document.getElementById('preview');
const importBtn = document.getElementById('import-btn');
const importError = document.getElementById('import-error');
const confirmInput = document.getElementById('confirm-input');
const clearBtn = document.getElementById('clear-btn');

let pendingRows = null;
let pendingName = '';

async function guard() {
  const u = await me();
  if (!u) { window.location.href = '/login.html?next=/admin.html'; return null; }
  if (u.role !== 'admin') {
    toast('ไม่มีสิทธิ์เข้าถึง');
    setTimeout(() => { window.location.href = '/'; }, 1200);
    return null;
  }
  return u;
}

function readWorkbook(file) {
  const reader = new FileReader();
  return new Promise((resolve, reject) => {
    reader.onload = (e) => {
      try {
        const wb = XLSX.read(e.target.result, { type: 'array' });
        const sheet = wb.Sheets[0];
        const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '' });
        const header = rows[0];
        const data = rows.slice(1).filter((r) => r.some((c) => String(c).trim() !== ''));
        const objs = data.map((r) => {
          const o = {};
          header.forEach((h, i) => { o[String(h).trim()] = r[i]; });
          return o;
        });
        resolve({ name: file.name, rows: objs });
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('อ่านไฟล์ไม่ได้'));
    reader.readAsArrayBuffer(file);
  });
}

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;
  importError.hidden = true;
  try {
    const { name, rows } = await readWorkbook(file);
    pendingRows = rows;
    pendingName = name;
    preview.hidden = false;
    document.getElementById('preview-name').textContent = name;
    document.getElementById('preview-rows').textContent = String(rows.length);
    document.getElementById('preview-headers').textContent = Object.keys(rows[0] || {}).join(', ');
    importBtn.disabled = rows.length === 0;
  } catch (err) {
    toast('อ่านไฟล์ไม่ได้: ' + err.message);
    importBtn.disabled = true;
  }
});

importBtn.addEventListener('click', async () => {
  if (!pendingRows) return;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  importBtn.disabled = true;
  importBtn.textContent = 'กำลังนำเข้า…';
  try {
    const data = await api('/api/admin/import?mode=' + mode + '&filename=' + encodeURIComponent(pendingName), {
      method: 'POST', body: { rows: pendingRows }
    });
    toast(`นำเข้าสำเร็จ: ${data.row_count} แถว`, 'success');
    await loadImports();
    preview.hidden = true;
    fileInput.value = '';
    pendingRows = null;
  } catch (err) {
    importError.hidden = false;
    importError.textContent = err.message;
    toast(err.message);
  } finally {
    importBtn.disabled = false;
    importBtn.textContent = 'นำเข้าข้อมูล';
  }
});

async function loadImports() {
  try {
    const data = await api('/api/admin/imports');
    const tbody = document.querySelector('#imports-table tbody');
    tbody.innerHTML = data.map((i) => `<tr>
      <td>${escapeHtml(i.filename)}</td>
      <td>${i.mode === 'replace' ? 'แทนที่' : 'เพิ่มต่อท้าย'}</td>
      <td>${i.row_count}</td>
      <td>${escapeHtml(i.imported_by || '')}</td>
      <td>${new Date(i.imported_at).toLocaleString('th-TH')}</td>
    </tr>`).join('');
  } catch { /* toast handled by api wrapper */ }
}

confirmInput.addEventListener('input', () => {
  clearBtn.disabled = confirmInput.value.trim() !== 'ลบทั้งหมด';
});

clearBtn.addEventListener('click', async () => {
  clearBtn.disabled = true;
  try {
    await api('/api/admin/clear', { method: 'POST', body: { confirm: true } });
    toast('ลบข้อมูลทั้งหมดสำเร็จ', 'success');
    confirmInput.value = '';
    clearBtn.disabled = true;
  } catch (err) {
    toast(err.message);
    clearBtn.disabled = false;
  }
});

document.getElementById('logout-btn').addEventListener('click', logout);

const user = await guard();
if (user) {
  await loadImports();
}
```

- [ ] **Step 3: Append admin styles to `public/styles.css`**

```css
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 20px; box-shadow: var(--shadow); }
.panel h2 { margin: 0 0 14px; font-size: 18px; }
.panel-danger { border-color: var(--danger); }
.panel-danger h2 { color: var(--danger); }
.import-form { display: flex; flex-direction: column; gap: 12px; }
.preview { background: var(--primary-soft); border-radius: 10px; padding: 10px 14px; }
.mode-row { display: flex; gap: 12px; }
.mode-row label { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; }
.muted { color: var(--muted); font-size: 13px; }
code { background: var(--primary-soft); padding: 1px 6px; border-radius: 6px; font-size: 13px; }
```

- [ ] **Step 4: Verify syntax**

Run: `node --check public/js/admin.js`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add public/admin.html public/js/admin.js public/styles.css
git commit -m "feat: admin page (import xlsx, history, clear data)"
```

---

### Task 11: create-user script, README, final verification

**Files:**
- Create: `scripts/create-user.js`
- Modify: `README.md`

- [ ] **Step 1: Write `scripts/create-user.js`**

```js
import { createClient } from '@supabase/supabase-js';
import { loadConfig } from '../api/_lib/config.js';
import { hashPassword } from '../api/_lib/passwords.js';

const [role, username] = process.argv.slice(2);
if (!['admin', 'viewer'].includes(role) || !username) {
  console.error('Usage: node scripts/create-user.js <admin|viewer> <username>');
  process.exit(1);
}
const password = process.env.USER_PASSWORD;
if (!password) {
  console.error('Set USER_PASSWORD env var for the new user password');
  process.exit(1);
}
const cfg = loadConfig();
const sb = createClient(cfg.supabaseUrl, cfg.supabaseKey);
const { data, error } = await sb.from('users').insert({ username, password_hash: hashPassword(password), role });
if (error) {
  console.error('Failed:', error.message);
  process.exit(1);
}
console.log(`Created ${role} user "${username}"`);
```

- [ ] **Step 2: Update `README.md`** with: prerequisites (Node 20+, Supabase project), setup steps (run `migrations/001_schema.sql` in Supabase SQL editor → `npm install` → copy `.env.example` → `.env` fill → `npm run dev`), create users (`USER_PASSWORD=... node scripts/create-user.js admin boss`), deploy (`vercel`), and the smoke checklist.

- [ ] **Step 3: Run the full test suite**

Run: `node --test tests/`
Expected: all PASS.

- [ ] **Step 4: Syntax-check every JS file**

Run: `node --check api/_lib/*.js api/_lib/adapters/*.js api/auth/*.js api/admin/*.js api/search.js api/search/orders.js api/customer.js api/product.js api/filters.js api/stats.js public/js/*.js scripts/create-user.js`
Expected: no output.

- [ ] **Step 5: Smoke checklist (manual, needs real Supabase env)**

1. `npm run dev` → open `http://localhost:3000`
2. Not logged in → redirected to `/login.html`
3. Login as admin → lands on `/`
4. Admin → `/admin.html` → import `simpledata_1000rows.xlsx` (replace) → success toast
5. Search "সুনীই" (customer) → card shows order count + group chips
6. Search a product name (product) → card shows customer count
7. Click card → detail table renders; browser back works
8. Login as viewer → `/admin.html` → toast "ไม่มีสิทธิ์เข้าถ့" + redirect to `/`
9. Admin → clear data → typed confirm → success
10. `vercel` deploy → repeat steps 2–9 on the deployed URL

- [ ] **Step 6: Commit**

```bash
git add scripts/create-user.js README.md
git commit -m "feat: create-user script, README, final verification"
```

---

## Self-Review

**Spec coverage:**
- Search both directions + filters + detail → Task 6, 9 ✓
- Login admin/viewer, viewer read-only → Task 5, 7 (requireRole) ✓
- Admin import (replace/append) + clear → Task 7, 10 ✓
- Central API / repository abstraction → Task 3, 4 ✓
- Supabase schema `order_item` → Task 1 ✓
- Thai UI, search-first + dashboard hybrid → Task 8, 9 ✓
- Error handling (typed codes, Thai messages) → Task 2, 6, 7 ✓
- Testing (unit + contract + import flow) → Tasks 2–7 ✓
- create-user script (no default password) → Task 11 ✓

**Placeholder scan:** No TBD/TODO; every step has concrete code or commands.

**Type consistency:** `queryOrderRows` params (`q, direction, dept, cls, subclass, customerNorm, itemId, limit`) identical across memory adapter, supabase adapter, and repository. `importRows({filename, mode, rows, importedBy})` consistent. `searchCustomers/searchProducts/searchOrders/getCustomer/getProduct/listFilters/getStats` signatures match between repository and handlers. `requireAuth(req, res, repo)` returns user object `{id, username, role}` everywhere.

**Known deviation from spec:** import upload is raw JSON rows (client parses xlsx with vendored SheetJS) instead of server-side multipart — avoids heavy server deps and Vercel function size limits; server still validates everything.