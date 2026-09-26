# ระบบค้นหาประวัติการซื้อสินค้าของลูกค้า (Order Item Search) — Design Spec

- **วันที่:** 2026-09-26
- **สถานะ:** อนุมัติแนวทาง A แล้ว (FastAPI + encrypted SQLite + PWA)
- **ผู้ใช้งาน:** พนักงานภายใน (ขาย/สาขา/ฝ่ายบริการ) + Admin เท่านั้น — **ไม่มีลูกค้าใช้เอง**
- **ข้อกำหนดหลัก:** ข้อมูลลูกค้าเป็นข้อมูลอ่อนไหว (sensitive) · ต้องใช้งานออนไลน์ผ่านมือถือ · ค้นหาเร็วและง่าย

---

## 1. ขอบเขต (Scope)

### ต้องทำ (In scope)
- ค้นหาด้วยชื่อลูกค้า → ดูสินค้าที่เคยซื้อ
- ค้นหาด้วยชื่อสินค้า/คำใบ (ภาษาไทย) → ดูว่าลูกค้าคนได้ซื้อ
- ค้นหาด้วยบาร์โค้ดแบบ exact
- ค้นหาแบบ fuzzy (พิมพ์ผิดก็เจอ)
- ตัวกรองขั้นสูง: สาขา, Dept, Class, Subclass, Order Type, VIP tier, ช่วงวันที่
- Autocomplete
- ระบบ login พร้อม audit log
- PWA ใช้งานบนมือถือ

### ไม่ทำ (Out of scope)
- ลูกค้าใช้งานเอง / OTP / สมัครสมาชิก
- เขียนข้อมูล (CRUD) — ระบบเป็น **read-only** ต่อข้อมูลลูกค้า
- แก้ไข/เพิ่มลูกค้าใน UI — ทำผ่านการ import ไฟล์ Excel เท่านั้น
- รายงาน/analytics เชิงลึก, dashboard กราฟ
- CSV export (ปิดไว้เป็นค่าเริ่มต้น — ดูหัวข้อ 7)

---

## 2. ผลการวิเคราะห์ข้อมูลต้นทาง

ไฟล์: `sample_order_data_1000_records.xlsx` · ชีต `Order Data` (13 คอลัมน์, 1,000 แถว) · `Summary` เป็น metadata เท่านั้น

| # | คอลัมน์ | ชนิด | ค่าไม่ว่าง | ค่าเฉพาะ | หมายเหตุ |
|---|--------|------|-----------|----------|----------|
| 0 | Store Code | str | 1000 | 15 | 101–155 |
| 1 | Order Type | str | 1000 | 4 | Standard 257 / Scheduled 251 / Express 246 / Pickup 246 |
| 2 | Product Name | str | 1000 | 15 | ภาษาไทย ยาว 26–48 ตัวอักษร มี `x N` ต่อท้าย |
| 3 | NO. | int | 1000 | 1000 | ค่า 1–1000 เรียงลำดับ ไม่ซ้ำ |
| 4 | Dept | int | 1000 | 9 | 1,4,5,7,8,9,10,11,12 |
| 5 | Class | int | 1000 | 14 | เช่น 312, 703, 901 |
| 6 | Subclass | int | 1000 | 15 | |
| 7 | Bar_Code | str | 1000 | 139 | **multi-value** คั่นด้วย ` \|\| ` |
| 8 | Customer Name | str | 1000 | 20 | **ไม่มี Customer ID** |
| 9 | Item Remark | str | 614 | 6 | |
| 10 | VIP Customer Remarks | str | 56 | 3 | |
| 11 | VIP Customer Groups | str | 119 | 4 | VIP / Gold / Platinum / Wholesale VIP |
| 12 | Original Expected Date | str | 1000 | **1** | `"26-Sep-2026 - 26-Sep-2026"` ทุกแถวเหมือนกันหมด |

### ข้อค้นพบสำคัญที่กำหนดดีไซน์

1. **`NO.` ไม่ใช่เลขออเดอร์** — ค่า 1–1000 เรียงลำดับไม่ซ้ำ แปลว่าเป็นเลขลำดับแถว ไม่ใช่ตัวจัดกลุ่มออเดอร์ → แต่ละแถวคือ 1 ออเดอร์ในข้อมูลปัจจุบัน
2. **`Bar_Code` เป็น multi-value** — บางแถวเป็น `"8850206900121 || 7579044163235"` → ต้องแยกเป็นหลายแถวในตาราง `product_barcodes` ไม่งั้นค้น exact จะพลาด
3. **`VIP Customer Groups` / `VIP Customer Remarks` ไม่ใช่คุณสมบัติระดับลูกค้า** — ลูกค้า**ทั้ง 20 คน**มีหลาย tier ปนกันในออเดอร์ของตัวเอง (เช่น สุรชัย มี Gold, Platinum, VIP, Wholesale VIP พร้อมกัน) → **ห้ามย้ายไปเก็บที่ `customers`** ต้องคงระดับ order line
4. **`Dept`/`Class`/`Subclass` ของสินค้าสม่ำเสมอ** — ทั้ง 15 รายการไม่มีข้อขัดแย้ง → normalize เป็น product dimension ได้อย่างปลอดภัย
5. **`Original Expected Date` เป็นช่วง ไม่ใช่วันเดียว** — รูปแบบ `DD-Mon-YYYY - DD-Mon-YYYY` ต้องแยกเป็น `date_from` / `date_to`; ในไฟล์ตัวอย่างทุกแถวเหมื่อนกันหมด (26-Sep-2026) จึง **ยังทดสอบการกรองตามวันที่ไม่ได้จากข้อมูลตัวอย่าง** — ต้องสร้าง synthetic fixture เพิ่ม
6. **ชื่อสินค้าคือ "วันคาดส่ง" ไม่ใช่ "วันสั่งซื้อ"** → ไม่มีวันที่สั่งซื้อจริง การเรียง "ซื้อล่าสุด" จึงใช้ `date_to` เป็นตัวแทน ต้องระบุข้อจำกัดนี้ใน UI
7. **ไม่มี Customer ID** — ใช้ชื่อเป็น key ชั่วคราว → ชื่อซ้ำของคนละคนจะถูกรวมเป็นคนเดียว (ความเสี่ยงที่ต้องยอมรับและบันทึกไว้)

