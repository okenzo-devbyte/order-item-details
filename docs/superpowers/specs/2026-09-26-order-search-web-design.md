# ระบบค้นหาประวัติการซื้อสินค้าของลูกค้า — Web Service + PWA (Plan 2) — Design Spec

- **วันที่:** 2026-09-26
- **สถานะ:** อนุมัติแนวทางแล้ว (คุยกับผู้ใช้ครบทุก decision)
- **ต่อจาก:** `2026-09-26-order-search-design.md` (Plan 1 — core engine) และ `2026-09-26-order-search-core.md` (12 tasks, 275 tests)
- **ขอบเขต:** เอา core engine ที่ทดสอบแล้วขึ้นเป็นเว็บ service ที่ login ได้ ใช้บนมือถือได้ และ deploy ฟรีบน Render

---

## 0. บริบทและข้อค้นพบใหม่ที่กำหนดดีไซน์

Plan 1 จบแล้ว: `import_excel.py` → `snapshot.db` → `query_cli.py` ทำงานในเครื่อง ไม่มี network surface

Plan 2 เพิ่ม: FastAPI + auth + audit + snapshot encryption + PWA + Dockerfile

### 0.1 ข้อค้นพบที่วัดจริงบนเครื่องนี้ (Python 3.14.7 / SQLite 3.50.4)

| การทดสอบ | ผล | ผลต่อดีไซน์ |
|----------|-----|-------------|
| `sqlite3.Connection.serialize()` / `.deserialize()` | มีให้ใช้ (Python ≥ 3.11) | ใช้โหลด snapshot เข้า memory ได้ |
| `deserialize()` แล้ว FTS5 `MATCH` | **คืน 0 ทุกคำ** — inverted index ไม่ถูกกู้คืน (แถวข้อมูลยังอยู่ครบ) | **ห้ามเชื่อ deserialize เฉย ๆ** |
| หลัง deserialize แล้ว `INSERT INTO products_fts(products_fts) VALUES('rebuild')` | **คืนผลครบ** (`สิงห์`=1, `600มล`=1, `น้ำ`=1) | ต้อง rebuild FTS ทุกครั้งหลัง deserialize |
| `PRAGMA query_only=ON` | บล็อก write (`OperationalError`) · read และ FTS ปกติ | ใช้ล็อก snapshot เป็น read-only |
| `products_fts` เป็น standalone FTS5 (ไม่ใช่ external-content) | `rebuild` ทำงานได้ | ดู `schema.sql:26-36` |

> **นัยสำคัญ:** `deserialize()` เพียงลำพังทำให้ search คืน 0 แบบเงียบ ๆ โดยไม่มี error — เป็นบั๊กที่หาไม่เจอถ้าไม่ทดสอบ golden query หลังโหลด snapshot จึงต้องมีเทสต์บังคับในหัวข้อ 9

---

## 1. ขอบเขต

### ต้องทำ (In scope)
- FastAPI service เสิร์ฟ API + PWA จาก container เดียว
- Login (argon2id + JWT cookie) + RBAC `staff`/`admin`
- Snapshot เข้ารหัส AES-256-GCM ถอดเข้า memory เท่านั้น
- Audit log ทุกการค้นหา
- Admin อัปโหลด xlsx ผ่าน UI เพื่อ rebuild snapshot (versioned + rollback)
- PWA mobile-first (Vanilla JS, no-build) ติดตั้งได้
- Dockerfile + render.yaml deploy Render
- Endpoint: search, suggest, filters, customer/product detail, admin users/audit/import

### ไม่ทำ (Out of scope — รอบนี้)
- TOTP 2FA (โครงสร้าง `users.totp_secret` เตรียมไว้ แต่ยังไม่เปิดใช้)
- ลูกค้าใช้งานเอง / OTP / สมัครสมาชิก
- เขียนข้อมูลลูกค้า (ระบบ read-only ต่อ snapshot)
- CSV/Excel export (ปิด)
- รายงาน/analytics/dashboard
- Postgres migration (interface `search/engine.py` คงเดิม เผื่อไว้)

---

## 2. การตัดสินใจที่ผู้ใช้อนุมัติแล้ว

