'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token:       sessionStorage.getItem('wa_token') || '',
  history:     [],   // [{role, content}] — max 12 entries
  currentMood: 'friend',
  tasks:       [],
  editing:     null, // task name being edited
  sending:     false,
};

// ── API helpers ────────────────────────────────────────────────────────────
const api = {
  _h() {
    return { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' };
  },
  async get(url) {
    const r = await fetch(url, { headers: this._h() });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async post(url, body = {}) {
    const r = await fetch(url, { method: 'POST', headers: this._h(), body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async patch(url, body = {}) {
    const r = await fetch(url, { method: 'PATCH', headers: this._h(), body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  async delete(url) {
    const r = await fetch(url, { method: 'DELETE', headers: this._h() });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
};

// ── Toast notifications ────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.textContent = msg;
  el.style.cssText = `
    position:fixed; bottom:20px; right:20px; z-index:9999;
    padding:10px 18px; border-radius:8px; font-size:13px;
    background:${type === 'error' ? '#7f1d1d' : '#1e3a5f'};
    border:1px solid ${type === 'error' ? '#ef4444' : '#3b82f6'};
    color:#fff; animation:fadeIn .3s ease; box-shadow:0 4px 12px #0006;
  `;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

// ── Login ──────────────────────────────────────────────────────────────────
const loginOverlay = document.getElementById('login-overlay');
const pwdInput     = document.getElementById('pwd-input');
const loginBtn     = document.getElementById('login-btn');
const loginErr     = document.getElementById('login-err');
const appEl        = document.getElementById('app');

async function doLogin() {
  const pw = pwdInput.value.trim();
  if (!pw) return;
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw }),
    });
    if (!res.ok) throw new Error('密码错误');
    state.token = pw;
    sessionStorage.setItem('wa_token', pw);
    loginOverlay.classList.add('fade-out');
    setTimeout(() => {
      loginOverlay.style.display = 'none';
      appEl.classList.remove('hidden');
      initApp();
    }, 300);
  } catch (e) {
    loginErr.textContent = e.message;
    pwdInput.classList.add('shake');
    setTimeout(() => pwdInput.classList.remove('shake'), 400);
  }
}

loginBtn.addEventListener('click', doLogin);
pwdInput.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

// Auto-login if token cached
if (state.token) {
  loginOverlay.style.display = 'none';
  appEl.classList.remove('hidden');
  initApp();
}

// ── App init ───────────────────────────────────────────────────────────────
async function initApp() {
  await Promise.all([loadSummary(), loadBoard(), loadMood(), loadNotionStatus()]);
}

// ── Summary stats ──────────────────────────────────────────────────────────
async function loadSummary() {
  try {
    const s = await api.get('/api/summary');
    animateCount(document.getElementById('stat-total'),   s.total       || 0);
    animateCount(document.getElementById('stat-done'),    s.done        || 0);
    animateCount(document.getElementById('stat-wip'),     s.in_progress || 0);
    animateCount(document.getElementById('stat-blocked'), s.blocked     || 0);
  } catch (e) { toast('摘要加载失败: ' + e.message, 'error'); }
}

function animateCount(el, target) {
  if (!el) return;
  let cur = 0;
  const step = Math.max(1, Math.ceil(target / 20));
  const id = setInterval(() => {
    cur = Math.min(cur + step, target);
    el.textContent = cur;
    if (cur >= target) clearInterval(id);
  }, 40);
}

// ── Task board ─────────────────────────────────────────────────────────────
async function loadBoard() {
  try {
    const tasks = await api.get('/api/tasks');
    state.tasks = tasks;
    renderBoard(tasks);
  } catch (e) { toast('任务加载失败: ' + e.message, 'error'); }
}

function renderBoard(tasks) {
  const groups = { todo: [], in_progress: [], done: [], blocked: [] };
  tasks.forEach(t => { if (groups[t.status]) groups[t.status].push(t); });

  for (const [status, list] of Object.entries(groups)) {
    const body  = document.getElementById('list-' + status);
    const count = document.getElementById('cnt-' + status);
    if (!body) continue;
    body.innerHTML = '';
    if (count) count.textContent = list.length;

    list.forEach((t, i) => {
      const card = document.createElement('div');
      card.className = 'task-card';
      card.style.animationDelay = `${i * 50}ms`;
      card.innerHTML = `
        <div class="task-name">${esc(t.name)}</div>
        <div class="task-meta">
          <span class="priority-dot ${t.priority}"></span>
          <span class="task-notes">${esc(t.notes || '')}</span>
        </div>`;
      card.addEventListener('click', () => openEdit(t));
      body.appendChild(card);
    });
  }
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── New task form ──────────────────────────────────────────────────────────
document.getElementById('new-task-btn').addEventListener('click', () => {
  document.getElementById('add-form').classList.toggle('hidden');
  document.getElementById('new-name').focus();
});
document.getElementById('add-cancel-btn').addEventListener('click', () => {
  document.getElementById('add-form').classList.add('hidden');
});
document.getElementById('add-submit-btn').addEventListener('click', async () => {
  const name     = document.getElementById('new-name').value.trim();
  const priority = document.getElementById('new-priority').value;
  const notes    = document.getElementById('new-notes').value.trim();
  if (!name) return;
  try {
    await api.post('/api/tasks', { name, priority, notes });
    document.getElementById('new-name').value  = '';
    document.getElementById('new-notes').value = '';
    document.getElementById('add-form').classList.add('hidden');
    await Promise.all([loadBoard(), loadSummary()]);
    toast(`已添加：${name}`);
  } catch (e) { toast('添加失败: ' + e.message, 'error'); }
});

// ── Edit sidebar ───────────────────────────────────────────────────────────
function openEdit(task) {
  state.editing = task.name;
  document.getElementById('edit-name').value    = task.name;
  document.getElementById('edit-status').value  = task.status;
  document.getElementById('edit-priority').value= task.priority;
  document.getElementById('edit-notes').value   = task.notes || '';
  document.getElementById('edit-sidebar').classList.remove('hidden');
}
document.getElementById('edit-close').addEventListener('click', () => {
  document.getElementById('edit-sidebar').classList.add('hidden');
});
document.getElementById('edit-save-btn').addEventListener('click', async () => {
  if (!state.editing) return;
  const status   = document.getElementById('edit-status').value;
  const priority = document.getElementById('edit-priority').value;
  const notes    = document.getElementById('edit-notes').value;
  try {
    await api.patch(`/api/tasks/${encodeURIComponent(state.editing)}`,
                    { status, priority, notes });
    document.getElementById('edit-sidebar').classList.add('hidden');
    await Promise.all([loadBoard(), loadSummary()]);
    toast('已保存');
  } catch (e) { toast('保存失败: ' + e.message, 'error'); }
});
document.getElementById('edit-delete-btn').addEventListener('click', async () => {
  if (!state.editing) return;
  if (!confirm(`归档任务「${state.editing}」？`)) return;
  try {
    await api.delete(`/api/tasks/${encodeURIComponent(state.editing)}`);
    document.getElementById('edit-sidebar').classList.add('hidden');
    await Promise.all([loadBoard(), loadSummary()]);
    toast('已归档');
  } catch (e) { toast('归档失败: ' + e.message, 'error'); }
});

// ── Mood switcher ──────────────────────────────────────────────────────────
async function loadMood() {
  try {
    const m = await api.get('/api/mood');
    setMoodUI(m.mode, m.label);
  } catch (e) { /* non-critical */ }
}

function setMoodUI(mode, label) {
  state.currentMood = mode;
  document.getElementById('mood-label').textContent = label || mode;
  document.querySelectorAll('.mood-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mood === mode);
  });
  const avatar = document.getElementById('agent-avatar');
  avatar.classList.add('pulse');
  setTimeout(() => avatar.classList.remove('pulse'), 400);
}

document.querySelectorAll('.mood-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    try {
      const res = await api.post(`/api/mood/${btn.dataset.mood}`);
      const labels = { friend: '😏 损友模式', drill: '🪖 军训教官模式', boss: '😔 怨念上司模式' };
      setMoodUI(btn.dataset.mood, labels[btn.dataset.mood]);
      toast(res.message || '人格已切换');
    } catch (e) { toast('切换失败: ' + e.message, 'error'); }
  });
});

