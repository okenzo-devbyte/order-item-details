# Order Groups Web — Supabase + Vercel HTML app

Date: 2026-09-28
Status: approved

## Context

พนักงานต้องการค้นหาบนมือถือว่า "ลูกค้าคนนี้เคยซื้อกลุ่มสินค้าอะไรบ้าง" และ
"สินค้านี้ใครเคยซื้อ" จากไฟล์งาน `simpledata_1000rows.xlsx` (1,000 แถว,
12 คอลัมน์, ภาษาไทย) ระบบเดิมใน git history เป็น FastAPI + PWA + Postgres
ที่รันได้เฉพาะบนเครื่อง developer และเปลี่ยนข้อมูลยาก (ต้อง rebuild ทุกครั้ง)

โปรเจกต์นี้สร้างใหม่เป็น HTML web app ที่คุยกับ Supabase ผ่าน API กลาง
เพื่อให้เปลี่ยนฐานข้อมูลในอนาคตได้โดยไม่แตะโค้ดส่วน UI

## Goals

- ค้นหาได้สองทิศทาง: ชื่อลูกค้า → กลุ่มสินค้าที่เคยซื้อ, ชื่อสินค้า → ลูกค้าที่เคยซื้อ
  พร้อมตัวกรอง Dept/Class/Subclass และหน้ารายละเอียดระดับออเดอร์
- Login ด้วยบทบาท 2 แบบ: `admin` (import/delete ได้) และ `viewer` (อ่านอย่างเดียว)
- Admin อัปโหลด xlsx ใหม่แล้วข้อมูลค้นได้ภายในไม่กี่วินาที (replace หรือ append)
- ทุกการเข้าถึงข้อมูลผ่าน API กลาง — UI ไม่รู้จัก Supabase เลย
- Deploy บน Vercel (Serverless Functions + static HTML) ไม่ต้องดูแล server
- UI ภาษาไทย mobile-first, สวยงาม, ใช้งานลื่นไหล

## Non-goals

- ไม่ทำ PWA/offline, ไม่ทำ user management หน้าเว็บ (สร้าง user ผ่านสคริปต์),
  ไม่ทำลบออเดอร์ทีละรายการ (มีแค่ลบทั้งหมด)
- ไม่เปลี่ยนรูปแบบข้อมูลใน xlsx และไม่รองรับหลายภาษา
- ไม่ทำ rate limit ขั้นสูง/audit log ละเอียด (มีแค่ประวัติ import + limiter ตอน login)

## Architecture

```
[เบราว์เซอร์: HTML/CSS/JS ล้วน ไม่มี build step]
        │  fetch('/api/...')
        ▼
[Vercel Function — Node]
  api/auth/*   api/search   api/search/orders   api/filters
  api/customer api/product  api/stats           api/admin/import   api/admin/clear
        │
        ▼
  api/lib/repository.js    ◄── interface เดียวสำหรับทุก route
        │
        ▼
  api/lib/adapters/supabase.js  ◄── ไฟล์เดียวที่รู้จัก Supabase
        │
        ▼
  [Supabase Postgres — schema `order_item`]
```

กฎ:

- ไม่มีคำว่า `supabase` อยู่นอก `api/lib/adapters/` — เปลี่ยน DB อนาคต =
  เขียน adapter ใหม่ 1 ไฟล์ แล้วผ่าน contract test เดิม
- Config อ่านจาก env ในที่เดียว (`api/lib/config.js`):
  `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SESSION_SECRET`
- ทุก response เป็น `{ ok: true, data }` หรือ
  `{ ok: false, error: { code, message } }` (message ภาษาไทย)
- Frontend มี wrapper `api()` ตัวเดียวสำหรับเรียกทุก endpoint

## Database schema (Postgres schema `order_item`)

แยก namespace เพราะ DB ใบนี้มีหลายโปรเจกต์ ทุกตารางอยู่ใน `order_item.`