---

## 3. สถาปัตยกรรม

### 3.1 ตัวเลือกที่พิจารณา

| ตัวเลือก | ข้อดี | ข้อเสีย | ผลตัดสิน |
|---------|------|---------|---------|
| **A. FastAPI + encrypted SQLite + PWA** | คุมความปลอดภัยเอง 100%, ไม่ต้องเช่า DB, อยู่ใน free tier, ไม่ติด vendor, อัปเกรด Postgres ได้ | ต้องเขียน auth/audit เอง, cold start บน Render free | **เลือก** |
| B. Next.js + Supabase | พัฒนาเร็ว, auth/RLS ให้พร้อม | PII อยู่บน vendor, free tier Postgres หยุดอัตโนมัติ, RLS ตั้งผิด = เจาะได้, ผูกกับ vendor | ไม่เลือก |
| C. Static PWA + encrypted blob | ฟรี เรียบง่ายที่สุด | **ไฟล์ข้อมูลทั้งก้อนดาวน์โหลดได้ + key อยู่ใน memory browser** → ข้อมูลรั่ว | **ตัดออก** |

### 3.2 โครงสร้างโปรเจกต์

```
order-search/
├─ api/
│  ├─ main.py                     FastAPI app + mount static PWA
│  ├─ core/
│  │  ├─ config.py                อ่าน SECRET_KEY / DATA_KEY จาก env
│  │  ├─ crypto.py                AES-256-GCM encrypt/decrypt snapshot
│  │  ├─ security.py              argon2id, JWT, RBAC dependencies
│  │  └─ audit.py                 บันทึกการค้นหา
│  ├─ db/
│  │  ├─ schema.sql               DDL
│  │  ├─ connection.py            read-only connection factory
│  │  └─ users.py                 ตาราง user + CRUD (admin)
│  ├─ search/
│  │  ├─ engine.py                ตัวค้นหาหลัก (ไม่ผูกกับ FastAPI)
│  │  ├─ normalize.py             ตัดวรรณยุกต์/ช่องว่าง, parse "x N"
│  │  ├─ detect.py                intention detection
│  │  └─ rank.py                  จัดอันดับผลลัพธ์
│  ├─ ingest/
│  │  ├─ importer.py              Excel → normalize → SQLite
│  │  └─ validate.py              ตรวจความถูกต้องของข้อมูล
│  └─ routers/
│     ├─ auth.py  search.py  admin.py  filters.py
├─ web/                           React + Vite PWA (mobile-first)
├─ scripts/
│  ├─ import_excel.py             CLI: xlsx → SQLite
│  └─ build_snapshot.py           SQLite → snapshot.enc
├─ tests/
│  ├─ fixtures/                   synthetic data ( varied dates )
│  ├─ test_normalize.py
│  ├─ test_importer.py
│  ├─ test_search_golden.py
│  ├─ test_security.py
│  └─ test_perf.py
├─ Dockerfile
├─ requirements.txt
└─ docs/
```

### 3.3 Data flow ตอนรัน

```
มือถือ (PWA) ──HTTPS──▶ FastAPI
                            │
                            ├─▶ ตรวจ JWT + role
                            ├─▶ ถอด snapshot.enc → plaintext **ใน memory เท่านั้น**
                            ├─▶ เปิด SQLite read-only (query_only=ON, WAL=off)
                            ├─▶ ค้นหา → จัดอันดับ → ตัดผลลัพธ์ให้เหลือเฉพาะที่ขอ
                            ├─▶ เขียน audit_log
                            └─▶ ตอบ JSON + Cache-Control: no-store
```

- ไม่เขียน plaintext ลง disk เด็ดขาด
- ตั้ง `Cache-Control: no-store` ทุก response ที่มีข้อมูลลูกค้า
- ปิด CDN caching สำหรับ `/api/*`

### 3.4 การ Deploy (free tier)

- **Container เดียว** เสิร์ฟทั้ง API และ PWA static → 1 โดเมน, ไม่มี CORS, ไม่ต้องค่า 2 ฝั่ง
- Target: **Render** (free web service) หรือ **Fly.io**
- ขนาดข้อมูล 76 KB → SQLite ทั้งก้อนอยู่ใน RAM ได้สบาย (free tier 512 MB)
- ข้อจำกัดที่ต้องยอมรับ: cold start ~50 วินาทีหลัง idle (แก้ได้ด้วย health check ping)
- **Upgrade path:** เมื่อข้อมูลเกิน ~500,000 แถว → ย้าย search engine ไป Postgres + pg_trgm (interface ของ `search/engine.py` คงเดิม)

---

## 3.5 เครื่องมือและไลบรารี

ตรวจสอบสภาพแวดล้อมเครื่องนี้แล้ว: **Python 3.14.7** (SQLite 3.50.4 รองรับ FTS5), Node v26.8.1, git 2.54.0, **ไม่มี Docker** (Dockerfile เขียนไว้ให้ Render/Fly สร้างบน cloud เท่านั้น — dev local รัน Python ตรงๆ)

