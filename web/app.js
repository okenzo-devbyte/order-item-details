const state = {
  user: null,
  mode: "auto",
  filters: {},
  cursor: null,
  query: "",
};

function cookie(name) {
  const match = document.cookie.match(
    new RegExp("(?:^|; )" + name + "=([^;]*)")
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function api(path, options = {}, retry = true) {
  const headers = options.headers || {};
  if (options.body) headers["Content-Type"] = "application/json";
  const csrf = cookie("csrf_token");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401 && retry && path !== "/api/v1/auth/refresh") {
    const refreshed = await fetch("/api/v1/auth/refresh", { method: "POST" });
    if (refreshed.ok) {
      return api(path, options, false);
    }
    showLogin();
    throw new Error("unauthenticated");
  }
  if (response.status === 401) {
    showLogin();
    throw new Error("unauthenticated");
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || "request failed");
  }
  if (response.status === 204) return null;
  return response.json();
}

function showLogin() {
  document.getElementById("login-view").hidden = false;
  document.getElementById("app-view").hidden = true;
}

function showApp(user) {
  state.user = user;
  document.getElementById("login-view").hidden = true;
  document.getElementById("app-view").hidden = false;
  document.getElementById("who").textContent = `${user.username} (${user.role})`;
  loadFilterOptions();
}

function renderResults(payload) {
  const container = document.getElementById("results");
  container.innerHTML = "";
  const customers = payload.customers || [];
  const products = payload.products || [];

  customers.forEach((customer) => {
    const card = document.createElement("div");
    card.className = "row";
    card.innerHTML =
      `<span class="title">${escapeHtml(customer.name)}</span>` +
      `<span class="meta">${escapeHtml(customer.order_count)} ออเดอร์ · ` +
      `${escapeHtml((customer.products || []).length)} สินค้า</span>`;
    container.appendChild(card);
    (customer.products || []).forEach((product) => {
      const line = document.createElement("div");
      line.className = "row sub";
      line.innerHTML =
        `<span>${escapeHtml(product.name)}</span>` +
        `<span class="meta">${escapeHtml(product.order_count)}× · ` +
        `${escapeHtml(product.last_date || "-")} · ` +
        `${escapeHtml((product.stores || []).join(", ") || "-")}</span>`;
      container.appendChild(line);
    });
  });

  products.forEach((product) => {
    const line = document.createElement("div");
    line.className = "row";
    line.innerHTML =
      `<span class="title">${escapeHtml(product.name)}</span>` +
      `<span class="meta">${escapeHtml(product.customer_count)} คน · ` +
      `${escapeHtml(product.order_count)} ออเดอร์ · ล่าสุด ` +
      `${escapeHtml(product.last_date || "-")}</span>`;
    container.appendChild(line);
  });

  if (!customers.length && !products.length) {
    container.innerHTML = '<p class="note">ไม่พบผลลัพธ์</p>';
  }
  state.cursor = payload.next_cursor || null;
}

async function runSearch(query) {
  state.query = query;
  const payload = await api("/api/v1/search", {
    method: "POST",
    body: JSON.stringify({
      q: query,
      mode: state.mode,
      filters: state.filters,
      limit: 20,
    }),
  });
  renderResults(payload);
}

let suggestTimer = null;
function scheduleSuggest(query) {
  clearTimeout(suggestTimer);
  if (query.trim().length < 2) {
    hideSuggestions();
    return;
  }
  suggestTimer = setTimeout(async () => {
    try {
      const payload = await api("/api/v1/suggest", {
        method: "POST",
        body: JSON.stringify({ q: query, limit: 8 }),
      });
      const list = document.getElementById("suggestions");
      list.innerHTML = "";
      (payload.suggestions || []).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item.name;
        li.addEventListener("click", () => {
          document.getElementById("search-input").value = item.name;
          hideSuggestions();
          runSearch(item.name);
        });
        list.appendChild(li);
      });
      list.hidden = !payload.suggestions.length;
    } catch (error) {
      hideSuggestions();
    }
  }, 250);
}

function hideSuggestions() {
  const list = document.getElementById("suggestions");
  list.hidden = true;
  list.innerHTML = "";
}

async function loadFilterOptions() {
  try {
    const facets = await api("/api/v1/filters");
    const fields = document.getElementById("filter-fields");
    fields.innerHTML = "";
    const groups = {
      store_code: "สาขา",
      order_type: "ประเภทออเดอร์",
      vip_group: "VIP",
      dept: "Dept",
    };
    Object.entries(groups).forEach(([key, label]) => {
      const wrapper = document.createElement("div");
      wrapper.innerHTML = `<label>${label}</label>`;
      const select = document.createElement("select");
      select.multiple = true;
      select.dataset.filterKey = key;
      (facets[key] || []).forEach((value) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = String(value);
        select.appendChild(option);
      });
      wrapper.appendChild(select);
      fields.appendChild(wrapper);
    });
    const dates = document.createElement("div");
    dates.innerHTML =
      '<label>จากวันที่</label><input type="date" id="filter-date-from">' +
      '<label>ถึงวันที่</label><input type="date" id="filter-date-to">';
    fields.appendChild(dates);
  } catch (error) {
    // Filters are a convenience; a failure here must not block search.
  }
}

function collectFilters() {
  const filters = {};
  document.querySelectorAll("[data-filter-key]").forEach((select) => {
    const values = Array.from(select.selectedOptions).map((o) => o.value);
    if (values.length) filters[select.dataset.filterKey] = values;
  });
  const fromField = document.getElementById("filter-date-from");
  const toField = document.getElementById("filter-date-to");
  if (fromField && fromField.value) filters.date_from = fromField.value;
  if (toField && toField.value) filters.date_to = toField.value;
  return filters;
}

function init() {
  document.getElementById("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = document.getElementById("login-error");
    error.textContent = "";
    try {
      const user = await api("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value,
        }),
      });
      showApp(user);
    } catch (loginError) {
      error.textContent = "เข้าสู่ระบบไม่สำเร็จ";
    }
  });

  document.getElementById("logout").addEventListener("click", async () => {
    await fetch("/api/v1/auth/logout", { method: "POST" });
    showLogin();
  });

  document.getElementById("search-form").addEventListener("submit", (event) => {
    event.preventDefault();
    hideSuggestions();
    runSearch(document.getElementById("search-input").value);
  });

  document.getElementById("search-input").addEventListener("input", (event) => {
    scheduleSuggest(event.target.value);
  });

  document.getElementById("clear-search").addEventListener("click", () => {
    document.getElementById("search-input").value = "";
    document.getElementById("results").innerHTML = "";
    hideSuggestions();
  });

  document.getElementById("mode-chips").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button) return;
    state.mode = button.dataset.mode;
    document
      .querySelectorAll("#mode-chips .chip[data-mode]")
      .forEach((chip) => chip.classList.toggle("active", chip === button));
  });

  document.getElementById("open-filters").addEventListener("click", () => {
    document.getElementById("filter-sheet").hidden = false;
  });

  document.getElementById("apply-filters").addEventListener("click", () => {
    state.filters = collectFilters();
    document.getElementById("filter-sheet").hidden = true;
  });

  document.getElementById("clear-filters").addEventListener("click", () => {
    document.querySelectorAll("[data-filter-key]").forEach((select) => {
      select.selectedIndex = -1;
    });
    const fromField = document.getElementById("filter-date-from");
    const toField = document.getElementById("filter-date-to");
    if (fromField) fromField.value = "";
    if (toField) toField.value = "";
    state.filters = {};
  });

  api("/api/v1/auth/me")
    .then(showApp)
    .catch(() => showLogin());

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

init();
