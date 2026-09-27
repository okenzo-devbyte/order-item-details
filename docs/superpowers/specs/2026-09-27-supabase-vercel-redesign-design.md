# Supabase + Vercel redesign

Date: 2026-09-27
Status: proposed

## Context

The system answers two questions in Thai on a phone: what has this customer
bought before, and who bought this product. It shipped as a FastAPI service
that decrypts a sealed SQLite snapshot into memory at boot, plus a PWA.

Deployment has not succeeded. Render could not be connected to GitHub, the
Docker Hub push needed a token scope the account did not have, and Hugging Face
Spaces could not be signed up for. The service currently runs only on a
developer's machine on the LAN.

More importantly, updating data is slow: the workbook is the source of truth,
so every new workbook means building a new encrypted snapshot, rebuilding the
container image and redeploying. That is the problem this redesign removes.

## Goals

- Uploading a new workbook through the web UI makes the new data searchable
  within about a minute, with no image build and no redeploy.
- The service deploys to Vercel without connecting a Git provider.
- The database is a real Postgres database that can be inspected, queried and
  extended later.
- Search results stay identical to the current implementation. This is a
  storage and deployment change, not a behaviour change.

## Non-goals

- No change to the PWA interface, and no change to the request and response
  shapes of the search, suggest, filter, detail, auth, user-management and
  audit endpoints. The admin import endpoints are the one exception: they are
  replaced by the job and step endpoints described below.
- No change to the Thai text normalisation rules or the ranking cutoffs.
- No customer self-service. The service remains staff and admin only.
- No column-level encryption of customer data (see Risks).

## Architecture

```
phone (PWA)  ->  Vercel Function (FastAPI)  ->  Supabase Postgres
                                     via shared pooler, transaction mode
```

Removed: `snapshot.enc`, `DATA_KEY`, `api/crypto.py`, `api/snapshot.py`, the
AES-256-GCM envelope, the FTS5 rebuild-on-load recovery, the Render disk mode,
`Dockerfile`, `.dockerignore`, `render.yaml`, `scripts/deploy_render.py`.

Reused unchanged: `src/order_search/textnorm.py` (three-column
normalisation), `search/detect.py`, `search/fuzzy.py`, `search/filters.py`, the
four cutoffs, `api/passwords.py`, the JWT and cookie design, the whole of
`web/`, and the request and response shapes of every endpoint except admin
import. What changes inside the search router is only where it reads from:
`request.app.state.snapshot` becomes a pooled Postgres client.

## Database schema

Three namespaces. Supabase grants `anon` and `authenticated` USAGE on `public`
only, so tables in other namespaces are unreachable through the Data API.

### `item`

| relation | kind | contents |
|----------|------|----------|
| `item.products_v{n}` | table | `id bigint primary key`, `name`, `name_norm`, `name_fold_light`, `name_fold_heavy`, `dept`, `class_code`, `subclass_code`, `pack_size`, `unit` |
| `item.product_barcodes_v{n}` | table | `product_id`, `barcode`, primary key `(product_id, barcode)` |
| `item.products` | view | points at the current version's table |
| `item.product_barcodes` | view | points at the current version's table |

Indexes on each version's tables:

```
products_v{n}            gin (name_norm gin_trgm_ops)
                         gin (name_fold_light gin_trgm_ops)
                         btree (dept), (class_code), (subclass_code)
product_barcodes_v{n}    btree (barcode)
```

`barcode` is deliberately not unique: one barcode may map to two products.

### `sales`

| relation | kind | contents |
|----------|------|----------|
| `sales.customers_v{n}` | table | `id bigint primary key`, `name`, `name_norm`, `name_fold_light`, `name_fold_heavy`, unique index on `name_norm` |
| `sales.orders_v{n}` | table | `id bigint primary key`, `order_no`, `store_code`, `customer_id`, `order_type`, `date_from`, `date_to`, `item_remark`, `vip_remark`, `vip_group` |
| `sales.order_items_v{n}` | table | `order_id`, `product_id`, `qty`, `price`, primary key `(order_id, product_id)` |
| `sales.customers` / `.orders` / `.order_items` | views | point at the current version's tables |

Indexes on each version's tables:

```
customers_v{n}           unique btree (name_norm), gin (name_norm gin_trgm_ops)
orders_v{n}              btree (customer_id), (store_code), (order_type),
                                (vip_group), (date_from), (date_to)
order_items_v{n}         btree (product_id)
```

`vip_group` and `vip_remark` stay on the order: in the real data every customer
carries several tiers across their own orders, so they cannot be lifted to the
customer level. `date_from` and `date_to` get one index each rather than a
composite, because the overlap query tests `date_from <= :to AND date_to >=
:from` and Postgres can only use the leftmost column of a composite.

There is no `stores` table. `store_code` is a column on `orders`, and the facet
list reads distinct values from there, exactly as the SQLite build does.

### `app`

