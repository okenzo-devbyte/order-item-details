@echo off
rem จัดการผู้ใช้ (สร้าง/ดู/เปลี่ยนรหัส/เปลี่ยนบทบาท/เปิด-ปิด/ลบ)
chcp 874 >nul
cd /d "%~dp0\.."

where node >nul 2>nul
if errorlevel 1 (
  echo ไม่พบ Node.js กรุณาติดตั้งก่อน
  pause
  exit /b 1
)

if not exist ".env" (
  echo ไม่พบไฟล์ .env
  echo ให้คัดลอก .env.example เป็น .env แล้วกรอกค่า SUPABASE_URL และ SUPABASE_SERVICE_ROLE_KEY ก่อน
  pause
  exit /b 1
)

:menu
echo.
echo === จัดการผู้ใช้ ===
echo  1. สร้าง admin
echo  2. สร้าง viewer
echo  3. ดูรายชื่อผู้ใช้
echo  4. เปลี่ยนรหัสผ่าน
echo  5. เปลี่ยนบทบาท (admin/viewer)
echo  6. เปิด/ปิดบัญชี
echo  7. ลบผู้ใช้
echo  0. ออก
echo.
set /p choice="เลือกเมนู: "

if "%choice%"=="1" goto create_admin
if "%choice%"=="2" goto create_viewer
if "%choice%"=="3" goto list_users
if "%choice%"=="4" goto change_password
if "%choice%"=="5" goto change_role
if "%choice%"=="6" goto toggle_active
if "%choice%"=="7" goto delete_user
if "%choice%"=="0" exit /b 0
echo เลือก 0-7 เท่านั้น
goto menu

:create_admin
set /p username="ชื่อผู้ใช้ admin: "
set /p password="รหัสผ่าน: "
set USER_PASSWORD=%password%
node scripts\users.js create admin "%username%"
set USER_PASSWORD=
pause
goto menu

:create_viewer
set /p username="ชื่อผู้ใช้ viewer: "
set /p password="รหัสผ่าน: "
set USER_PASSWORD=%password%
node scripts\users.js create viewer "%username%"
set USER_PASSWORD=
pause
goto menu

:list_users
node scripts\users.js list
pause
goto menu

:change_password
set /p username="ชื่อผู้ใช้: "
set /p password="รหัสผ่านใหม่: "
set USER_PASSWORD=%password%
node scripts\users.js password "%username%"
set USER_PASSWORD=
pause
goto menu

:change_role
set /p username="ชื่อผู้ใช้: "
set /p role="บทบาทใหม่ (admin/viewer): "
node scripts\users.js role "%username%" "%role%"
pause
goto menu

:toggle_active
set /p username="ชื่อผู้ใช้: "
set /p flag="เปิดหรือปิด (on/off): "
node scripts\users.js active "%username%" "%flag%"
pause
goto menu

:delete_user
set /p username="ชื่อผู้ใช้ที่จะลบ: "
set /p confirm="พิมพ์ชื่อผู้ใช้อีกครั้งเพื่อยืนยัน: "
if not "%username%"=="%confirm%" (
  echo ชื่อไม่ตรงกัน ยกเลิก
  pause
  goto menu
)
node scripts\users.js delete "%username%"
pause
goto menu
