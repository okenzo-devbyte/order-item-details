export async function api(path, opts = {}) {
  const init = { ...opts, headers: { ...(opts.headers || {}) } };
  if (opts.body !== undefined && !(opts.body instanceof FormData)) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch {
    throw { code: 'network', message: 'เชื่อมต่อไม่ได้' };
  }
  let payload = {};
  try { payload = await res.json(); } catch { /* ignore */ }
  if (res.status === 401 && !path.startsWith('/api/auth/login')) {
    window.location.href = '/login.html?next=' + encodeURIComponent(window.location.pathname + window.location.search);
    throw { code: 'unauthorized', message: 'กรุณาเข้าสู่ระบบก่อน' };
  }
  if (!res.ok || !payload.ok) {
    const err = payload.error || { code: 'internal', message: 'เกิดข้อผิดพลาดในระบบ' };
    throw err;
  }
  return payload.data;
}

export async function me() {
  try {
    const data = await api('/api/auth/me');
    return data.user;
  } catch {
    return null;
  }
}

export async function logout() {
  try { await api('/api/auth/logout', { method: 'POST', body: {} }); } catch { /* ignore */ }
  window.location.href = '/login.html';
}