| relation | purpose |
|----------|---------|
| `app.users` | username, argon2id hash, role, is_active |
| `app.refresh_tokens` | hashed token, `revoked_at`, expiry |
| `app.audit_log` | append-only action log |
| `app.data_versions` | one row per imported version: counts, filename, imported_at, imported_by, is_current |
| `app.import_jobs` | state machine for a running import |
| `app.stg_*` | staging tables, truncated at the start of every import |
| `app.rate_buckets` | request counters shared across instances |

### Versioning

Each import writes into fresh `{table}_v{n}` tables. Activation is
`CREATE OR REPLACE VIEW`, which is atomic, so the swap is instantaneous and
there is no window in which a reader sees a half-written dataset.

- **Update data**: fill `products_v3`, then re-point the five views.
- **Roll back**: re-point the views at the previous version. One click.
- **Retain one previous**: after activation, `DROP TABLE` the version older
  than the retained one.
- **Query cost**: none. Filters never mention a version, so indexes are used
  normally. Putting `version_id` in a `WHERE` clause instead would have
  required partial indexes and would have been the wrong trade.

## Search

The four layers are unchanged. Only the third layer's SQL differs.

| layer | SQLite | Postgres |
|-------|--------|----------|
| 1 barcode | btree lookup | identical |
| 2 customer name | exact, then `WRatio` over 20 names | identical, plus the trigram index so it scales past that |
| 3 product text | `products_fts MATCH` ranked by `bm25()` | `name_norm LIKE '%' \|\| :q \|\| '%'` limited to 200 candidates, ranked by rapidfuzz |
| 4 fuzzy | widen on the tone-stripped form, confirm against the original | identical |

Losing BM25 is acceptable because the final ranking already used `WRatio`, which
the implementation trusts more. `STAGE1_CUTOFF` (40), `FINAL_CUTOFF` (70) and
`CUSTOMER_FUZZY_CUTOFF` (70) are untouched.

A query shorter than three characters cannot use a trigram index in either
engine, so it falls back to a prefix match. This limit is pre-existing and is
documented in the README.

A search costs about three round trips: detection, product candidates, then
aggregate counts. At roughly 100 ms from Vercel to Supabase that is about
300 ms. If it measures slower, the three queries merge into one CTE.

## Import pipeline

A hundred thousand rows cannot finish inside one Vercel invocation, and a run
that dies halfway must not restart from zero. All state therefore lives in
Postgres, and the browser drives the machine.

```
POST /api/v1/admin/import             upload .xlsx, store in Storage, create job
POST /api/v1/admin/import/{id}/step   perform one bounded unit of work
GET  /api/v1/admin/import/{id}        poll for status
```

States: `pending -> parsing -> staging -> activating -> done`, or `failed`.

**parse** opens the workbook from Supabase Storage in read-only mode, skips to
`progress.last_row`, normalises the text, and `COPY`s up to 5,000 rows into
`app.stg_*` through psycopg3's binary copy. Each batch is copied into its own
temporary table and then merged with `INSERT ... ON CONFLICT DO NOTHING` keyed
on the source row number. An instance that dies between the copy and the
progress update therefore repeats a batch without duplicating rows.

**transform** creates the version's tables and populates them with
`INSERT ... SELECT` from staging, then records the row counts.

**activate** re-points the five views, marks the new version current, drops the
version that falls outside the retention window, truncates staging, deletes the
stored workbook, and marks the job done.

**A failed import leaves the service serving the previous version.** The views
only move after transform succeeds, so no failure mode can leave the system
without data.

Only one import may be active at a time, enforced by a partial unique index on
`app.import_jobs(status)`.

**Cost.** Each `step` re-opens the workbook and skips to the cursor, which
costs roughly 6 to 10 seconds at 100,000 rows. Twenty steps is two to three
minutes overall, which suits a weekly or monthly import. If that becomes
painful, the first step can also write an NDJSON copy to Storage for later
steps to read; that is deliberately not built now.

The workbook contains unencrypted personal data, so the `order-imports` bucket
is private, is reached only with the service role, and the object is deleted on
both success and failure.

### Rejected alternatives

- **Browser uploads rows one at a time through the Supabase Data API.** Puts
  personal data through the client and cannot work at 100,000 rows.
- **A Supabase Edge Function performs the import.** Adds a second runtime to
  maintain when 60 seconds is sufficient.

## Security

Unchanged: argon2id password hashing, 15-minute access token and 7-day refresh
token in httpOnly cookies, single-use refresh rotation through
`UPDATE ... SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL
RETURNING id`, role dependencies, CSRF double-submit with an exact-origin
check, personal data only in POST bodies, and `Cache-Control: no-store` on
`/api/*`.

Changed:

- **Rate limiting moves into the database.** The in-process limiter counted per
  instance, which on Vercel means per warm instance, so the 60-per-minute limit
  would not hold. Counters live in `app.rate_buckets`, keyed by user id or
  client IP and route bucket with a one-minute window. This costs one extra
  query per request and is the price of a limit that means anything.
