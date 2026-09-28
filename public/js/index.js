import { api, me, logout } from './api.js';
import { toast, escapeHtml, debounce, skeleton, formatDate } from './ui.js';

const state = {
  q: '',
  page: 1,
  view: 'search', // 'search' | 'customer'
  customer: '',
  // Detail view state
  currentCustomerData: null,
  orderFilterQuery: '',
  orderPage: 1,
  orderPageSize: 25
};

const resultsEl = document.getElementById('results');
const searchInput = document.getElementById('search-input');
const searchClearBtn = document.getElementById('search-clear');
const paginationEl = document.getElementById('pagination');
const resultsMetaBar = document.getElementById('results-meta-bar');
const resultsCountEl = document.getElementById('results-count');
const kpiBanner = document.getElementById('kpi-banner');
const searchSection = document.getElementById('search-section');

function readUrl() {
  const p = new URLSearchParams(window.location.search);
  state.q = p.get('q') || '';
  state.page = Number(p.get('page') || '1');
  state.view = p.get('view') === 'customer' ? 'customer' : 'search';
  state.customer = p.get('customer') || '';
}

function writeUrl() {
  const p = new URLSearchParams();
  if (state.q) p.set('q', state.q);
  if (state.page > 1) p.set('page', String(state.page));
  if (state.view === 'customer' && state.customer) {
    p.set('view', 'customer');
    p.set('customer', state.customer);
  }
  const newUrl = p.toString() ? '/?' + p.toString() : '/';
  history.pushState({}, '', newUrl);
}

function renderHeader() {
  const u = window.__user;
  const badge = document.getElementById('role-badge');
  const adminLink = document.getElementById('admin-link');
  if (u) {
    badge.hidden = false;
    badge.textContent = u.role === 'admin' ? 'ผู้ดูแลระบบ (Admin)' : 'ผู้ดูข้อมูล (Viewer)';
    adminLink.hidden = u.role !== 'admin';
  }
}

async function loadKpis() {
  try {
    const stats = await api('/api/stats');
    if (stats) {
      document.getElementById('kpi-customers').textContent = Number(stats.customer_count || 0).toLocaleString('th-TH');
      document.getElementById('kpi-orders').textContent = Number(stats.order_count || 0).toLocaleString('th-TH');
      document.getElementById('kpi-items').textContent = Number(stats.product_count || 0).toLocaleString('th-TH') + ' รายการ';
      
      if (stats.last_import) {
        const d = new Date(stats.last_import);
        document.getElementById('kpi-last-import').textContent = d.toLocaleDateString('th-TH', {
          day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'
        });
      } else {
        document.getElementById('kpi-last-import').textContent = 'ยังไม่มีข้อมูล';
      }
    }
  } catch (err) {
    console.warn('Failed to load KPIs:', err);
  }
}

function getInitialLetter(name) {
  if (!name) return 'C';
  const clean = name.trim().replace(/^บริษัท\s*|^หจก\.\s*|^คุณ\s*/, '');
  return clean.charAt(0) || name.charAt(0) || 'C';
}

