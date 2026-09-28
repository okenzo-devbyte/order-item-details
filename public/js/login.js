import { api } from './api.js';
import { toast } from './ui.js';

const form = document.getElementById('login-form');
const errorEl = document.getElementById('form-error');
const submitBtn = document.getElementById('submit-btn');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  errorEl.hidden = true;
  submitBtn.disabled = true;
  submitBtn.textContent = 'กำลังเข้าสู่ระบบ…';
  try {
    await api('/api/auth/login', {
      method: 'POST',
      body: { username: form.username.value.trim(), password: form.password.value }
    });
    const next = new URLSearchParams(window.location.search).get('next') || '/';
    window.location.href = next;
  } catch (err) {
    errorEl.hidden = false;
    errorEl.textContent = err.message;
    toast(err.message);
    submitBtn.disabled = false;
    submitBtn.textContent = 'เข้าสู่ระบบ';
  }
});
