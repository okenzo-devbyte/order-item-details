import { api, me, logout } from './api.js';
import { toast, escapeHtml } from './ui.js';

const fileInput = document.getElementById('file-input');
const preview = document.getElementById('preview');
const importBtn = document.getElementById('import-btn');
const importError = document.getElementById('import-error');
const confirmInput = document.getElementById('confirm-input');
const clearBtn = document.getElementById('clear-btn');

let pendingRows = null;
let pendingName = '';

async function guard() {
  const u = await me();
  if (!u) { window.location.href = '/login.html?next=/admin.html'; return null; }
  if (u.role !== 'admin') {
    toast('ไม่มีสิทธิ์เข้าถึง');
    setTimeout(() => { window.location.href = '/'; }, 1200);
    return null;
  }
  return u;
}

function readWorkbook(file) {
  const reader = new FileReader();
  return new Promise((resolve, reject) => {
    reader.onload = (e) => {
      try {
        const wb = XLSX.read(e.target.result, { type: 'array' });
        const sheet = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: '' });
        if (!rows.length) return reject(new Error('ไฟล์ว่าง'));
        const header = rows[0].map((h) => String(h).trim());
        const data = rows.slice(1).filter((r) => r.some((c) => String(c).trim() !== ''));
        const objs = data.map((r) => {
          const o = {};
          header.forEach((h, i) => { o[h] = r[i]; });
          return o;
        });
        resolve({ name: file.name, rows: objs });
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error('อ่านไฟล์ไม่ได้'));
    reader.readAsArrayBuffer(file);
  });
}

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;
  importError.hidden = true;
  try {
    const { name, rows } = await readWorkbook(file);
    pendingRows = rows;
    pendingName = name;
    preview.hidden = false;
    document.getElementById('preview-name').textContent = name;
    document.getElementById('preview-rows').textContent = String(rows.length);
    document.getElementById('preview-headers').textContent = Object.keys(rows[0] || {}).join(', ');
    importBtn.disabled = rows.length === 0;
  } catch (err) {
    toast('อ่านไฟล์ไม่ได้: ' + err.message);
    importBtn.disabled = true;
  }
});

importBtn.addEventListener('click', async () => {
  if (!pendingRows) return;
  const mode = document.querySelector('input[name="mode"]:checked').value;
  importBtn.disabled = true;
  importBtn.textContent = 'กำลังนำเข้า…';
  try {
    const data = await api('/api/admin/import?mode=' + mode + '&filename=' + encodeURIComponent(pendingName), {
      method: 'POST', body: { rows: pendingRows }
    });
    toast(`นำเข้าสำเร็จ: ${data.row_count} แถว`, 'success');
    await loadImports();
    preview.hidden = true;
    fileInput.value = '';
    pendingRows = null;
  } catch (err) {
    importError.hidden = false;
    importError.textContent = err.message;
    toast(err.message);
  } finally {
    importBtn.disabled = false;
    importBtn.textContent = 'นำเข้าข้อมูล';
  }
});

async function loadImports() {
  try {
    const data = await api('/api/admin/imports');
    const tbody = document.querySelector('#imports-table tbody');
    tbody.innerHTML = data.map((i) => `<tr>
      <td>${escapeHtml(i.filename)}</td>
      <td>${i.mode === 'replace' ? 'แทนที่' : 'เพิ่มต่อท้าย'}</td>
      <td>${i.row_count}</td>
      <td>${escapeHtml(i.imported_by || '')}</td>
      <td>${new Date(i.imported_at).toLocaleString('th-TH')}</td>
    </tr>`).join('');
  } catch { /* toast handled by api wrapper */ }
}

confirmInput.addEventListener('input', () => {
  clearBtn.disabled = confirmInput.value.trim() !== 'ลบทั้งหมด';
});

clearBtn.addEventListener('click', async () => {
  clearBtn.disabled = true;
  try {
    await api('/api/admin/clear', { method: 'POST', body: { confirm: true } });
    toast('ลบข้อมูลทั้งหมดสำเร็จ', 'success');
    confirmInput.value = '';
    clearBtn.disabled = true;
  } catch (err) {
    toast(err.message);
    clearBtn.disabled = false;
  }
});

document.getElementById('logout-btn').addEventListener('click', logout);

const user = await guard();
if (user) {
  await loadImports();
}