- **`DATA_KEY` no longer exists.** It is the strongest control the old design
  had and it goes away with the snapshot.

Namespaces give an unplanned protection: because `anon` and `authenticated`
have no USAGE on `item`, `sales` or `app`, the Supabase Data API cannot address
these tables at all. Migrations add an explicit `REVOKE`.

`DATABASE_URL` uses `sslmode=require`. The service authenticates to Postgres
with the database password, which exists only in Vercel's environment.

## Vercel deployment

`vercel.json`:

```json
{
  "regions": ["sin1"],
  "functions": { "index.py": { "maxDuration": 60 } }
}
```

`index.py` at the repository root is a shim, `from api.main import app`. Vercel
looks for a `FastAPI` instance named `app` at a supported entrypoint. If it
resolves `api/` as a functions directory instead, the fallback is
`[tool.vercel] entrypoint = "api.main:app"` in `pyproject.toml`.

The Supabase project is created in `sin1` to match the function region.

Static files keep being served by the existing `app.mount()`. Because the app
has top-level middleware, Vercel keeps those files in the function rather than
promoting them to the CDN, which is what we want: the CSP and HSTS headers then
apply to the shell as well as the API.

Connection management follows the Supabase serverless guidance: one client at
module scope, pool size 1, `prepare_threshold=0` because transaction mode does
not support prepared statements, and `sslmode=require`.

Environment variables:

| name | purpose |
|------|---------|
| `DATABASE_URL` | shared pooler, transaction mode, port 6543 |
| `SECRET_KEY` | JWT signing and cookie encryption |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | first-run bootstrap |
| `COOKIE_SECURE` | `true` |
| `DB_SCHEMA_ITEM`, `DB_SCHEMA_SALES`, `DB_SCHEMA_APP` | default `item`, `sales`, `app` |

The exact-origin CSRF check compares the `Origin` header against the request's
own host, so no additional origin allowlist is needed. `ALLOWED_HOSTS` keeps its
existing meaning.

`scripts/load_postgres.py` performs the first load from a terminal, where the
60-second limit does not apply, reusing the same parsing code as the web path.

## Testing

The honest cost of this port: today `pytest` runs with no external dependency.
Afterwards, every test that touches storage needs a real Postgres.

Kept as-is and still offline: `textnorm`, `detect`, `fuzzy`, `filters`,
`test_passwords`, `test_pwa`, validation and schema tests.

Rewritten against a real database using `TEST_DATABASE_URL` and the schemas
`t_item`, `t_sales`, `t_app`, created and dropped by a session fixture.
Production data is never touched.

The tests that matter most prove the search rewrite did not change behaviour:

- `สุรชัย` returns one customer with 65 order lines
- `8850250001234` returns `น้ำดื่มสิงห์ 600 มล. x 12`
- `น้ำ` returns four products

New tests: every import state transition; resuming mid-import without
duplicates; a failed import leaving the previous version serving; a rollback
that demonstrably swaps data; retention of exactly one previous version; a
rate limit shared across two limiter instances; single-use refresh rotation
against Postgres; and a check that the `anon` role cannot read any table.

CI runs pytest with `TEST_DATABASE_URL` from repository secrets.

## Cutover

1. Create the Supabase project in `sin1`, enable `pg_trgm`, run migrations.
2. Do all the work on a branch. `main` keeps serving the current system
   throughout, so there is no outage window.
3. Deploy to Vercel with the environment variables set.
4. Load the first workbook, through the CLI if it is large.
5. Verify the three ground-truth searches in a browser.
6. Only then delete `Dockerfile`, `.dockerignore`, `render.yaml`,
   `scripts/deploy_render.py`, `snapshot.enc`, `api/crypto.py` and
   `api/snapshot.py`, and drop the Hugging Face front matter from the README.
7. Retire the LAN instance once the Vercel URL is confirmed.

Reverting the cutover means checking out the previous commit; the current
system is untouched throughout.

## Risks and accepted trade-offs

**Personal data is no longer encrypted at rest by this application.** The old
design sealed the snapshot with AES-256-GCM. In the new design the data is
plaintext in Postgres, protected by Supabase's disk encryption and by the fact
that only the database password reaches the application. Restoring
application-level encryption would mean encrypting customer names, which breaks
the trigram indexes and therefore the search. Recorded, not done.

**Import time at the top of the range.** Two to three minutes for 100,000 rows.
Acceptable for a periodic import; the NDJSON staging optimisation is the
escape hatch.

**Cold starts.** Each new Vercel instance opens its own pooled connection. The
transaction pooler absorbs this; connection exhaustion is the failure mode to
watch for in the first week.

**Latency.** About 300 ms per search, versus an in-memory SQLite lookup. The
interface shows a spinner already.

**Three round trips per search.** Mergeable into one CTE if measurement
demands it.

**Serverless shutdown.** Audit rows may be lost if an invocation is killed
mid-request. Searches are unaffected.