```sql
create schema if not exists order_item;

create table order_item.order_items (
  id            bigserial primary key,
  order_number  text not null,
  store_code    text,
  item_id       text not null,
  product_name  text not null,
  product_norm  text not null,          -- lower + ลบช่องว่าง (ค้นไทยเรื่อง spacing)
  customer_name text not null,
  customer_norm text not null,
  expected_from date,
  expected_to   date,
  expected_raw  text,                   -- สตริงต้นฉบับ "28-Sep-2026 - 28-Sep-2026"
  dept          integer,
  class         integer,
  subclass      integer,
  item_remark          text,
  vip_customer_remarks text,
  vip_customer_groups  text
);
create index order_items_customer_norm_idx  on order_item.order_items (customer_norm);
create index order_items_product_norm_idx   on order_item.order_items (product_norm);
create index order_items_group_idx          on order_item.order_items (dept, class, subclass);
create index order_items_order_number_idx   on order_item.order_items (order_number);

create table order_item.users (
  id            uuid primary key default gen_random_uuid(),
  username      text unique not null,
  password_hash text not null,          -- scrypt: scrypt$N$salt$hash
  role          text not null check (role in ('admin','viewer')),
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table order_item.sessions (
  token_hash text primary key,          -- SHA-256 ของ token ไม่ใช่ token เปล่า
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
```

เหตุผล: ข้อมูล 1,000 แถว ไม่แยก customers/products เป็นตาราง (denormalized)
เพื่อให้ import ง่ายและ query เดียวจบ; `*_norm` แก้ปัญหาช่องว่างภาษาไทย;
ถ้าข้อมูลโตค่อยเพิ่ม index โดยไม่เปลี่ยนรูปแบบ API

## API endpoints

ทุกเส้นทางใต้ `/api/*` ห้ามมี supabase client ในเบราว์เซอร์

### Auth
| เมธอด | เส้นทาง | คำอธิบาย |
|---|---|---|
| POST | `/api/auth/login` | `{username,password}` → ตั้ง cookie `sid` HttpOnly SameSite=Lax Secure, คืน `{user:{id,username,role}}` |
| POST | `/api/auth/logout` | ลบ session + ลบ cookie |
| GET  | `/api/auth/me` | คืน user ปัจจุบัน, 401 ถ้าไม่ได้ login |

### อ่านข้อมูล (admin + viewer)
| เมธอด | เส้นทาง | คำอธิบาย |
|---|---|---|
| GET | `/api/search?direction=customer\|product&q=&dept=&class=&subclass=&page=&page_size=` | ผลแบบ grouped: customer = ต่อลูกค้า สรุปจำนวนออเดอร์/กลุ่มสินค้า/VIP; product = ต่อสินค้า สรุปจำนวนลูกค้า/จำนวนครั้ง |
| GET | `/api/search/orders?` (พารามิเตอร์เดียวกัน) | ผลระดับแถวออเดอร์ สำหรับตาราง detail/dashboard |
| GET | `/api/customer?name=` | โปรไฟล์ลูกค้า + กลุ่มสินค้าที่เคยซื้อ (aggregated) + สถิติ |
| GET | `/api/product?item_id=` | สินค้า + รายชื่อลูกค้าที่เคยซื้อ |
| GET | `/api/filters?dept=&class=` | ตัวกรอง cascade (Dept → Class → Subclass) |
| GET | `/api/stats` | ตัวเลขสรุปสำหรับ dashboard |

### Admin เท่านั้น (viewer → 403)
| เมธอด | เส้นทาง | คำอธิบาย |
|---|---|---|
| POST | `/api/admin/import` | multipart `file` + `mode=replace\|append` → parse server-side (exceljs) → validate → transaction → `{filename,row_count,mode,warnings}` |
| GET | `/api/admin/imports` | ประวัติ import ล่าสุด 50 รายการ |
| POST | `/api/admin/clear` | ต้องส่ง `{confirm:true}` ไม่งั้น 400 |

Validation ตอน import: หัวคอลัมน์ครบ, วันที่แปลงได้ (รูปแบบ
`dd-Mon-yyyy - dd-Mon-yyyy`), ห้าม (`order_number`,`item_id`) ซ้ำในไฟล์เดียวกัน,
`q` ยาวสุด 100 ตัวอักษร, `dept/class/subclass` ต้องเป็นตัวเลข
ไฟล์ไม่ผ่าน = transaction ย้อนกลับทั้งหมด ไม่แตะข้อมูลเดิม แล้วรายงานแถวที่มีปัญหา

## Frontend

หน้าทั้งหมด: `index.html` (ค้น+รายละเอียด), `login.html`, `admin.html`
แชร์ `public/styles.css` + `public/js/*.js` (ES modules, no build step, no framework)

### index.html — search-first + detail ในหน้าเดียว (History API ไม่ reload)
- Hero: ช่องค้นใหญ่ + สลับ `ค้นด้วยชื่อลูกค้า | ค้นด้วยชื่อสินค้า`,
  debounce 300ms, skeleton shimmer ระหว่างโหลด