| # | หัวข้อ | ตัดสิน | ทางเลือกที่ตัดออก |
|---|--------|--------|-------------------|
| 1 | ขอบเขต Plan 2 | **ครบทั้งชุด** API + auth + PWA + deploy | แยกทำทีละส่วน |
| 2 | Deploy target | **Render** (free web service) | Fly.io / LAN / ยังไม่ deploy |
| 3 | Auth | **argon2id + JWT cookie + RBAC** | เพิ่ม TOTP ตั้งแต่รอบนี้ / แบบง่ายสุด |
| 4 | Import ข้อมูลใหม่ | **admin อัปโหลด xlsx ผ่าน UI** | CLI อย่างเดียว / ทั้งสองแบบ |
| 5 | PWA stack | **Vanilla JS, no-build** | React + Vite / React แยก repo |
| 6 | Snapshot versioning | **เก็บเวอร์ชันเก่า + rollback** | ทับไฟล์เดิม / เก็บทุกเวอร์ชัน |
| 7 | Persistence บน Render free | **รองรับทั้งมี disk และไม่มี** | ยอมให้ audit หาย / paid disk / export manual |
| 8 | ข้อมูลตั้งต้น | **Bake `snapshot.enc` ตอน build เข้า image** | build ตอน startup / อัปโหลดครั้งแรก manual |
| 9 | Layout ผลลัพธ์มือถือ | **แบบ B — รายการกระชับ** | การ์ดใหญ่ / แท็บแยกโหมด |

### 2.1 ประเด็นที่เบี่ยงจาก spec เดิม (อนุมัติแล้ว)
1. **ตัด TOTP** ออกจากรอบนี้ — เก็บคอลัมน์ `totp_secret` ไว้แต่ไม่บังคับ
2. **ใช้ PyJWT** แทน `python-jose` — ยัง maintain อยู่และ dependency เบากว่า
3. **ใช้ Vanilla JS** แทน React+Vite — ลด build stage, single container ง่าย
4. **เพิ่ม FTS rebuild หลัง deserialize** — ข้อค้นพบใหม่ จำเป็นต่อความถูกต้อง

---

## 3. สถาปัตยกรรม

### 3.1 ภาพรวม

```
มือถือ (PWA) ──HTTPS──▶ FastAPI (container เดียว)
                            │
                            ├─▶ ตรวจ session cookie (JWT) + role + CSRF + rate limit
                            ├─▶ อ่าน snapshot ที่ถอดรหัสค้างใน memory แล้ว (read-only)
                            ├─▶ SearchEngine (core เดิมจาก Plan 1) ค้นหา/จัดอันดับ
                            ├─▶ เขียน audit_log ลง app.db
                            └─▶ JSON + Cache-Control: no-store
```

- **Snapshot path:** `SNAPSHOT_PATH` (ค่าเริ่มต้น `/app/data/snapshot.enc`) — bake เข้า image ตอน build
- **App DB path:** `DISK_PATH/app.db` ถ้ามี `DISK_PATH`, ไม่งั้นใช้ `${TMPDIR}/order-search/app.db` (ephemeral)
- ทั้งหมดอยู่ใน container เดียว; ไม่มี CORS; ไม่มี external service

### 3.2 โครงสร้างโปรเจกต์ (เพิ่มจาก Plan 1)

```
api/
  __init__.py
  main.py                 FastAPI app, lifespan, static mount, security headers
  config.py               Settings จาก env (pydantic-settings)
  crypto.py               AES-256-GCM envelope (encrypt/decrypt snapshot)
  security.py             argon2id, JWT issue/verify, cookie deps, RBAC, CSRF
  audit.py                append-only audit writer
  ratelimit.py            in-process fixed-window counter
  snapshot.py             SnapshotStore: decrypt→deserialize→rebuild FTS→query_only, swap, rollback
  schemas.py              pydantic request/response models
  db/
    app_schema.sql        users, refresh_tokens, import_versions, audit_log
    app_db.py             read-write connection factory + migrate
    users.py              user CRUD + bootstrap admin
  routers/
    auth.py  search.py  admin.py  filters.py
web/
  index.html  app.js  styles.css  manifest.webmanifest  sw.js
  icons/icon-192.png  icons/icon-512.png
scripts/
  build_snapshot.py       xlsx → snapshot.db → snapshot.enc
  make_admin.py           CLI เพิ่ม/รีเซ็ต admin ใน app.db
Dockerfile
render.yaml
tests/
  test_crypto.py  test_snapshot_store.py  test_security.py
  test_api_auth.py  test_api_search.py  test_api_admin.py
  test_ratelimit.py  test_audit.py  test_pwa.py
  conftest.py             app factory + temp app.db + fixture snapshot
```