| ไลบรารี | สถานะบนเครื่องนี้ | หน้าที่ |
|--------|------------------|--------|
| `openpyxl` | ✅ มีแล้ว | อ่านไฟล์ Excel ตอน import |
| `cryptography` | ✅ มีแล้ว | AES-256-GCM เข้า/ถอด snapshot |
| `pytest` | ✅ มีแล้ว | unit + integration test |
| `fastapi` | ❌ ต้องติดตั้ง | web framework |
| `uvicorn` | ❌ ต้องติดตั้ง | ASGI server |
| `pydantic` | ❌ ต้องติดตั้ง | validate request/response |
| `argon2-cffi` | ❌ ต้องติดตั้ง | hash password |
| `python-jose` | ❌ ต้องติดตั้ง | encode/decode JWT |
| `rapidfuzz` | ❌ ต้องติดตั้ง | fuzzy match (ชั้น 2 และ 4) |
| `httpx` | ❌ ต้องติดตั้ง | test client |
| `pyotp` | ❌ ต้องติดตั้ง | TOTP 2FA (ถ้าเปิดใช้) |

หมายเหตุ: **FTS5 เป็นส่วนขยายที่ต้องคอมไพล์มากับ SQLite** — ตรวจแล้วว่า Python 3.14.7 บนเครื่องนี้มีให้ใช้ (`tokenize='trigram'` ทำงาน) แต่ต้องยืนยันอีกครั้งใน Docker image ที่ deploy

---

## 4. Data Model

### 4.1 ตาราง

| ตาราง | คอลัมน์ | หมายเหตุ |
|-------|---------|----------|
| `products` | `id, name, name_norm, name_fold_light, name_fold_heavy, dept, class, subclass, pack_size, unit` | 3 คอลัมน์ค้นหา · `pack_size` parse จาก `x N` · `unit` = NULL |
| `product_barcodes` | `product_id, barcode` | แยกจาก `\|\|` · index บน `barcode` |
| `customers` | `id, name, name_norm, name_fold_light, name_fold_heavy` | key = ชื่อ (ยังไม่มี Customer ID) |
| `orders` | `id, order_no, store_code, customer_id, order_type, date_from, date_to, item_remark, vip_remark, vip_group` | `date_from`/`date_to` แยกจาก string range · VIP คงระดับ order |
| `order_items` | `order_id, product_id, qty, price` | เผื่ออนาคต 1 ออเดอร์มีหลายสินค้า (`qty`/`price` = NULL ตอนนี้) |
| `users` | `id, username, password_hash, role, totp_secret, is_active, created_at` | `role` ∈ `staff`, `admin` |
| `audit_log` | `id, user_id, query, mode, result_count, ip, user_agent, created_at` | append-only |

- ตารางค้นหา: `products_fts` (FTS5 trigram บน `name_norm` + `name_fold_light`) และ `product_barcodes`, `customers(name_norm)` ต้องมี index

- ข้อมูล `products`/`customers`/`orders` อยู่ใน **snapshot** (อ่านอย่างเดียว)
- `users` และ `audit_log` อยู่ใน **ไฟล์ฐานข้อมูลอีกชุดหนึ่งที่เขียนได้** (`app.db`) — แยกจาก snapshot เพราะ (ก) ต้องเขียนได้ (ก) ต้องไม่ถูกเข้ารหัสรวมกับข้อมูลลูกค้าในไฟล์เดียว (ค) เปลี่ยนบัญชีผู้ใช้ไม่ต้อง rebuild snapshot
- ทั้งสองไฟล์อยู่ใน container เดียว; `app.db` ต้องถูก mount เป็น **persistent volume** เพื่อไม่ให้ audit log หายเมื่อ restart

### 4.1.1 ความหมายของตัวกรอง (Filter semantics)

กำหนดให้ชัดเจน เพราะข้อมูลเป็นช่วงและเป็นระดับ order line:

| ตัวกรอง | กติกา |
|---------|--------|
| `store_code`, `dept`, `class`, `subclass`, `order_type` | ตรงกับ order line นั้นตรงๆ (จับคู่หลายค่าได้ = OR ภายในกลุ่ม, AND ระหว่างกลุ่ม) |
| `vip_group` | กรอง **ระดับ order line** (`orders.vip_group`) — ไม่ใช่ระดับลูกค้า เพราะข้อมูลจริงไม่สอดคล้องในระดับลูกค้า |
| `date_from` / `date_to` | **ช่วงทับกัน**: order ผ่านเมื่อ `order.date_from <= filter.date_to` **และ** `order.date_to >= filter.date_from` · order ที่ `date_from IS NULL` จะ**ไม่ผ่าน**ตัวกรองวันที่ (แต่ยังเจอเมื่อไม่กรองวันที่) |
| `q` (คำค้น) | ต้องผ่านทุกชั้นของ search engine |

### 4.2 การ Normalize สำหรับค้นภาษาไทย

ภาษาไทยไม่มีช่องว่างระหว่างคำ จึงต้องมีชั้นข้อความหลายชั้น — และต้องแยก "ตัดวรรณยุกต์" ออกจาก "ตัดสระ" เพราะผลต่างกันจริง

```
ชื่อเดิม  : น้ำดื่มสิงห์ 600 มล. x 12
name_norm        : น้ำดื่มสิงห์600มลx12    ← NFD, เก็บ category L/N/M, ตัดช่องว่าง+อักขระพิเศษ
name_fold_light  : นำดืมสิงห600มลx12      ← ตัด tone marks (้ ่ ๊ ๋) + ์ + ํ  ← เก็บสระไว้
name_fold_heavy  : นาดมสงห600มลx12        ← NFKD แล้วตัด category Mn ทั้งหมด (รวมสระ)
pack_size        : 12                      ← parse จากท้ายชื่อ "x N"
```