function renderSearchResults(data) {
  kpiBanner.hidden = false;
  searchSection.hidden = false;
  resultsMetaBar.hidden = false;

  if (!data || data.total === 0) {
    resultsCountEl.innerHTML = 'ไม่พบข้อมูลลูกค้า';
    resultsEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">🔍</div>
        <h3>ไม่พบผลการค้นหา</h3>
        <p>ลองตรวจสอบตัวสะกดชื่อลูกค้า</p>
      </div>`;
    paginationEl.hidden = true;
    return;
  }

  resultsCountEl.innerHTML = `พบลูกค้าทั้งหมด <strong>${Number(data.total).toLocaleString('th-TH')}</strong> ราย`;

  const cardsHtml = data.items.map((it) => {
    const vip = it.vip_groups && it.vip_groups.length 
      ? `<span class="vip-badge">⭐ VIP: ${escapeHtml(it.vip_groups.join(', '))}</span>` 
      : '';
    const initial = getInitialLetter(it.customer_name);

    return `
      <article class="customer-card" data-customer="${escapeHtml(it.customer_name)}" tabindex="0">
        <div class="cust-left">
          <div class="cust-avatar">${escapeHtml(initial)}</div>
          <div class="cust-details">
            <div class="cust-title-row">
              <span class="cust-name">${escapeHtml(it.customer_name)}</span>
              ${vip}
            </div>
            <div class="cust-meta">
              <span>📦 <strong>${Number(it.order_count).toLocaleString('th-TH')}</strong> คำสั่งซื้อ</span>
              <span>🏷️ <strong>${Number(it.product_count).toLocaleString('th-TH')}</strong> Item สินค้า</span>
              <span>🕒 สั่งซื้อล่าสุด: ${formatDate(it.last_expected)}</span>
            </div>
          </div>
        </div>
        <div class="cust-arrow">
          <span>ดูประวัติ</span> →
        </div>
      </article>
    `;
  }).join('');

  resultsEl.innerHTML = `<div class="customer-grid">${cardsHtml}</div>`;

  const pages = Math.max(1, Math.ceil(data.total / 50));
  paginationEl.hidden = pages <= 1;
  paginationEl.innerHTML = `
    <button class="btn btn-secondary btn-sm" id="prev-page" ${state.page <= 1 ? 'disabled' : ''}>← หน้าก่อนหน้า</button>
    <span class="page-info">หน้า ${state.page} จาก ${pages}</span>
    <button class="btn btn-secondary btn-sm" id="next-page" ${state.page >= pages ? 'disabled' : ''}>หน้าถัดไป →</button>
  `;

  document.querySelectorAll('.customer-card').forEach((c) => {
    c.addEventListener('click', () => openCustomerDetail(c.dataset.customer));
    c.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') openCustomerDetail(c.dataset.customer);
    });
  });

  const prevBtn = document.getElementById('prev-page');
  const nextBtn = document.getElementById('next-page');
  if (prevBtn) prevBtn.onclick = () => { if (state.page > 1) { state.page--; writeUrl(); doSearch(); window.scrollTo({ top: 380, behavior: 'smooth' }); } };
  if (nextBtn) nextBtn.onclick = () => { if (state.page < pages) { state.page++; writeUrl(); doSearch(); window.scrollTo({ top: 380, behavior: 'smooth' }); } };
}

async function doSearch() {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  params.set('direction', 'customer');
  params.set('page', String(state.page));

  resultsEl.innerHTML = skeleton(4);
  resultsMetaBar.hidden = true;

  try {
    const data = await api('/api/search?' + params.toString());
    renderSearchResults(data);
  } catch (err) {
    if (err.code === 'unauthorized') return;
    resultsEl.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">⚠️</div>
        <h3>ไม่สามารถโหลดข้อมูลได้</h3>
        <p>${escapeHtml(err.message || 'เกิดข้อผิดพลาดในการเชื่อมต่อ')}</p>
        <button class="btn btn-primary btn-sm" style="margin-top: 12px;" id="retry-btn">ลองใหม่อีกครั้ง</button>
      </div>`;
    document.getElementById('retry-btn')?.addEventListener('click', doSearch);
  }
}

async function openCustomerDetail(customerName) {
  state.view = 'customer';
  state.customer = customerName;
  state.orderFilterQuery = '';
  writeUrl();
  await renderCustomerDetail();
}

async function renderCustomerDetail() {
  kpiBanner.hidden = true;
  searchSection.hidden = true;
  resultsMetaBar.hidden = true;
  paginationEl.hidden = true;
  resultsEl.innerHTML = skeleton(3);
  window.scrollTo({ top: 0, behavior: 'smooth' });

  try {
    const d = await api('/api/customer?name=' + encodeURIComponent(state.customer));
    state.currentCustomerData = d;
    renderCustomerDetailView(d);
  } catch (err) {
    if (err.code === 'unauthorized') return;
    resultsEl.innerHTML = `
      <div class="empty-state">
        <h3>เกิดข้อผิดพลาด</h3>
        <p>${escapeHtml(err.message)}</p>
        <button class="btn btn-secondary" id="detail-back-btn">← กลับหน้ารายการลูกค้า</button>
      </div>`;
    document.getElementById('detail-back-btn')?.addEventListener('click', backToSearch);
  }
}