> `src/order_search/**` (core เดิม) **ไม่แก้** ยกเว้นเพิ่ม `SnapshotStore` ใน `api/snapshot.py` ที่เรียก `SearchEngine` เดิม

### 3.3 SnapshotStore — หัวใจของ Plan 2

`SnapshotStore` (ใน `api/snapshot.py`) รับผิดชอบวัฏจักรชีวิตของ snapshot:

```
load(path, data_key):
    enc   = read_file(path)                       # ciphertext
    plain = aes_gcm_decrypt(enc, data_key)        # bytes ใน memory
    conn  = sqlite3.connect(":memory:")
    conn.deserialize(plain)                       # โหลดหน้า DB
    conn.execute("INSERT INTO products_fts(products_fts) VALUES('rebuild')")  # ★ จำเป็น
    conn.execute("PRAGMA query_only=ON")          # ล็อก read-only
    conn.row_factory = sqlite3.Row
    return conn

serve():
    with lock:            # shared connection + threading.Lock
        return SearchEngine(conn)
```

- **ห้ามเขียน plaintext ลงดิสก์** ทุกกรณี — ใช้ `deserialize` เข้า memory เท่านั้น
- `rebuild` ต้องรัน **ก่อน** `query_only=ON` (query_only บล็อก write)
- shared connection ตัวเดียว + `threading.Lock` เพราะ FastAPI รัน sync endpoint ใน threadpool; ระบบ read-only อัตราใช้งานต่ำ จึงเพียงพอ (ไม่ต้อง pool)
- ขนาด 76 KB → rebuild บน 15 สินค้าแทบไม่มีต้นทุน; ที่ 100,000 แถวก็ทำครั้งเดียวตอน boot

### 3.4 การสลับ snapshot แบบ atomic (admin import)

```
import_version(new_xlsx):
    1. validate + build → sqlite bytes (ใช้ ingest/build.py เดิม) → เข้ารหัส → bytes ใหม่
    2. เขียน bytes ใหม่ → <data_dir>/versions/<utc_ts>.enc.tmp
    3. os.replace(tmp, versions/<utc_ts>.enc)          # atomic บน filesystem เดียวกัน
    4. สร้าง connection ใหม่จาก bytes ใหม่ (deserialize + rebuild + query_only)
    5. สลับ store.conn = connection ใหม่  (ใต้ lock)
    6. บันทึก import_versions + audit
    ถ้าขั้นใดพัง → ลบ tmp, คง connection เดิม (ไม่กระทบผู้ใช้ที่กำลังค้นหา)

rollback(version_id):
    โหลด versions/<id>.enc → ตรวจ integrity → สร้าง connection ใหม่ → สลับ + audit
```

- ไม่มี `DISK_PATH` → เขียนลง `${TMPDIR}/order-search/versions/` (หายเมื่อ restart); API ตอบ flag `persistent: false` ให้ UI เตือน
- `SNAPSHOT_PATH` เดิม (baked) ใช้เป็น "version 0" สำหรับ rollback กลับค่าเริ่มต้น

---

## 4. Data Model

### 4.1 `snapshot.db` (Plan 1 — ไม่เปลี่ยน)
`products`, `products_fts`, `product_barcodes`, `customers`, `orders`, `order_items` ตาม `src/order_search/ingest/schema.sql`

### 4.2 `app.db` (ใหม่ — เขียนได้, แยกจาก snapshot)

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,          -- argon2id
    role          TEXT    NOT NULL CHECK (role IN ('staff','admin')),
    totp_secret   TEXT,                      -- เตรียมไว้ ยังไม่ใช้รอบนี้
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);
CREATE UNIQUE INDEX idx_users_username ON users(username);