> **ทั้งสามชั้นต้องผ่านการตัดช่องว่างและอักขระพิเศษเหมือนกัน** (กรองเฉพาะ category L/N/M) มิฉะนั้นคำค้นที่ผ่าน `norm` มาแล้วจะไม่มีทางเทียบเท่าค่าที่เก็บไว้ในคอลัมน์ fold ได้เลย — วัดแล้วว่าได้ 0 ผลลัพธ์
>
> และ `name_fold_light` ต้อง **ไม่เหมือน** `name_fold_heavy` (light เก็บสระ) ถ้าเท่ากันแปลว่าชั้นที่ 2 ไม่มีประโยชน์
>
> `_nfkd` ใช้เฉพาะ `fold_heavy` — **ห้ามใช้กับ `norm` หรือ `fold_light`** เพราะ `norm` ต้องคงรูป NFD เพื่อให้ความยาวอักขระของคำค้น ≥ 3 ตามที่ trigram ต้องการ

**ข้อค้นพบสำคัญที่ 2 — `name_norm` ต้อง "เก็บ" วรรณยุกต์ ไม่ใช่ "ตัด"**

FTS5 trigram ทำงานบน **จำนวนอักขระ** ถ้า strip วรรณยุกต์ออกก่อน คำสั้น ๆ จะสั้นเกินไปจนค้นไม่เจอ ทดสอบจริงกับข้อมูลจริง:

| `name_norm` นิยามแบบ | `น้ำดื่ม` | `โค้ก` | `น้ำ` | ผลลัพธ์ |
|---|---|---|---|---|
| `isalnum()` (ตัดวรรณยุกต์ทิ้ง) | ❌ 0 hit | ❌ 0 hit | ❌ 0 hit | **พังทั้งระบบ** |
| เก็บ category `L/N/M` (ตัดเฉพาะช่องว่าง + อักขระพิเศษ) | ✅ 1 hit | ✅ 1 hit | ✅ 3 hit | **ถูกต้อง** |

→ กฎ: `name_norm` = NFD แล้ว**เก็บ**อักขระที่ category ขึ้นต้นด้วย `L`, `N`, `M` · **ตัด**เฉพาะช่องว่าง (`Z`) และอักขระพิเศษ (`P`, `S`) · lowercase

**ข้อจำกัดของ trigram: ต้องมีอย่างน้อย 3 อักขรร**

| คำค้น | จำนวนอักขระ | ผล |
|-------|-----------|-----|
| `น้ำ` | 3 | ✅ เจอ (ตรงกับ 4 จาก 15 สินค้าที่มี "น้ำ") |
| `น้ำดื่ม` | 7 | ✅ เจอ |
| `สิงห์` | 5 | ✅ เจอ |
| `นํา` (รูปที่ fold สระ) | 3 | ❌ ไม่เจอ — เพราะคนละชั้นกับ `name_norm` → ต้องแปลงคำค้นให้ตรงชั้นก่อน |
| `นำ` | 2 | ❌ ไม่เจอ — สั้นกว่า 3 |
| `น้` | 2 | ❌ ไม่เจอ — สั้นกว่า 3 |

→ **กฎการจัดการคำค้น:**
1. คำค้นต้องถูกแปลงเป็น `name_norm` **ด้วยฟังก์ชันเดียวกับตอน import** เสมอ (ห้ามส่ง string ดิบเข้า FTS)
2. คำค้นที่ normalize แล้ว **ยาว < 3 อักขรร** → ใช้ `LIKE 'q%'` prefix match บนคอลัมน์ที่มี B-tree index แทน (ที่ขนาดข้อมูลนี้เร็วมาก) ถ้ายังไม่มีผลลัพธ์ → ตอบว่า "พิมพ์เพิ่มอย่างน้อย 3 ตัวอักษร"
3. คำค้นที่ผู้ใช้พิมพ์มาจาก `name_fold_*` (คือพิมพ์ผิดวรรณยุกต์) → ให้ชั้น 4 (Levenshtein) จัดการ ไม่ต้องพึ่ง trigram

**ข้อค้นพบสำคัญ — ห้ามใช้ `unicodedata.combining()` ตัดวรรณยุกต์ไทย**

`unicodedata.combining()` คืน *canonical combining class* ซึ่งเป็น **0 สำหรับวรรณยุกต์ไทยเกือบทั้งหมด** แม้จะเป็น category `Mn` ก็ตาม — ตรวจสอบแล้วได้ผลดังนี้

| อักขระ | codepoint | `combining()` | `category()` |
|--------|-----------|---------------|--------------|
| ้ mai tho | U+0E49 | 107 | Mn |
| ่ mai ek | U+0E48 | 107 | Mn |
| ุ sara u | U+0E38 | 103 | Mn |
| **ิ sara i** | U+0E34 | **0** | Mn |
| **ึ sara ue** | U+0E36 | **0** | Mn |
| **็ mai taikhu** | U+0E47 | **0** | Mn |
| **ั mai hanakat** | U+0E31 | **0** | Mn |
| **์ thanthakhat** | U+0E4C | **0** | Mn |
| **ํ nikhahit** | U+0E4D | **0** | Mn |

→ ต้องใช้ **`unicodedata.category(ch) == 'Mn'`** เท่านั้น มิฉะนั้น fold จะไม่ทำงานกับกรณีพิมพ์ผิดที่พบบ่อยที่สุด

**ระดับการ fold และความครอบคลุม (วัดจากข้อมูลจริงด้วย rapidfuzz 3.14.6)**

