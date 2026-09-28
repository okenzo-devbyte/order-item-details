import { api, me, logout } from './api.js';
import { toast, escapeHtml, debounce, skeleton, formatDate } from './ui.js';

const state = {
  q: '', dir: 'customer', dept: '', cls: '', subclass: '', page: 1,
  view: 'search', // 'search' | 'customer' | 'product'
  customer: '', item: ''
};

const resultsEl = document.getElementById('results');
const searchInput = document.getElementById('search-input');
const paginationEl = document.getElementById('pagination');

function readUrl() {
  const p = new URLSearchParams(window.location.search);
  state.q = p.get('q') || '';
  state.dir = p.get('dir') === 'product' ? 'product' : 'customer';
  state.dept = p.get('dept') || '';
  state.cls = p.get('class') || '';
  state.subclass = p.get('subclass') || '';
  state.page = Number(p.get('page') || '1');
  state.view = p.get('view') || 'search';
  state.customer = p.get('customer') || '';
  state.item = p.get('item') || '';
}

function writeUrl() {
  const p = new URLSearchParams();
  if (state.q) p.set('q', state.q);
  p.set('dir', state.dir);
  if (state.dept) p.set('dept', state.dept);
  if (state.cls) p.set('class', state.cls);
  if (state.subclass) p.set('subclass', state.subclass);
  if (state.page > 1) p.set('page', String(state.page));
  if (state.view !== 'search') p.set('view', state.view);
  if (state.view === 'customer' && state.customer) p.set('customer', state.customer);
  if (state.view === 'product' && state.item) p.set('item', state.item);
  history.pushState({}, '', '/?' + p.toString());
}

function renderHeader() {
  const u = window.__user;
  const badge = document.getElementById('role-badge');
  const adminLink = document.getElementById('admin-link');
  if (u) {
    badge.hidden = false;
    badge.textContent = u.role === 'admin' ? 'ผู้ดูแล' : 'ผู้ดู';
    adminLink.hidden = u.role !== 'admin';
  }
}

async function loadFilters() {
  const params = new URLSearchParams();
  if (state.dept) params.set('dept', state.dept);
  if (state.cls) params.set('class', state.cls);
  const data = await api('/api/filters?' + params.toString());
  fillSelect('f-dept', data.depts, state.dept, 'ทุกฝ่าย (Dept)');
  fillSelect('f-class', data.classes, state.cls, 'ทุกกลุ่ม (Class)');
  fillSelect('f-subclass', data.subclasses, state.subclass, 'ทุกประเภทย่อย (Subclass)');
}

