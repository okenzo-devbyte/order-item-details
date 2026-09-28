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