| คู่ที่ต้อง match | light | heavy | ผลจริง |
|------------------|-------|-------|--------|
| `สิงห์` ↔ `สิงห` (ลืม ์) | ✅ | ✅ | ✅ เจอ |
| `ข้าวหอมมะลิ` ↔ `ขาวหอมมะลิ` (ลืม tone) | ✅ | ✅ | ✅ เจอ |
| `สิงห์` ↔ `สึงห์` (สระ+tone ต่างกัน) | ❌ | ✅ | ✅ เจอ (ผ่าน heavy fold) |
| `น้ำดื่ม` ↔ `น้ำดืม` (สระ+tone ต่างกัน) | ❌ | ✅ | ✅ เจอ |
| `กาแฟ` ↔ `กแฟ` (ตกสระจากคำค้นสั้น) | ❌ | ❌ | ❌ **ไม่เจอ — ข้อจำกัดที่รับได้** |

**ข้อจำกัดที่วัดแล้ว:** `กแฟ` → `กาแฟ` เป็นการตกสระ 1 ตัวจากคำค้นความยาว 3 ทำให้คะแนนสูงสุดที่ทำได้คือ 57 (ไม่ว่าจะใช้ scorer ใด) จึง **ไม่สามารถแก้ด้วยการปรับเกณฑ์** — การเพิ่ม threshold จะทำให้เกิดผลบวกลวงมากขึ้น

**วิธีรับมือ:** พึ่ง **autocomplete** ซึ่งทำงานด้วย trigram prefix match ตอนผู้ใช้พิมพ์ — เมื่อพิมพ์ถึง 3 ตัวอักษร `กาแฟ` จะปรากฏใน dropdown ให้เลือกก่อนกดค้นหา ดังนั้นกรณีนี้จึงถูกปิดกั้นที่ชั้น UI ไม่ใช่ที่ชั้น engine

- **`light`** ใช้เป็นค่า default เพราะแก้กรณีพิมพ์ผิดที่พบบ่อยสองแบบโดยไม่ทำให้คำต่างกันชนกัน
- **`heavy`** ใช้เป็นตัวสร้าง candidate เพิ่ม recall ให้กรณีสระ/วรรณยุกต์ต่างกัน — **ตรวจแล้วกับข้อมูลจริง 15 สินค้า ไม่เกิดการชนกันเลย (15 → 15 keys, 0 collisions)** แต่ต้องระวังว่าโดยทั่วไปมันอาจทำให้ `มา` กับ `ม่า` ชนกัน จึงห้ามใช้ heavy เป็นตัวตัดสินสุดท้าย — ต้องยืนยันด้วยการวัดซ้ำบน `name_norm` อีกครั้ง
- ต้องเก็บทั้ง 3 ชั้นเป็นคอลัมน์จริง (คำนวณตอน import) เพื่อไม่ต้องคำนวณซ้ำตอน query
- **`pack_size`**: regex `x\s*(\d+)\s*$` ท้ายชื่อ · ไม่เจอ → `NULL` · ค่านี้คือ **จำนวนต่อแพ็ค ไม่ใช่จำนวนที่ขาย**
- **`unit` ไม่มีในข้อมูลต้นทาง → ตั้ง `NULL` เสมอ** (ห้ามเดาค่า เช่น "กล่อง" เพราะไม่มีหลักฐานยืนยัน)

### 4.2.1 ผลการทดสอบความสามารถของ SQLite FTS5 กับภาษาไทย (ตรวจจริงแล้ว)

| ความสามารถ | ผล |
|-----------|-----|
| SQLite เวอร์ชันในเครื่อง | 3.50.4 — รองรับ FTS5 |
| `tokenize='trigram'` + `MATCH 'น้ำดื่ม'` | ✅ เจอ |
| `tokenize='trigram'` + `MATCH 'สิงห์'` | ✅ เจอ |
| `tokenize='trigram'` + `MATCH '600มล'` | ✅ เจอ |
| `tokenize='trigram'` + `MATCH 'สิงห์600'` | ✅ เจอ (ข้ามช่องว่างได้) |
| tokenizer ปริยาย `unicode61` + `MATCH 'สิงห์'` | ❌ **ไม่เจอ** — ตัดคำไทยไม่ได้ |

→ ยืนยันการเลือก **trigram** เป็น tokenizer ที่ถูกต้อง (ไม่ใช่ค่าเริ่มต้น)

### 4.3 กติกาความถูกต้องของ Import

- แถวทั้งหมดต้องมี `Product Name` และ `Customer Name` — ถ้าไม่มี → ข้ามพร้อมบันทึก log
- `Bar_Code` ว่าง → บันทึก `NULL` ไม่ error
- `Original Expected Date` ที่ parse ไม่ได้ → เก็บ `date_from = date_to = NULL` และ flag ในรายงาน
- รายงานสรุปหลัง import: จำนวนแถวเข้า/ข้าม, จำนวนสินค้า/ลูกค้า/บาร์โค้ด, วันที่ที่ parse ไม่ได้
- **Idempotent** — import ซ้ำด้วยไฟล์เดิมต้องได้ผลเหมือนเดิม (ลบ snapshot เดิมแล้วสร้างใหม่เสมอ)

---

## 5. Search Engine

### 5.1 ชั้นการค้นหา (เรียงตามความเร็ว)

| ชั้น | วิธี | เวลาคาด |
|-----|------|---------|
| 1 | บาร์โค้ด: ตัดเหลือตัวเลข → index lookup | < 5 ms |
| 2 | ชื่อลูกค้า: exact บน `name_norm` → fuzzy ด้วย **rapidfuzz `WRatio`** บน `name_fold_light` (มี 20 รายการ) | < 10 ms |
| 3 | FTS5 **trigram** บน `name_norm` → substring แม้ไม่มีช่องว่าง (ยืนยันแล้วว่า tokenizer ปริยาย `unicode61` ใช้ไม่ได้กับไทย) | ~ 20 ms |
| 4 | ถ้าผล < 5 รายการ → **2 ขั้น**: ขยาย candidate ด้วย `name_fold_heavy` + `WRatio` ≥ 45 แล้วยืนยันด้วย `WRatio` บน `name_norm` ≥ 70 | ~ 50 ms |