// ── Notion status ──────────────────────────────────────────────────────────
async function loadNotionStatus() {
  try {
    const s = document.getElementById('notion-status');
    const n = await api.get('/api/notion/status');
    if (n.configured) {
      s.innerHTML = `🔗 <a href="${n.url}" target="_blank" style="color:inherit">Notion 已连接</a>`;
    } else {
      s.textContent = 'Notion 未配置';
    }
  } catch (e) { /* non-critical */ }
}

document.getElementById('sync-btn').addEventListener('click', async () => {
  const icon = document.getElementById('sync-icon');
  icon.className = 'sync-spinning'; icon.textContent = '↻';
  try {
    const r = await api.post('/api/notion/sync');
    toast(`同步完成 ↑${r.pushed} ↓${r.pulled}`);
  } catch (e) { toast('同步失败: ' + e.message, 'error'); }
  finally {
    icon.className = ''; icon.textContent = '🔄';
    await Promise.all([loadBoard(), loadSummary()]);
  }
});

// ── Chat ───────────────────────────────────────────────────────────────────
const messagesEl = document.getElementById('messages');
const chatInput  = document.getElementById('chat-input');
const sendBtn    = document.getElementById('send-btn');
const sendIcon   = document.getElementById('send-icon');

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const isAgent = role === 'agent';
  div.innerHTML = `
    ${isAgent ? '<span class="msg-avatar">🤖</span>' : ''}
    <div class="msg-bubble">${esc(text)}</div>
    ${role === 'user' ? '<span class="msg-avatar">🙂</span>' : ''}
  `;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div.querySelector('.msg-bubble');
}

