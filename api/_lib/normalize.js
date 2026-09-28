export function normalizeThai(s) {
  return String(s ?? '').toLowerCase().replace(/\s+/g, '').trim();
}