**scorer ที่ถูกต้อง: `WRatio` ไม่ใช่ `ratio`** (วัดแล้ว)

เนื่องจากผู้ใช้พิมพ์ **substring** ของชื่อสินค้าที่ยาว 20–48 ตัวอักษร `fuzz.ratio` จะเทียบความยาวเต็มจึงให้คะแนนต่ำมาก

| scorer | ค้น `สิงห์` ใน `น้ำดื่มสิงห์600มลx12` (เกณฑ์ 70) |
|--------|------------------------------------------------|
| `fuzz.ratio` | ❌ ไม่เจอ (คะแนนต่ำกว่า 70 เพราะเทียบความยาวเต็ม) |
| `fuzz.token_set_ratio` | ❌ ไม่เจอ |
| `fuzz.partial_ratio` | ✅ 100.0 |
| **`fuzz.WRatio`** | ✅ **90.0** ← ใช้ตัวนี้ (รองรับทั้ง substring และการพิมพ์ใกล้เคียง) |

- ชั้น 4 เป็น fallback เท่านั้น เพื่อไม่ให้ผลลัพธ์เต็มเป็น noise
- **ห้ามใช้ผลจาก `name_fold_heavy` เป็นคำตอบสุดท้ายโดยไม่ยืนยันกับ `name_norm`** เพราะ heavy fold อาจทำให้คำต่างกันชนกัน (ดู 4.2)
- **อย่าส่ง list of tuples เข้า `process.extract`** เพราะ `fuzz` จะเทียบกับ tuple แล้วได้คะแนน 0 — ให้ส่ง list of string แล้วแปลงกลับด้วย reverse map
- `process.extract` คืน **3-tuple** `(value, score, index)` เมื่อ choices เป็น list และ `(value, score, key)` เมื่อเป็น dict — ต้อง destructure ให้ถูก

### 5.2 Intention Detection

```
ตัวเลขล้วน ยาว 8–14 ตัว      → โหมดบาร์โค้ด
ตรงกับชื่อลูกค้า (exact/fuzzy) → โหมดลูกค้า
ตรงกับชื่อสินค้า              → โหมดสินค้า
ตรงทั้งสองอย่าง               → รวมผลลัพธ์ทั้งสองโหมด
ไม่ตรงอะไรเลย                → ค้นหาสินค้าแบบ fuzzy เป็นหลัก
```

ผู้ใช้บังคับโหมดได้ด้วยพารามิเตอร์ `mode` (`auto` | `customer` | `product`)

### 5.3 รูปแบบผลลัพธ์

**โหมดลูกค้า** — ตารางสินค้าที่ลูกค้าเคยซื้อ:
สินค้า · จำนวนครั้งที่ซื้อ · วันคาดส่งล่าสุด · สาขาที่ซื้อ · Order Type · Item Remark · VIP tier · VIP remark

**โหมดสินค้า** — ตารางลูกค้าที่ซื้อสินค้านั้น:
ลูกค้า · จำนวนครั้งที่ซื้อ · VIP tier · สาขา · วันคาดส่งล่าสุด → ใช้ทำ cross-sell ได้ตรงจุด

### 5.4 Pagination

- ใช้ **cursor-based** (`limit` + `cursor`) ไม่ใช้ offset — ผลลัพธ์ถูกจัดอันดับตาม relevance ซึ่งไม่ stable พอสำหรับ offset
- ค่าเริ่มต้น `limit = 20`, สูงสุด `100`

---

## 6. API Surface

```
POST /api/v1/auth/login          {username, password} → ตั้ง httpOnly cookie
POST /api/v1/auth/logout
POST /api/v1/auth/refresh
GET  /api/v1/auth/me

POST /api/v1/search             {q, mode, filters{}, limit, cursor}   ← PII ใน body
POST /api/v1/suggest           {q, limit}                            ← PII ใน body
GET  /api/v1/customers/{id}/history
GET  /api/v1/products/{id}/customers
GET  /api/v1/filters                                        ค่า facet สำหรับ UI

POST /api/v1/admin/import       อัปโหลด xlsx → สร้าง snapshot ใหม่
GET  /api/v1/admin/audit
GET  /api/v1/admin/users
POST /api/v1/admin/users
PATCH /api/v1/admin/users/{id}

GET  /healthz
```

**เหตุผลที่ search/suggest ใช้ POST:** การใส่คำค้น (ซึ่งเป็น PII) ใน URL จะรั่วผ่าน browser history, `Referer` header ไปยังเว็บไซต์อื่น, access log ของ reverse proxy และ CDN

---

## 7. ความปลอดภัย