function appendTypingDots() {
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'typing-indicator';
  div.innerHTML = `
    <span class="msg-avatar">🤖</span>
    <div class="typing-dots"><span></span><span></span><span></span></div>
  `;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return div;
}

async function sendMessage(text) {
  if (!text.trim() || state.sending) return;
  state.sending = true;
  sendBtn.disabled = true;
  sendIcon.className = 'spin'; sendIcon.textContent = '↻';

  appendMessage('user', text);
  chatInput.value = '';
  chatInput.style.height = 'auto';

  const typingEl = appendTypingDots();
  let agentBubble = null;
  let fullReply   = '';

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history: state.history }),
    });

    if (!resp.ok) throw new Error(`${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split('\n');
      buffer = lines.pop(); // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') break;
        try {
          const chunk = JSON.parse(raw);
          if (chunk.error) { toast(chunk.error, 'error'); break; }
          if (chunk.char !== undefined) {
            if (!agentBubble) {
              typingEl.remove();
              agentBubble = appendMessage('agent', '');
              agentBubble.innerHTML = '<span class="cursor"></span>';
            }
            fullReply += chunk.char;
            // Replace cursor with text + cursor
            agentBubble.innerHTML =
              esc(fullReply) + '<span class="cursor"></span>';
            messagesEl.scrollTop = messagesEl.scrollHeight;
          }
        } catch (_) { /* ignore parse errors */ }
      }
    }
  } catch (e) {
    typingEl.remove();
    toast('发送失败: ' + e.message, 'error');
  } finally {
    // Remove typing cursor
    if (agentBubble) agentBubble.innerHTML = esc(fullReply);
    state.sending = false;
    sendBtn.disabled = false;
    sendIcon.className = ''; sendIcon.textContent = '➤';

    // Update history (keep last 12)
    state.history.push({ role: 'user', content: text });
    state.history.push({ role: 'assistant', content: fullReply });
    if (state.history.length > 12) state.history = state.history.slice(-12);

    // Refresh board after any message (tasks may have changed)
    loadBoard();
    loadSummary();
  }
}

sendBtn.addEventListener('click', () => sendMessage(chatInput.value));
chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage(chatInput.value);
  }
});
// Auto-resize textarea
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
});

// Quick command buttons
document.querySelectorAll('.quick-btn').forEach(btn => {
  btn.addEventListener('click', () => sendMessage(btn.dataset.msg));
});