CREATE TABLE refresh_tokens (
    id          TEXT PRIMARY KEY,            -- jti (uuid4)
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    issued_at   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_refresh_user ON refresh_tokens(user_id);

CREATE TABLE import_versions (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL,               -- ของ ciphertext
    row_count   INTEGER,
    product_count INTEGER,
    customer_count INTEGER,
    is_current  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    created_by  INTEGER REFERENCES users(id)
);

CREATE TABLE audit_log (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER REFERENCES users(id),
    action       TEXT NOT NULL,              -- search | suggest | login | logout | import | rollback | ...
    query        TEXT,                       -- เฉพาะ action ที่มีคำค้น
    mode         TEXT,
    result_count INTEGER,
    ip           TEXT,
    user_agent   TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_audit_created ON audit_log(created_at);
```

- `audit_log` เป็น append-only — ไม่มี UPDATE/DELETE ในโค้ด
- ไม่มี FK บังคับจาก `audit_log` ไป `users` แบบ RESTRICT เพื่อให้ลบ user ได้โดยไม่ทำลายประวัติ (เก็บ `user_id` ไว้เป็นหลักฐาน)
- วันที่เก็บเป็น ISO `YYYY-MM-DDTHH:MM:SSZ` (UTC)

### 4.3 Session model

| องค์ประกอบ | ค่า |
|-----------|-----|
| Access token | JWT HS256, อายุ 15 นาที, claims: `sub`(user_id), `role`, `exp`, `iat`, `type=access` |
| Refresh token | JWT HS256, อายุ 7 วัน, claim `jti` → ต้องมีแถวใน `refresh_tokens` ที่ `revoked=0` |
| Cookie | `access_token`, `refresh_token` — `HttpOnly; Secure(ตาม COOKIE_SECURE); SameSite=Strict; Path=/` |
| Idle timeout 30 นาที | ตรวจตอน refresh: ถ้า `now - last_used_at > 30 นาที` → ปฏิเสธ; ไม่งั้นอัปเดต `last_used_at` |
| Rotation | ทุกครั้งที่ refresh → revoke jti เก่า + ออก jti ใหม่ (กัน replay) |
| Logout | revoke refresh jti ทันที + ล้าง cookie |
| Password change | revoke refresh token ทั้งหมดของ user |

---

## 5. API Surface

```
POST   /api/v1/auth/login     {username, password} → set cookies, {user}
POST   /api/v1/auth/logout    → revoke + clear cookies
POST   /api/v1/auth/refresh   → rotate cookies
GET    /api/v1/auth/me        → {id, username, role}

POST   /api/v1/search         {q, mode?, filters?, limit?, cursor?}   ← PII ใน body
POST   /api/v1/suggest        {q, limit?}                             ← PII ใน body
GET    /api/v1/filters                                                 facet values
GET    /api/v1/customers/{id}/history
GET    /api/v1/products/{id}/customers

POST   /api/v1/admin/import              multipart xlsx → new version
GET    /api/v1/admin/import/versions     list + persistent flag
POST   /api/v1/admin/import/rollback     {version_id}
GET    /api/v1/admin/audit               ?limit&cursor&user_id&action
GET    /api/v1/admin/users
POST   /api/v1/admin/users               {username, password, role}
PATCH  /api/v1/admin/users/{id}          {password?, role?, is_active?}

GET    /healthz
```

- ทุก endpoint ใต้ `/api/v1` ยกเว้น login ต้องมี access token + role ที่ผ่าน
- `/api/v1/admin/*` ต้อง role `admin`
- search/suggest เป็น **POST** เพราะคำค้นเป็น PII — หลีกเลี่ยง URL/history/referrer/proxy log
- จำกัดความยาว `q` ≤ 200 อักขระ, `limit` ≤ 100 (engine มี clamp อยู่แล้ว — เสริมที่ pydantic)
- จำกัดขนาดไฟล์อัปโหลด ≤ 20 MB และนามสกุล `.xlsx`

### 5.1 Error convention
`401` ยังไม่ login / token หมดอายุ · `403` role ไม่พอ · `413` ไฟล์ใหญ่เกิน · `422` payload ผิด · `429` rate limit · `500` มี request id แต่ไม่หลุด stack trace

---

## 6. Security

| ชั้น | การทำ |
|------|-------|
| Authentication | argon2id (`argon2-cffi` ค่าปริยาย) · access 15 นาที + refresh 7 วัน · revocable |
| Session | idle 30 นาที ตรวจ server-side · refresh rotation + revoke on logout · password change revoke ทั้งหมด |
| RBAC | dependency `require_staff` / `require_admin` |
| CSRF | `SameSite=Strict` + ตรวจ `Origin` ทุก non-GET + double-submit token (`csrf_token` cookie อ่านได้ + header `X-CSRF-Token`) สำหรับ admin mutation |
| PII | search/suggest POST body · ไม่ log คำค้นใน access log · audit log เก็บคำค้นได้ (ต้องมี เพื่อตรวจสอบ) แต่ไม่ echo ใน error |
| Audit | append-only · เฉพาะ admin อ่าน · บันทึก login สำเร็จ/ล้มเหลว, search, suggest, import, rollback, user management |
| Rate limit | fixed-window 60 req/นาที/ผู้ใช้ (ใช้ user_id; ก่อน login ใช้ IP) · เกิน → 429 |
| Cache | middleware ใส่ `Cache-Control: no-store` ให้ทุก response ใต้ `/api/v1` |
| Headers | HSTS (เมื่อ COOKIE_SECURE), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, CSP ที่อนุญาตเฉพาะ self |
| At rest | `snapshot.enc` = AES-256-GCM · `DATA_KEY` base64 32 byte จาก env · envelope มี `key_id` + nonce ต่อไฟล์ รองรับ rotation |
| Transport | HTTPS (Render จัดให้) · บังคับ Secure cookie ใน prod |
| Input | SQL parameterized ทั้งหมด (core ทำอยู่แล้ว) · pydantic validate · จำกัดขนาด/ชนิดไฟล์อัป |
| Secrets | จาก env เท่านั้น · ไม่ commit `.env` · `snapshot.enc` เป็น ciphertext จึง commit ได้ แต่ xlsx ต้นทางห้าม commit |
| PWA | service worker cache เฉพาะ app shell · `/api/*` network-only |
| Bootstrap admin | จาก `ADMIN_USERNAME`/`ADMIN_PASSWORD` ตอน boot เฉพาะเมื่อไม่มี admin ใน `app.db`; บังคับเปลี่ยนรหัสผ่านถ้ายังเป็นค่าเริ่มต้น (ตั้ง `must_change_password` ในอนาคต — รอบนี้แค่ log เตือน) |

---

## 7. Frontend (PWA)

### 7.1 จอ
1. **Login** — username/password, error inline, ปุ่มใหญ่, autofocus
2. **Search** — ช่องค้นหา 56px + ปุ่มล้าง · chip แสดง/สลับโหมด `ลูกค้า|สินค้า|อัตโนมัติ` · autocomplete dropdown จาก `/suggest` (debounce 250ms) · ผลลัพธ์ **รายการกระชับ** · ปุ่มตัวกรอง (bottom sheet) · ปุ่ม logout
3. **Detail** — customer → รายการสินค้าที่เคยซื้อ; product → รายชื่อลูกค้า
4. **Admin** (role admin) — import (เลือกไฟล์ + ความคืบหน้า), versions + rollback, audit, users

### 7.2 ผลลัพธ์แบบ B (รายการกระชับ)
```
สุรชัย · Gold · 65 ออเดอร์ · 15 สินค้า
น้ำดื่มสิงห์ x12 · 6× · 26 ก.ย. · 101
น้ำตาลทรายขาว · 4× · 26 ก.ย. · 107
...
```
- หนึ่งบรรทัดต่อรายการ แตะเพื่อดู detail
- หมายเหตุใต้ผลลัพธ์: "วันที่คือวันคาดส่ง ไม่ใช่วันสั่งซื้อ"

### 7.3 Service Worker
- `install`: cache app shell (`/`, `/app.js`, `/styles.css`, `/manifest.webmanifest`, icons)
- `fetch`: ถ้า path ขึ้นต้น `/api/` → `fetch(event.request)` ตรง ๆ (network-only, ไม่แตะ cache) · ถ้าเป็น navigation → network-first fallback cache · asset อื่น → cache-first
- `sw.js` เองห้าม cache
- อัปเดตเวอร์ชัน cache เมื่อ deploy (ใช้ hash/version string)

### 7.4 Vanilla JS module structure (`app.js`)
```
state = { user, mode, query, filters, cursor }
api(path, opts)        // fetch + CSRF header + 401 → redirect login
renderLogin(), renderSearch(), renderResults(), renderDetail(), renderAdmin()
no framework: template strings + event delegation
```

---

## 8. Build & Deploy

### 8.1 `scripts/build_snapshot.py`
```
import_excel() → build_database() → sqlite bytes → AES-256-GCM encrypt(DATA_KEY, key_id) → snapshot.enc
```
- รันในเครื่อง dev; commit เฉพาะ `snapshot.enc` (ciphertext) · ห้าม commit `.xlsx`
- `DATA_KEY` เดียวกันต้องตั้งใน Render env ตอน deploy
- พิมพ์สรุป: products/customers/barcodes/rows + key_id

### 8.2 Dockerfile (multi-stage ไม่ต้องมี node)
```
FROM python:3.12-slim            # CPython มี FTS5 compiled-in (ยืนยันใน image)
WORKDIR /app
COPY requirements.txt .; RUN pip install --no-cache-dir -r requirements.txt
COPY src/ src/ ; COPY api/ api/ ; COPY web/ web/ ; COPY scripts/ scripts/
COPY snapshot.enc data/snapshot.enc
ENV SNAPSHOT_PATH=/app/data/snapshot.enc
EXPOSE 8000
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
```
- **ต้องตรวจตอน boot ว่า FTS5 + trigram ใช้ได้** (failsafe: log + ปฏิเสธ start ถ้าไม่มี) เพราะ image ต่างจากเครื่อง dev ได้

### 8.3 `render.yaml`
- web service, Docker, plan free, `healthCheckPath: /healthz`
- env: `SECRET_KEY` (generate), `DATA_KEY`, `DATA_KEY_ID`, `ADMIN_USERNAME`, `ADMIN_PASSWORD` (sync: false = ตั้งใน dashboard), `COOKIE_SECURE=true`
- ไม่มี disk (free) → audit/users เป็น ephemeral; เอกสารระบุวิธีเพิ่ม disk ($7) ถ้าต้องการถาวร
- healthcheck ping ช่วยลด cold start (optional external cron)

---

## 9. แผนทดสอบ

### 9.1 Ground truth ที่ใช้ (จาก Plan 1)
`สุรชัย` = 65 order lines · 15 สินค้า · VIP 4 tier | บาร์โค้ด `8850250001234` → `น้ำดื่มสิงห์ 600 มล. x 12` | `น้ำ` = 4 สินค้า | 1,000 แถว · 15 สินค้า · 20 ลูกค้า · 127 บาร์โค้ด

| ระดับ | เนื้อหา |
|-------|--------|
| crypto | roundtrip encrypt/decrypt · tamper → fail · ผิด key → fail · nonce ต่างกันทุกครั้ง |
| snapshot | **deserialize แล้วค้นด้วย `สิงห์`/`น้ำ`/บาร์โค้ดได้ผลเท่ากับ Plan 1** (กันบั๊ก FTS หาย) · rebuild ถูกเรียก · `query_only=ON` บล็อก write · หลังสลับ version ค้นได้ข้อมูลใหม่ · rollback กลับได้ |
| security | argon2id verify · JWT หมดอายุ → 401 · role ผิด → 403 · refresh rotation ทำให้ jti เก่าใช้ไม่ได้ · idle 30 นาที · logout revoke · password change revoke ทั้งหมด · CSRF token ขาด → 403 |
| API auth | login สำเร็จ/ล้ม · 401 เมื่อไม่มี cookie · logout ล้าง cookie · `/admin` ด้วย `staff` → 403 |
| API search | golden ผ่าน HTTP: `สุรชัย`, บาร์โค้ด, `สิงห` (พิมพ์ผิด) · `no-store` ทุก response · **ไม่มี PII ใน URL** (assert request.url.path ไม่มีคำค้น) · limit clamp · cursor ไม่ตกหล่น/ไม่ซ้ำ |
| admin import | upload xlsx → version ใหม่ + ค้นเจอ · rollback ได้ · ไฟล์ผิดชนิด/ใหญ่ → 422/413 · ไม่มี disk → `persistent:false` |
| audit | ทุก action เขียนแถว · append-only (ไม่มีโค้ด update/delete) · staff อ่านไม่ได้ · admin อ่านได้ |
| ratelimit | เกิน 60/นาที → 429 · ผู้ใช้ต่างกันไม่รบกวนกัน |
| PWA | `/` เสิร์ฟ index · `sw.js` ไม่มี `/api/` ใน cache list · manifest valid · API ตอบ `no-store` |
| deploy | (manual) `docker build` สำเร็จ · container เริ่มและ `/healthz` = 200 · FTS5 ใช้ได้ใน image |

### 9.2 Test strategy
- ใช้ `TestClient` (httpx) กับ app factory ที่รับ settings override และชี้ไป temp `app.db` + fixture snapshot
- fixture snapshot สร้างจาก `tests/conftest.py` (reuse fixture ของ Plan 1) แล้วเข้ารหัสด้วย key ทดสอบ
- ไม่พึ่ง network จริง/TOTP
- ทุกเทสต์รันด้วย `pytest` เดิม (ขยาย testpaths)

---

## 10. ข้อจำกัดที่ทราบแล้ว (Plan 2)

1. **Render free ไม่มี persistent disk** — audit log/users หายเมื่อ restart; ต้องอัปเกรดหรือ export
2. **Single container + shared connection** — ไม่ scale แนวนอน; เหมาะกับผู้ใช้ภายในหลักสิบ
3. **ไม่มี TOTP** รอบนี้ — 2FA จะเพิ่มภายหลัง (คอลัมน์เตรียมไว้)
4. **Snapshot baked ตอน build** — ข้อมูลตั้งต้นแก้ได้ด้วย redeploy หรือ admin import (ถ้ามี disk จึงถาวร)
5. **Cold start** Render free (~50 วิ หลัง idle)
6. **ไม่มี Customer ID / วันสั่งซื้อ / จำนวน-ราคา** — ข้อจำกัดสืบทอดจาก Plan 1
7. **Vanilla JS** — ถ้า UI โตมากจะย้ายไป React ได้แต่ต้องเพิ่ม build stage

---

## 11. การตัดสินใจที่ผ่านแล้ว (สรุป)

| # | การตัดสิน | เหตุผล |
|---|----------|--------|
| 1 | ครบทั้งชุดใน Plan 2 | ผู้ใช้ต้องการใช้งานจริงบนมือถือ |
| 2 | Render | ตั้งง่าย มี Docker + free tier |
| 3 | argon2id + JWT (ไม่ทำ TOTP) | เพียงพอกับผู้ใช้ภายใน ลดความซับซ้อนรอบแรก |
| 4 | import ผ่าน UI | admin ใช้งานเองไม่ต้องแตะ terminal |
| 5 | Vanilla JS no-build | single container ง่าย deploy |
| 6 | versioned snapshot + rollback | กันข้อมูลพังจากการ import ผิด |
| 7 | รองรับทั้งมี/ไม่มี disk | โค้ดเดียวใช้ได้ทั้ง free และ paid |
| 8 | bake snapshot ตอน build | ข้อมูลอยู่รอด restart โดยไม่มี disk |
| 9 | layout B รายการกระชับ | เห็นผลเยอะ สแกนเร็ว บนมือถือ |
| 10 | deserialize + FTS rebuild | ข้อค้นพบใหม่ จำเป็นต่อความถูกต้อง |
| 11 | PyJWT แทน python-jose | maintain ดีกว่า เบากว่า |
| 12 | `app.db` แยกจาก snapshot | เขียนได้ + เปลี่ยน user ไม่ต้อง rebuild snapshot |