| ชั้น | การทำ |
|------|-------|
| Authentication | บัญชีพนักงานในตาราง `users` · password hash ด้วย **argon2id** · JWT access 15 นาที + refresh 7 วันใน **httpOnly, Secure, SameSite=Strict** cookie · รองรับ **TOTP 2FA** |
| Session | idle timeout 30 นาที (ตรวจ server-side) · logout ยกเลิก refresh token ทันที |
| RBAC | `staff` = ค้นหา + ดูประวัติลูกค้า · `admin` = + จัดการ user / import / ดู audit log |
| PII ไม่หลุดใน URL | search และ suggest ใช้ `POST` + body ทั้งคู่ |
| Audit log | ทุกครั้งที่ค้น: ผู้ใช้ · คำค้น · โหมด · จำนวนผลลัพธ์ · IP · user-agent · เวลา · append-only · อ่านได้เฉพาะ admin |
| Rate limit | 60 req/นาที/ผู้ใช้ (ใช้ in-process counter — single container) |
| Cache | ทุก response ที่มีข้อมูลลูกค้า → `Cache-Control: no-store` · ปิด CDN cache สำหรับ `/api/*` |
| At rest | `snapshot.enc` เข้ารหัส **AES-256-GCM** · กุญแจจาก env `DATA_KEY` (รองรับ key rotation ด้วย `key_id`) |
| Transport | HTTPS บังคับ + HSTS + redirect HTTP→HTTPS |
| Input | SQL แบบ parameterized เท่านั้น · Pydantic validate · จำกัดความยาวคำค้น 200 ตัวอักษร |
| Export | **ปิดเป็นค่าเริ่มต้น** · ถ้าเปิด: admin เท่านั้น + audit + ฝัง watermark ชื่อผู้ใช้/เวลา |
| Secrets | ทั้งหมดจาก env var · ไม่ hardcode · ไม่ commit `.env` |
| PDPA | มี audit trail · retention policy · เตรียมโครงสร้างรองรับสิทธิ์เจ้าของข้อมูล (ลบ/แก้ไข) ในอนาคต |

**ข้อกำหนดเฉพาะของ PWA:** service worker cache **เฉพาะ app shell** — ห้าม cache ข้อมูลลูกค้าไว้ในเครื่อง

---

## 8. หน้าจอมือถือ (PWA)

- ช่องค้นหาสูง 56px กลางจอ + **autofocus** + ปุ่มล้าง
- **chip แสดงว่าระบบเดาว่าเป็น "ลูกค้า" หรือ "สินค้า"** พร้อมปุ่มสลับโหมด
- ผลลัพธ์เป็น **การ์ด** บนมือถือ (ตารางบนจอ ≥ 1024px)
  - **การ์ดลูกค้า**: ชื่อ + ป้าย VIP → รายการสินค้าที่เคยซื้อ · จำนวนครั้ง · วันล่าสุด · สาขา · Order Type · หมายเหตุ
  - **การ์ดสินค้า**: ชื่อสินค้า + จำนวนลูกค้า → กดเจาะดูรายชื่อลูกค้า
- ตัวกรองเป็น **bottom sheet**: สาขา / Dept / Class / Subclass / Order Type / VIP / ช่วงวันที่
- ติดตั้งได้ (manifest + service worker) · ใช้งานเต็ม viewport · ปุ่มอยู่ในระยะเอื้อมถือ
- แสดงข้อความกำกับว่า "วันที่คือวันคาดส่ง ไม่ใช่วันสั่งซื้อ"

---

## 9. แผนทดสอบ

### 9.0 ข้อมูลจริงที่ยืนยันแล้ว (ground truth สำหรับ golden tests)

ตรวจอ่านจากไฟล์จริงแล้ว ใช้เป็นค่าคาดหวังในเทสต์ได้เลย:

| ข้อเท็จจริง | ค่า |
|-----------|-----|
| จำนวนแถว | 1,000 |
| สินค้า | 15 · ลูกค้า 20 · สาขา 15 · Dept 9 · Class 14 · Subclass 15 |
| `Bar_Code` แบบ multi-value | 148 แถว · ตัวอย่าง `"21464546 || 2500001464545"` |
| บาร์โค้ด unique ก่อน split | 139 |
| บาร์โค้ด unique **หลัง** split ที่ `\|\|` | **127** (ลดลง 12 เพราะหลายสตริงซ้อนกัน) |
| `น้ำดื่มสิงห์ 600 มล. x 12` | 86 order lines · คนซื้อ 20 คน (ทุกคน) · สุรชัยซื้อ 6 ครั้ง · เอกชัยซื้อ 9 ครั้ง (มากสุด) |
| สินค้าที่มี "น้ำ" | 4 จาก 15 (ดื่มสิงห์ / ตาลทรายขาว / มันปาล์ม / ยาล้างจาน) |
| `สุรชัย` | 65 order lines · สินค้า 15 รายการ · 14 สาขา · VIP tier ทั้ง 4 (Gold, Platinum, VIP, Wholesale VIP) |
| `8850250001234` | → `น้ำดื่มสิงห์ 600 มล. x 12` |
| ลูกค้าที่มีออเดอร์น้อยที่สุด | `วราภรณ์` = 32 |
| สินค้าที่ไม่มี `x N` | `ทิชชู่ม้วน 24 ม้วน` → `pack_size = NULL` |
| คู่ (ลูกค้า, สินค้า) ที่ไม่ซ้ำ | 292 |

