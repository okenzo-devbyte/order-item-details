const MONTHS = { Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6, Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12 };

export function parseDate(d) {
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/.exec(String(d ?? '').trim());
  if (!m) return null;
  const month = MONTHS[m[2]];
  if (!month) return null;
  const day = +m[1], year = +m[3];
  const dt = new Date(Date.UTC(year, month - 1, day));
  if (dt.getUTCFullYear() !== year || dt.getUTCMonth() !== month - 1 || dt.getUTCDate() !== day) return null;
  return dt.toISOString().slice(0, 10);
}

export function parseExpectedRange(raw) {
  const m = /^\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\s*-\s*(\d{1,2}-[A-Za-z]{3}-\d{4})\s*$/.exec(String(raw ?? ''));
  if (!m) return null;
  const from = parseDate(m[1]);
  const to = parseDate(m[2]);
  if (!from || !to) return null;
  return { from, to, raw: String(raw) };
}

export function parseSearchQuery(query) {
  const errors = [];
  const direction = query.direction === 'product' ? 'product' : 'customer';
  const q = String(query.q ?? '').trim();
  if (q.length > 100) errors.push({ field: 'q', message: 'คำค้นยาวเกิน 100 ตัวอักษร' });
  const num = (v) => {
    if (v === undefined || v === '') return null;
    const n = Number(v);
    return Number.isInteger(n) && n > 0 ? n : null;
  };
  const dept = num(query.dept);
  const cls = num(query.class);
  const subclass = num(query.subclass);
  if (query.dept !== undefined && query.dept !== '' && dept === null) errors.push({ field: 'dept', message: 'dept ต้องเป็นตัวเลข' });
  if (query.class !== undefined && query.class !== '' && cls === null) errors.push({ field: 'class', message: 'class ต้องเป็นตัวเลข' });
  if (query.subclass !== undefined && query.subclass !== '' && subclass === null) errors.push({ field: 'subclass', message: 'subclass ต้องเป็นตัวเลข' });
  let page = num(query.page) ?? 1;
  let pageSize = num(query.page_size) ?? 50;
  pageSize = Math.min(Math.max(pageSize, 1), 100);
  page = Math.max(page, 1);
  return { direction, q, dept, cls, subclass, page, pageSize, errors };
}

const REQUIRED_HEADERS = [
  'Order Number', 'Store Code', 'Item Id', 'Product Name', 'Original Expected Date',
  'Dept', 'Class', 'Subclass', 'Customer Name', 'Item Remark', 'VIP Customer Remarks', 'VIP Customer Groups'
];

export function validateImportRows(rows) {
  const errors = [];
  const warnings = [];
  if (!Array.isArray(rows) || rows.length === 0) {
    return { errors: [{ row: 0, field: '_file', message: 'ไฟล์ว่างหรืออ่านไม่ได้' }], warnings };
  }
  const headers = Object.keys(rows[0]);
  const missing = REQUIRED_HEADERS.filter((h) => !headers.includes(h));
  if (missing.length) {
    return { errors: [{ row: 0, field: '_headers', message: `หัวคอลัมน์ไม่ครบ: ${missing.join(', ')}` }], warnings };
  }
  const seen = new Map();
  rows.forEach((r, i) => {
    const rowNo = i + 2;
    const orderNumber = String(r['Order Number'] ?? '').trim();
    const itemId = String(r['Item Id'] ?? '').trim();
    if (!orderNumber) errors.push({ row: rowNo, field: 'Order Number', message: 'ว่าง' });
    if (!itemId) errors.push({ row: rowNo, field: 'Item Id', message: 'ว่าง' });
    const key = `${orderNumber}|${itemId}`;
    if (orderNumber && itemId) {
      if (seen.has(key)) errors.push({ row: rowNo, field: 'Order Number', message: `ซ้ำกับแถว ${seen.get(key)}` });
      else seen.set(key, rowNo);
    }
    const range = parseExpectedRange(r['Original Expected Date']);
    if (!range) errors.push({ row: rowNo, field: 'Original Expected Date', message: 'รูปแบบวันที่ไม่ถูก (ต้องการ dd-Mon-yyyy - dd-Mon-yyyy)' });
    else {
      r._from = range.from;
      r._to = range.to;
    }
    for (const f of ['Dept', 'Class', 'Subclass']) {
      const v = r[f];
      if (v !== undefined && v !== '' && v !== null && !Number.isInteger(Number(v))) {
        errors.push({ row: rowNo, field: f, message: 'ต้องเป็นตัวเลข' });
      }
    }
  });
  return { errors, warnings };
}
