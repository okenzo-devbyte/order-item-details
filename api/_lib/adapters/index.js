import { createClient } from '@supabase/supabase-js';
import { loadConfig } from '../config.js';
import { createSupabaseAdapter } from './supabase.js';

let _adapter;

export function getAdapter(env = process.env) {
  if (!_adapter) {
    const cfg = loadConfig(env);
    // Tables live in the `order_item` schema, not `public`.
    const client = createClient(cfg.supabaseUrl, cfg.supabaseKey, { db: { schema: 'order_item' } });
    _adapter = createSupabaseAdapter(client);
  }
  return _adapter;
}