| ระดับ | เนื้อหา |
|-------|--------|
| Unit | `normalize`: `light`/`heavy` fold (ต้องใช้ `category()=='Mn'` **ไม่ใช่** `combining()`), `norm`, parse `x N` · `Bar_Code` split ที่ `\|\|` · parse date range `DD-Mon-YYYY - DD-Mon-YYYY` |
| Unit | **Regression กัน over-fold**: `light` ต้องทำให้ `สิงห์`==`สิงห` และ `ข้าวหอม`==`ขาวหอม` แต่ต้อง **ไม่** ทำให้ `ปลา`==`ปา` · ตรวจว่า `light`/`heavy` บนข้อมูลจริง 15 สินค้าไม่เกิด key ชนกัน |
| Import | 1,000 แถวเข้าครบ · จำนวนบาร์โค้ดหลัง split · VIP tier คงอยู่ระดับ order line · import ซ้ำได้ผลเดิม (idempotent) |
| Search golden | ใช้ข้อมูลจริง 1,000 แถว: `"น้ำดื่มสิงห์"` → ต้องเจอสุรชัย · บาร์โค้ด `8850250001234` → ต้องเจอ · พิมพ์ผิด `"สิงห"` (ลืม ์) → ยังเจอ · ชื่อลูกค้า `"สุรชัย"` → ได้รายการสินค้าครบ |
| Search unit | ทั้ง 4 ชั้น · intention detection ทุกกรณี · กรองตามทุก facet ตามกติกาใน 4.1.1 · pagination ไม่ตกหล่น/ไม่ซ้ำ |
| Security | ไม่ login → 401 · `staff` เรียก `/admin` → 403 · เกิน rate limit → 429 · response มี `no-store` · ไม่มี PII ใน URL · password ไม่ถูก log · ไม่มี plaintext ของ snapshot บนดิสก์หลัง decrypt |
| UI | snapshot ของ Playwright: login → ค้นหา → เห็นการ์ดผลลัพธ์บน viewport มือถือ |
| Performance | p95 < 200 ms ที่ 1,000 แถว · load test ที่ 100,000 แถวสังเคราะห์ · cold start < 60 วิ |
| Fixture | synthetic data ที่มีวันที่หลากหลาย — เพราะข้อมูลจริงทุกแถวเป็นวันเดียวกัน ทดสอบการกรองตามวันไม่ได้ |

---

## 10. ข้อจำกัดที่ทราบแล้ว

1. **ไม่มี Customer ID** — ใช้ชื่อเป็น key; ชื่อซ้ำของคนละคนจะถูกรวม
2. **ไม่มีวันสั่งซื้อ** — ใช้ `Original Expected Date` (วันคาดส่ง) แทน
3. **ไม่มีจำนวน/ราคา** — `qty`/`price` เป็น NULL; ปริมาณอยู่ในชื่อสินค้า (`x N`) จึง parse เป็น `pack_size` แต่ไม่ใช่จำนวนที่ขาย
4. **ข้อมูลตัวอย่างมีวันเดียว** — การกรองตามช่วงวันต้องทดสอบด้วย synthetic fixture
5. **ชื่อสินค้าคืนค่าเดิมทุกแถว** — ประวัติ "ซื้ออะไร" คือประวัติ "เคยสั่งอะไร" ไม่ใช่ "ซื้อจริง"
6. **Cold start** บน Render free — ผลกระทบการใช้งานช่วงแรกหลัง idle
7. **Single container** — ไม่ scale แนวนอน; เพียงพอมากถ้าข้อมูลไม่เกินหลักแสนแถว

---

## 11. การตัดสินใจที่ผ่านแล้ว (สรุป)

| # | การตัดสิน | เหตุผล |
|---|----------|--------|
| 1 | เลือกสถาปัตยกรรม A (FastAPI + encrypted SQLite + PWA) | คุมความปลอดภัยเอง 100%, เข้า free tier ได้, ไม่ติด vendor |
| 2 | ผู้ใช้มีแค่ 2 role: `staff`, `admin` | scope ไม่มีลูกค้าใช้เอง ไม่มีผู้บริหารแยก |
| 3 | ต้องมี API server เป็นตัวกลาง | static site เปิดข้อมูลดิบให้ทุกคนดาวน์โหลด |
| 4 | SQLite read-only + เข้ารหัส แทนการเช่า DB | ไม่มี persistent disk บน free tier, ข้อมูลเล็ก |
| 5 | search ใช้ `POST` ไม่ใช่ `GET` | กัน PII รั่วผ่าน URL/history/referrer |
| 6 | VIP tier/remark คงระดับ order line | ข้อมูลจริงขัดแย้งเองในระดับลูกค้า |
| 7 | แต่ละแถว = 1 ออเดอร์ แต่โครงรองรับ 1:N | `NO.` เป็นเลขลำดับแถว แต่อนาคตอาจเป็นเลขออเดอร์ |
| 8 | service worker cache เฉพาะ app shell | ไม่ให้ PII ค้างในเครื่อง |
| 9 | ใช้ **3 ระดับ** การ normalize: `norm` / `fold_light` / `fold_heavy` | ตรวจแล้วว่า light แก้กรณีพิมพ์ผิดที่พบบ่อยได้แต่ไม่ครอบคลุมกรณีสระต่างกัน ส่วน heavy ครอบคลุมแต่เสี่ยงชนกัน → ต้องมีทั้งสองระดับ |
| 10 | ตัดวรรณยุกต์ด้วย `category()=='Mn'` **ไม่ใช่** `combining()` | `combining()` คืน 0 สำหรับ `ิ ึ ์ ็ ั` ซึ่งเป็นกรณีพิมพ์ผิดที่พบบ่อยที่สุด → fold จะไม่ทำงาน |
| 11 | ใช้ FTS5 `trigram` | tokenizer ปริยาย `unicode61` ตัดคำไทยไม่ได้ (ทดสอบ: `MATCH 'สิงห์'` ไม่เจอ) |
| 12 | `name_norm` **เก็บ** วรรณยุกต์ ไม่ใช่ตัด | ถ้าใช้ `isalnum()` จะตัดวรรณยุกต์ → trigram จับ `น้ำดื่ม` และ `โค้ก` ไม่ได้เลย (0 hit ทั้งคู่) |
| 13 | คำค้นยาว < 3 อักขรรใช้ `LIKE 'q%'` แทน trigram | ข้อจำกัดของ trigram tokenizer · ที่ขนาดข้อมูลนี้เร็วพอ |
| 14 | เก็บ `unit` = NULL เสมอ | ไม่มีข้อมูลหน่วยในไฟล์ต้นทาง — ห้ามเดา |
| 15 | เก็บ `users` + `audit_log` แยกจาก snapshot | ต้องเขียนได้ และเปลี่ยนบัญชีผู้ใช้ไม่ต้อง rebuild snapshot |