- แถบ filter chip Dept → Class → Subclass (cascade) + ปุ่มล้าง
- ผล grouped เป็นการ์ด: ลูกค้า = ชื่อ, จำนวนออเดอร์, badge กลุ่มสินค้า,
  ดาว VIP; สินค้า = ชื่อ, จำนวนลูกค้า, จำนวนครั้ง + pagination (50 แถว/หน้า)
- คลิกการ์ด → detail เลื่อนเข้า: stat chips + ตารางออเดอร์เรียง/กรองได้
  + ปุ่มกลับ (browser back ทำงาน)
- URL เก็บสถานะ `?q=&dir=&dept=&class=&subclass=&page=` → share/refresh ได้
- empty state ภาษาไทย, toast แจ้งเตือน

### login.html
การ์ดกึ่งกลาง ช่องผู้ใช้/รหัสผ่าน ข้อความผิดชัดเจน ถ้ามี `?next=` กลับไปหลัง login

### admin.html (เฉพาะ admin; viewer เปิด → 403 → เด้งออก)
- การ์ดนำเข้า: เลือกไฟล์ → preview (ชื่อ, จำนวนแถว, อ่านหัวคอลัมน์)
  → เลือก `แทนที่ทั้งหมด | เพิ่มต่อท้าย` → ปุ่มนำเข้า + progress → สรุปผล/แถบที่มีปัญหา
- ตารางประวัติการนำเข้า
- เขตอันตราย: ลบทั้งหมด → ต้องพิมพ์ `ลบทั้งหมด` ยืนยัน

### ดีไซน์
ธีม indigo/violet บนพื้นขาว/เทาอ่อน, dark mode อัตโนมัติจาก system
(CSS variables), ฟอนต์ Noto Sans Thai, การ์ดมุมมน โปร่ง, transition 200ms,
รองรับคีย์บอร์ด (focus visible), mobile-first

## Auth & security

- `password_hash` = scrypt (Node `crypto` ไม่พึ่ง lib) รูปแบบ `scrypt$N$salt$hash`
- Login สำเร็จ → token สุ่ม 32 byte → เก็บ SHA-256 hash ใน `sessions`
  อายุ 7 วัน เลื่อนอายุเมื่อใช้งาน → cookie `sid` HttpOnly SameSite=Lax Secure
- ทุก request ป้องกัน: cookie → hash → session → user → ตรวจ `active` + `role`
- `requireAuth` ทุก endpoint ยกเว้น login; `requireRole('admin')` กับ `/api/admin/*`
  หลักคือ API ปฏิเสธเสมอ UI ซ่อนปุ่มเป็นเรื่องรอง
- service role key อยู่ใน env ของ Vercel เท่านั้น เปิด RLS บนตารางโดยไม่มี policy
- CSRF: SameSite=Lax + ทุก mutation เป็น POST `application/json`/multipart
- Brute-force: in-memory limiter 10 ครั้ง / 5 นาที / IP ที่ login
- สร้าง user ผ่าน `scripts/create-user.js` (รันที่เครื่อง) ไม่มี default password ในโค้ด

## Error handling

Error code → HTTP status: `validation_error` 400, `unauthorized` 401,
`forbidden` 403, `not_found` 404, `bad_file` 422, `too_large` 413,
`rate_limited` 429, `internal` 500
500 = ข้อความไทยทั่วไป + log server เท่านั้น ไม่ leak stack/SQL
Frontend: wrapper `api()` ตัวเดียว — 401 → `login.html?next=...`, 403 → toast,
429 → "ลองใหม่ในอีกสักครู่", network ล่ม → การ์ด "เชื่อมต่อไม่ได้ [ลองใหม่]",
ผลว่าง → empty state, ทุก async มี loading + ปุ่ม disable กันกดซ้ำ

## Testing

`node --test` (ศูนย์ dependency)

- Unit: scrypt hash/verify, session issue/validate/หมดอายุ, normalizer
  (`เด็ก สมบูรณ์` == `เด็กสมบูรณ์`), validate พารามิเตอร์, xlsx→rows transform
  (fixture เล็ก ๆ)
- **Contract test**: repository รันกับ fake in-memory adapter → พิสูจน์ว่า
  adapter ใหม่ในอนาคตเข้าแทนได้จริง (หัวใจของ "api กลาง")
- Adapter test (Supabase): รันเฉพาะเมื่อมี env จริง (skip ถ้าไม่มี)
- Smoke E2E ด้วยมือ: login admin → import `simpledata_1000rows.xlsx` (replace)
  → ค้นสองทิศทาง → viewer เปิด `/admin` ไม่ได้ → clear data
- ก่อนจบงาน: รัน test ทั้งหมด + checklist smoke
