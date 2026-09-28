import { createClient } from '@supabase/supabase-js';
import { loadConfig } from '../api/_lib/config.js';
import { hashPassword } from '../api/_lib/passwords.js';

function client() {
  const cfg = loadConfig();
  return createClient(cfg.supabaseUrl, cfg.supabaseKey, { db: { schema: 'order_item' } });
}

function usage() {
  console.log(`วิธีใช้:
  node scripts/users.js list
  node scripts/users.js create <admin|viewer> <username>      (รหัสผ่านจาก USER_PASSWORD)
  node scripts/users.js password <username>                   (รหัสผ่านใหม่จาก USER_PASSWORD)
  node scripts/users.js role <username> <admin|viewer>
  node scripts/users.js active <username> <on|off>
  node scripts/users.js delete <username>`);
  process.exit(1);
}

function need(value, message) {
  if (!value) {
    console.error(message);
    process.exit(1);
  }
  return value;
}

const [cmd, ...args] = process.argv.slice(2);

if (cmd === 'list') {
  const sb = client();
  const { data, error } = await sb.from('users').select('username,role,active,created_at').order('username');
  if (error) {
    console.error('ดึงรายชื่อไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  if (!data.length) console.log('ยังไม่มีผู้ใช้');
  for (const u of data) {
    console.log(`${u.username}\t${u.role}\t${u.active ? 'เปิดใช้' : 'ปิดใช้'}\t${u.created_at}`);
  }
} else if (cmd === 'create') {
  const role = need(args[0], 'ระบุบทบาท: admin หรือ viewer');
  const username = need(args[1], 'ระบุชื่อผู้ใช้');
  if (!['admin', 'viewer'].includes(role)) {
    console.error('บทบาทต้องเป็น admin หรือ viewer เท่านั้น');
    process.exit(1);
  }
  const password = need(process.env.USER_PASSWORD, 'ตั้งรหัสผ่านผ่านตัวแปร USER_PASSWORD ก่อน');
  const sb = client();
  const { error } = await sb.from('users').insert({ username, password_hash: hashPassword(password), role });
  if (error) {
    console.error('สร้างไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  console.log(`สร้าง ${role} "${username}" สำเร็จ`);
} else if (cmd === 'password') {
  const username = need(args[0], 'ระบุชื่อผู้ใช้');
  const password = need(process.env.USER_PASSWORD, 'ตั้งรหัสผ่านใหม่ผ่านตัวแปร USER_PASSWORD ก่อน');
  const sb = client();
  const { data, error } = await sb.from('users').update({ password_hash: hashPassword(password) }).eq('username', username).select('username');
  if (error) {
    console.error('เปลี่ยนรหัสผ่านไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  if (!data.length) {
    console.error(`ไม่พบผู้ใช้ "${username}"`);
    process.exit(1);
  }
  console.log(`เปลี่ยนรหัสผ่าน "${username}" สำเร็จ`);
} else if (cmd === 'role') {
  const username = need(args[0], 'ระบุชื่อผู้ใช้');
  const role = need(args[1], 'ระบุบทบาท: admin หรือ viewer');
  if (!['admin', 'viewer'].includes(role)) {
    console.error('บทบาทต้องเป็น admin หรือ viewer เท่านั้น');
    process.exit(1);
  }
  const sb = client();
  const { data, error } = await sb.from('users').update({ role }).eq('username', username).select('username');
  if (error) {
    console.error('เปลี่ยนบทบาทไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  if (!data.length) {
    console.error(`ไม่พบผู้ใช้ "${username}"`);
    process.exit(1);
  }
  console.log(`เปลี่ยน "${username}" เป็น ${role} สำเร็จ`);
} else if (cmd === 'active') {
  const username = need(args[0], 'ระบุชื่อผู้ใช้');
  const flag = need(args[1], 'ระบุ on หรือ off');
  if (!['on', 'off'].includes(flag)) {
    console.error('ต้องเป็น on หรือ off เท่านั้น');
    process.exit(1);
  }
  const sb = client();
  const { data, error } = await sb.from('users').update({ active: flag === 'on' }).eq('username', username).select('username');
  if (error) {
    console.error('เปลี่ยนสถานะไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  if (!data.length) {
    console.error(`ไม่พบผู้ใช้ "${username}"`);
    process.exit(1);
  }
  console.log(`${flag === 'on' ? 'เปิดใช้' : 'ปิดใช้'} "${username}" สำเร็จ`);
} else if (cmd === 'delete') {
  const username = need(args[0], 'ระบุชื่อผู้ใช้');
  const sb = client();
  const { data, error } = await sb.from('users').delete().eq('username', username).select('username');
  if (error) {
    console.error('ลบไม่สำเร็จ:', error.message);
    process.exit(1);
  }
  if (!data.length) {
    console.error(`ไม่พบผู้ใช้ "${username}"`);
    process.exit(1);
  }
  console.log(`ลบ "${username}" สำเร็จ`);
} else {
  usage();
}