function renderCustomerDetailView(d) {
  const vipBadge = d.vip_groups && d.vip_groups.length
    ? `<span class="vip-badge">⭐ VIP: ${escapeHtml(d.vip_groups.join(', '))}</span>`
    : '';

  resultsEl.innerHTML = `
    <div class="detail-dashboard">
      <div class="detail-top-nav">
        <button class="btn btn-secondary" id="back-to-search-btn">
          <span>←</span> กลับไปค้นหาลูกค้า
        </button>
        <button class="btn btn-success" id="export-excel-btn">
          <span>📥</span> ส่งออกประวัติเป็น Excel (.xlsx)
        </button>
      </div>

      <!-- Customer Profile Card -->
      <div class="detail-profile-card">
        <div class="detail-profile-header">
          <div class="detail-title-group" style="display: flex; align-items: center; gap: 16px;">
            <div class="cust-avatar" style="width: 54px; height: 54px; font-size: 22px; border-radius: var(--radius-xl);">
              ${escapeHtml(getInitialLetter(d.customer_name))}
            </div>
            <div>
              <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <h2 style="font-size: 24px; font-weight: 800;">${escapeHtml(d.customer_name)}</h2>
                ${vipBadge}
              </div>
              <p style="color: var(--text-muted); font-size: 13.5px; margin-top: 4px;">ประวัติการซื้อและข้อมูลสินค้าที่เคยสั่งซื้อทั้งหมด</p>
            </div>
          </div>
        </div>

        <div class="detail-metrics-row">
          <div class="detail-metric-box">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span>คำสั่งซื้อสะสม</span>
              <span style="font-size: 19px;">📦</span>
            </div>
            <strong>${Number(d.order_count).toLocaleString('th-TH')} ครั้ง</strong>
          </div>
          <div class="detail-metric-box">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span>Item สินค้า</span>
              <span style="font-size: 19px;">🏷️</span>
            </div>
            <strong>${Number(d.product_count).toLocaleString('th-TH')} รายการ</strong>
          </div>
          <div class="detail-metric-box">
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span>วันที่สั่งซื้อล่าสุด</span>
              <span style="font-size: 19px;">🕒</span>
            </div>
            <strong>${formatDate(d.last_expected)}</strong>
          </div>
        </div>
      </div>

      <!-- Orders Data Table Card -->
      <div class="detail-table-card">
        <div class="table-toolbar">
          <div>
            <h3 style="font-size: 17px; margin-bottom: 4px;">ประวัติรายการสินค้าที่สั่งซื้อ (<span id="table-orders-count">${d.orders.length}</span> รายการ)</h3>
            <p style="color: var(--text-muted); font-size: 13px;">รายการสินค้าทั้งหมดที่ลูกค้าเคยสั่งซื้อ เรียงจากล่าสุด</p>
          </div>
          <input 
            type="search" 
            id="order-search-filter" 
            class="table-search-input" 
            placeholder="ค้นหาชื่อสินค้า, รหัสสินค้า, ออเดอร์..."
            value="${escapeHtml(state.orderFilterQuery)}"
          >
        </div>

        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width: 120px;">Store Code</th>
                <th style="width: 80px;">Dept</th>
                <th style="width: 80px;">Class</th>
                <th style="width: 130px;">Item Id</th>
                <th>Product Name</th>
                <th style="width: 130px;">Date</th>
              </tr>
            </thead>
            <tbody id="orders-tbody"></tbody>
          </table>
        </div>

        <div class="orders-pagination-bar" style="display: flex; align-items: center; justify-content: space-between; margin-top: 16px; flex-wrap: wrap; gap: 12px;">
          <div style="font-size: 13px; color: var(--text-muted);" id="orders-page-summary"></div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <button class="btn btn-secondary btn-sm" id="orders-prev-btn">← หน้าก่อนหน้า</button>
            <span style="font-size: 13px; font-weight: 600;" id="orders-page-info">หน้า 1 / 1</span>
            <button class="btn btn-secondary btn-sm" id="orders-next-btn">หน้าถัดไป →</button>
          </div>
        </div>
      </div>
    </div>
  `;

  // Bind detail events
  document.getElementById('back-to-search-btn').onclick = backToSearch;
  
  function updateOrdersTable() {
    const q = state.orderFilterQuery;
    const filtered = (d.orders || []).filter((o) => {
      if (!q) return true;
      const text = `${o.store_code || ''} ${o.dept ?? ''} ${o.class ?? ''} ${o.item_id || ''} ${o.product_name || ''} ${o.expected_from || ''}`.toLowerCase();
      return text.includes(q);
    });

    const total = filtered.length;
    const totalPages = Math.max(1, Math.ceil(total / state.orderPageSize));
    if (state.orderPage > totalPages) state.orderPage = totalPages;
    if (state.orderPage < 1) state.orderPage = 1;

    const start = (state.orderPage - 1) * state.orderPageSize;
    const end = Math.min(start + state.orderPageSize, total);
    const pageRows = filtered.slice(start, end);

    const tbody = document.getElementById('orders-tbody');
    if (!total) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; padding: 32px; color: var(--text-muted);">ไม่พบรายการที่ตรงกับคำค้นหา</td></tr>`;
    } else {
      tbody.innerHTML = pageRows.map((o) => `
        <tr>
          <td><span class="order-num-pill">${escapeHtml(o.store_code || '—')}</span></td>
          <td><span style="font-weight: 700; color: var(--text-main);">${escapeHtml(o.dept ?? '—')}</span></td>
          <td><span style="font-weight: 700; color: var(--text-main);">${escapeHtml(o.class ?? '—')}</span></td>
          <td><span style="font-family: monospace; font-size: 13px; font-weight: 700; color: var(--primary-600); background: var(--primary-50); padding: 3px 8px; border-radius: var(--radius-xs); border: 1px solid var(--primary-100);">${escapeHtml(o.item_id || '—')}</span></td>
          <td><strong style="color: var(--text-main); font-weight: 600;">${escapeHtml(o.product_name || '—')}</strong></td>
          <td><span style="color: var(--text-muted); font-size: 13px; font-weight: 500;">${formatDate(o.expected_from)}</span></td>
        </tr>
      `).join('');
    }

    document.getElementById('table-orders-count').textContent = total;
    document.getElementById('orders-page-summary').textContent = total > 0 
      ? `แสดง ${start + 1} - ${end} จากทั้งหมด ${total.toLocaleString('th-TH')} รายการ`
      : 'ไม่มีข้อมูล';
    document.getElementById('orders-page-info').textContent = `หน้า ${state.orderPage} จาก ${totalPages}`;
    document.getElementById('orders-prev-btn').disabled = state.orderPage <= 1;
    document.getElementById('orders-next-btn').disabled = state.orderPage >= totalPages;
  }

  const filterInput = document.getElementById('order-search-filter');
  filterInput.oninput = (e) => {
    state.orderFilterQuery = e.target.value.toLowerCase().trim();
    state.orderPage = 1;
    updateOrdersTable();
  };

  document.getElementById('orders-prev-btn').onclick = () => {
    if (state.orderPage > 1) {
      state.orderPage--;
      updateOrdersTable();
    }
  };

  document.getElementById('orders-next-btn').onclick = () => {
    state.orderPage++;
    updateOrdersTable();
  };

  updateOrdersTable();
  document.getElementById('export-excel-btn').onclick = () => exportToExcel(d);
}