function fillSelect(id, values, current, placeholder) {
  const el = document.getElementById(id);
  el.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>` +
    values.map((v) => `<option value="${v}" ${String(v) === String(current) ? 'selected' : ''}>${v}</option>`).join('');
}

function groupBadges(groups) {
  return groups.map((g) => `<span class="chip">${g.dept}/${g.class}/${g.subclass} ×${g.count}</span>`).join('');
}

function renderSearchResults(data) {
  if (data.total === 0) {
    resultsEl.innerHTML = '<div class="empty"><div class="empty-icon">🔍</div><h2>ไม่พบผลลัพธ์</h2><p>ลองเปลี่ยนคำค้นหรือล้างตัวกรอง</p></div>';
    paginationEl.hidden = true;
    return;
  }
  const cards = data.items.map((it) => {
    if (state.dir === 'customer') {
      const vip = it.vip_groups.length ? `<span class="vip">⭐ ${escapeHtml(it.vip_groups.join(', '))}</span>` : '';
      return `<article class="card" data-customer="${escapeHtml(it.customer_name)}" tabindex="0">
        <div class="card-main">
          <h3>${escapeHtml(it.customer_name)}</h3>
          <div class="stats">${it.order_count} ออเดอร์ · ${it.product_count} กลุ่มสินค้า · ล่าสุด ${formatDate(it.last_expected)}</div>
          <div class="chips">${groupBadges(it.groups)}</div>
          ${vip}
        </div>
        <div class="card-arrow">→</div>
      </article>`;
    }
    return `<article class="card" data-item="${escapeHtml(it.item_id)}" tabindex="0">
      <div class="card-main">
        <h3>${escapeHtml(it.product_name)}</h3>
        <div class="stats">${it.order_count} ครั้ง · ${it.customer_count} ลูกค้า</div>
        <div class="chips">${groupBadges(it.groups)}</div>
      </div>
      <div class="card-arrow">→</div>
    </article>`;
  }).join('');
  resultsEl.innerHTML = cards;
  const pages = Math.max(1, Math.ceil(data.total / 50));
  paginationEl.hidden = pages <= 1;
  paginationEl.innerHTML = `<button class="btn btn-secondary btn-sm" id="prev-page" ${state.page <= 1 ? 'disabled' : ''}>ก่อนหน้า</button>
    <span>หน้า ${state.page} / ${pages}</span>
    <button class="btn btn-secondary btn-sm" id="next-page" ${state.page >= pages ? 'disabled' : ''}>หน้าถัดไป</button>`;
  document.querySelectorAll('.card').forEach((c) => c.addEventListener('click', () => openDetail(c)));
  document.querySelectorAll('.card').forEach((c) => c.addEventListener('keydown', (e) => { if (e.key === 'Enter') openDetail(c); }));
}

async function doSearch() {
  const params = new URLSearchParams();
  if (state.q) params.set('q', state.q);
  params.set('direction', state.dir);
  if (state.dept) params.set('dept', state.dept);
  if (state.cls) params.set('class', state.cls);
  if (state.subclass) params.set('subclass', state.subclass);
  params.set('page', String(state.page));
  resultsEl.innerHTML = skeleton(3);
  try {
    const data = await api('/api/search?' + params.toString());
    renderSearchResults(data);
  } catch (err) {
    if (err.code === 'unauthorized') return; // api() already redirects to login
    resultsEl.innerHTML = '<div class="empty"><h2>เชื่อมต่อไม่ได้</h2><button class="btn" id="retry-btn">ลองใหม่</button></div>';
    document.getElementById('retry-btn').addEventListener('click', doSearch);
  }
}

async function openDetail(card) {
  if (state.dir === 'customer') {
    state.view = 'customer';
    state.customer = card.dataset.customer;
  } else {
    state.view = 'product';
    state.item = card.dataset.item;
  }
  writeUrl();
  await renderDetail();
}

async function renderDetail() {
  resultsEl.innerHTML = skeleton(2);
  paginationEl.hidden = true;
  try {
    if (state.view === 'customer') {
      const d = await api('/api/customer?name=' + encodeURIComponent(state.customer));
      resultsEl.innerHTML = detailCustomer(d);
    } else {
      const d = await api('/api/product?item_id=' + encodeURIComponent(state.item));
      resultsEl.innerHTML = detailProduct(d);
    }
    document.getElementById('back-btn').addEventListener('click', () => {
      state.view = 'search';
      writeUrl();
      doSearch();
    });
  } catch (err) {
    if (err.code === 'unauthorized') return; // api() already redirects to login
    resultsEl.innerHTML = `<div class="empty"><h2>${escapeHtml(err.message)}</h2></div>`;
  }
}

function detailCustomer(d) {
  const rows = d.orders.map((o) => `<tr>
    <td>${escapeHtml(o.order_number)}</td>
    <td>${escapeHtml(o.product_name)}</td>
    <td>${formatDate(o.expected_from)}</td>
    <td>${o.dept}/${o.class}/${o.subclass}</td>
    <td>${escapeHtml(o.item_remark || '')}</td>
  </tr>`).join('');
  return `<div class="detail-head">
      <button class="btn btn-secondary btn-sm" id="back-btn">← กลับ</button>
      <h2>${escapeHtml(d.customer_name)}</h2>
      <div class="stats">${d.order_count} ออเดอร์ · ${d.product_count} กลุ่มสินค้า</div>
      <div class="chips">${groupBadges(d.groups)}</div>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>ออเดอร์</th><th>สินค้า</th><th>วันที่</th><th>กลุ่ม</th><th>หมายเหตุ</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function detailProduct(d) {
  const rows = d.customers.map((c) => `<tr><td>${escapeHtml(c)}</td></tr>`).join('');
  return `<div class="detail-head">
      <button class="btn btn-secondary btn-sm" id="back-btn">← กลับ</button>
      <h2>${escapeHtml(d.product_name)}</h2>
      <div class="stats">${d.order_count} ครั้ง · ${d.customer_count} ลูกค้า</div>
    </div>
    <div class="table-wrap"><table class="data-table">
      <thead><tr><th>ลูกค้า</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function bindEvents() {
  searchInput.value = state.q;
  document.querySelectorAll('.dir-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.dir === state.dir);
    b.setAttribute('aria-selected', String(b.dataset.dir === state.dir));
    b.addEventListener('click', () => { state.dir = b.dataset.dir; state.page = 1; state.view = 'search'; writeUrl(); syncInputs(); doSearch(); });
  });
  const onFilter = (key) => (e) => { state[key] = e.target.value; state.page = 1; writeUrl(); loadFilters().catch(() => toast('โหลดตัวกรองไม่ได้')); doSearch(); };
  document.getElementById('f-dept').addEventListener('change', onFilter('dept'));
  document.getElementById('f-class').addEventListener('change', onFilter('cls'));
  document.getElementById('f-subclass').addEventListener('change', onFilter('subclass'));
  document.getElementById('clear-filters').addEventListener('click', () => {
    state.dept = state.cls = state.subclass = '';
    state.page = 1;
    writeUrl();
    loadFilters().catch(() => {});
    doSearch();
  });
  document.getElementById('logout-btn').addEventListener('click', logout);
  const debounced = debounce(() => { state.q = searchInput.value.trim(); state.page = 1; state.view = 'search'; writeUrl(); doSearch(); });
  searchInput.addEventListener('input', debounced);
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { state.q = searchInput.value.trim(); state.page = 1; state.view = 'search'; writeUrl(); doSearch(); }
  });
  document.addEventListener('click', (e) => {
    if (e.target.id === 'prev-page') { state.page = Math.max(1, state.page - 1); writeUrl(); doSearch(); }
    if (e.target.id === 'next-page') { state.page++; writeUrl(); doSearch(); }
  });
}

function syncInputs() {
  searchInput.value = state.q;
  document.querySelectorAll('.dir-btn').forEach((b) => {
    b.classList.toggle('active', b.dataset.dir === state.dir);
    b.setAttribute('aria-selected', String(b.dataset.dir === state.dir));
  });
}

async function init() {
  readUrl();
  window.__user = await me();
  renderHeader();
  bindEvents();
  syncInputs();
  loadFilters().catch(() => {});
  if (state.view === 'customer' && state.customer) {
    await renderDetail();
  } else if (state.view === 'product' && state.item) {
    await renderDetail();
  } else if (state.q) {
    await doSearch();
  }
}

init();
