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
const { error } = await sb.from('users').insert({ username, password_hash: hashPassword(password), role });
if (error) {
  console.error('Failed:', error.message);
  process.exit(1);
}
console.log(`Created ${role} user "${username}"`);