function exportToExcel(customerData) {
  if (!window.XLSX) {
    toast('ระบบไม่พร้อมสำหรับการส่งออก Excel กรุณาลองใหม่', 'error');
    return;
  }

  try {
    const exportRows = (customerData.orders || []).map((o, idx) => ({
      'ลำดับ': idx + 1,
      'Store Code': o.store_code || '',
      'Dept': o.dept ?? '',
      'Class': o.class ?? '',
      'Item Id': o.item_id || '',
      'Product Name': o.product_name || '',
      'Date': o.expected_from ? String(o.expected_from) : '',
      'ชื่อลูกค้า': customerData.customer_name,
      'กลุ่มลูกค้า VIP': (customerData.vip_groups || []).join(', ')
    }));

    const worksheet = XLSX.utils.json_to_sheet(exportRows);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, 'ประวัติคำสั่งซื้อ');

    const cleanName = (customerData.customer_name || 'Customer').replace(/[/\\?%*:|"<>]/g, '_');
    const filename = `Orders_${cleanName}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(workbook, filename);
    toast('ส่งออกไฟล์ Excel สำเร็จแล้ว', 'success');
  } catch (err) {
    console.error('Export error:', err);
    toast('ส่งออกไฟล์ไม่สำเร็จ: ' + err.message, 'error');
  }
}

function backToSearch() {
  state.view = 'search';
  state.customer = '';
  writeUrl();
  kpiBanner.hidden = false;
  searchSection.hidden = false;
  doSearch();
}

function bindEvents() {
  searchInput.value = state.q;
  updateClearBtn();

  searchInput.addEventListener('input', (e) => {
    state.q = e.target.value.trim();
    state.page = 1;
    updateClearBtn();
    writeUrl();
    debouncedSearch();
  });

  searchClearBtn.addEventListener('click', () => {
    searchInput.value = '';
    state.q = '';
    state.page = 1;
    updateClearBtn();
    writeUrl();
    doSearch();
    searchInput.focus();
  });

  document.getElementById('logout-btn').addEventListener('click', async () => {
    await logout();
    window.location.href = '/login.html';
  });

  window.addEventListener('popstate', () => {
    readUrl();
    if (state.view === 'customer' && state.customer) {
      renderCustomerDetail();
    } else {
      kpiBanner.hidden = false;
      searchSection.hidden = false;
      searchInput.value = state.q;
      updateClearBtn();
      doSearch();
    }
  });
}

function updateClearBtn() {
  searchClearBtn.style.display = searchInput.value ? 'block' : 'none';
}

const debouncedSearch = debounce(() => doSearch(), 300);

async function init() {
  try {
    window.__user = await me();
    renderHeader();
  } catch (err) {
    window.location.href = '/login.html';
    return;
  }

  readUrl();
  bindEvents();
  loadKpis();

  if (state.view === 'customer' && state.customer) {
    renderCustomerDetail();
  } else {
    doSearch();
  }
}

init();
