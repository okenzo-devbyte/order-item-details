# Order Groups Web

เว็บค้นหากลุ่มสินค้าที่ลูกค้าเคยซื้อ (ภาษาไทย) — HTML + Vercel Serverless Functions + Supabase Postgres

## ต้องมี

- Node 20+ (แนะนำ 22+)
- Supabase project (คุณมีแล้ว)

## ตั้งค่า

1. เปิด **Supabase Dashboard → SQL Editor** แล้วรันไฟล์ `migrations/001_schema.sql` ทั้งไฟล์
2. `npm install`
3. คัดลอก `.env.example` เป็น `.env` แล้วกรอกค่า:
   - `SUPABASE_URL` — Project Settings → Data API
   - `SUPABASE_SERVICE_ROLE_KEY` — Project Settings → API Keys (service_role, **ห้ามเปิดเผย**)
   - `SESSION_SECRET` — สตริงสุ่มยาว ๆ อะไรก็ได้
4. สร้าง user แรก: `USER_PASSWORD=<รหัสผ่าน> node scripts/create-user.js admin <ชื่อผู้ใช้>`
5. รันเครื่อง: `npm run dev` แล้วเปิด `http://localhost:3000`
6. Deploy: `vercel` (ตั้ง env ทั้ง 3 ตัวใน Vercel project ด้วย)

## Smoke checklist

- ยังไม่ login เปิด `/` → เด้งไป `/login.html`
- login admin → กลับมาหน้าค้น
- `/admin.html` → import `simpledata_1000rows.xlsx` (replace) → toast สำเร็จ
- ค้นชื่อลูกค้า (customer) → การ์ดมีจำนวนออเดอร์ + badge กลุ่มสินค้า
- ค้นชื่อสินค้า (product) → การ์ดมีจำนวนลูกค้า
- คลิกการ์ด → ตารางรายละเอียด; ปุ่ม back ของเบราว์เซอร์ทำงาน
- login viewer → เปิด `/admin.html` → toast "ไม่มีสิทธิ์เข้าถึง" + เด้งกลับ `/`
- admin → ล้างข้อมูล (พิมพ์ `ลบทั้งหมด` ยืนยัน) → สำเร็จ

## โครงสร้าง

- `public/` — หน้าเว็บ static (HTML/CSS/JS ล้วน, ไม่มี build)
- `api/` — Vercel Functions; ทุก route คุยกับ DB ผ่าน `api/_lib/repository.js` เท่านั้น
- `api/_lib/adapters/supabase.js` — ไฟล์เดียวที่รู้จัก Supabase (เปลี่ยน DB = เขียน adapter ใหม่ไฟล์เดียว)
- `api/_lib/adapters/memory.js` — adapter in-memory สำหรับ test
- `migrations/` — SQL schema (`order_item` namespace)
- `scripts/create-user.js` — สร้าง user admin/viewer
- `tests/` — รันด้วย `npm test` (`node --test`)
