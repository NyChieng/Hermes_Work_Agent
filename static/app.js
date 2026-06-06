'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token:         sessionStorage.getItem('wa_token') || '',
  history:       [],   // [{role, content}] — max 12 entries
  currentMood:   'friend',
  tasks:         [],
  editing:       null,   // kept for backward compat (no longer used)
  sending:       false,
  activeTask:    null,   // task object currently shown in detail panel
  taskHistories: {},     // { [taskName]: [{role, content}] }
  taskSending:   false,
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
      card.addEventListener('click', () => openTaskDetail(t));
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

// ── Task Detail Panel ──────────────────────────────────────────────────────

const _STATUS_LABELS   = { todo: '⬜ Todo', in_progress: '🟡 进行中', done: '✅ 完成', blocked: '🔴 阻塞' };
const _PRIORITY_LABELS = { high: '🔴 高优', medium: '🟡 中优', low: '🔵 低优' };
const _STATUS_CYCLE    = ['todo', 'in_progress', 'done', 'blocked'];
const _PRIORITY_CYCLE  = ['low', 'medium', 'high'];

function openTaskDetail(task) {
  state.activeTask = task;

  document.getElementById('tdp-name').textContent = task.name;

  const sb = document.getElementById('tdp-status-badge');
  sb.dataset.status = task.status;
  sb.textContent = _STATUS_LABELS[task.status] || task.status;

  const pb = document.getElementById('tdp-priority-badge');
  pb.dataset.priority = task.priority;
  pb.textContent = _PRIORITY_LABELS[task.priority] || task.priority;

  document.querySelectorAll('.qa-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.status === task.status);
  });

  const tagsEl = document.getElementById('tdp-tags');
  tagsEl.innerHTML = '';
  (task.tags || '').split(',').map(t => t.trim()).filter(Boolean).forEach(tag => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.textContent = tag;
    tagsEl.appendChild(pill);
  });

  document.getElementById('tdp-notes').textContent = task.notes || '（无备注）';
  document.getElementById('tdp-meta').textContent  = task.updated ? `🕐 更新：${task.updated}` : '';

  const notionEl = document.getElementById('tdp-notion');
  if (task.notion_id) {
    const url = `https://www.notion.so/${task.notion_id.replace(/-/g, '')}`;
    notionEl.innerHTML = `🔗 Notion <a href="${url}" target="_blank">已同步</a>`;
  } else {
    notionEl.textContent = 'Notion：未同步';
  }

  const msgEl = document.getElementById('tdp-messages');
  msgEl.innerHTML = '';
  const hist = state.taskHistories[task.name] || [];
  hist.forEach(m => appendTaskMessage(m.role === 'user' ? 'user' : 'agent', m.content));

  document.getElementById('task-detail-panel').classList.remove('hidden');
  document.getElementById('app').classList.add('app-3col');
  document.getElementById('tdp-input').focus();
}

function closeTaskDetail() {
  document.getElementById('task-detail-panel').classList.add('hidden');
  document.getElementById('app').classList.remove('app-3col');
  state.activeTask = null;
}

document.getElementById('tdp-name').addEventListener('blur', async () => {
  if (!state.activeTask) return;
  const newName = document.getElementById('tdp-name').textContent.trim();
  if (!newName || newName === state.activeTask.name) return;
  try { await loadBoard(); } catch (e) { /* ignore */ }
});

document.getElementById('tdp-close-btn').addEventListener('click', closeTaskDetail);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeTaskDetail(); });

document.getElementById('tdp-archive-btn').addEventListener('click', async () => {
  if (!state.activeTask) return;
  if (!confirm(`归档任务「${state.activeTask.name}」？`)) return;
  try {
    await api.delete(`/api/tasks/${encodeURIComponent(state.activeTask.name)}`);
    closeTaskDetail();
    await Promise.all([loadBoard(), loadSummary()]);
    toast('已归档');
  } catch (e) { toast('归档失败: ' + e.message, 'error'); }
});

document.getElementById('tdp-status-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const idx  = _STATUS_CYCLE.indexOf(state.activeTask.status);
  const next = _STATUS_CYCLE[(idx + 1) % _STATUS_CYCLE.length];
  await _updateActiveTask({ status: next });
});

document.getElementById('tdp-priority-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const idx  = _PRIORITY_CYCLE.indexOf(state.activeTask.priority);
  const next = _PRIORITY_CYCLE[(idx + 1) % _PRIORITY_CYCLE.length];
  await _updateActiveTask({ priority: next });
});

document.querySelectorAll('.qa-btn').forEach(btn => {
  btn.addEventListener('click', () => _updateActiveTask({ status: btn.dataset.status }));
});

async function _updateActiveTask(patch) {
  if (!state.activeTask) return;
  try {
    const updated = await api.patch(
      `/api/tasks/${encodeURIComponent(state.activeTask.name)}`, patch
    );
    state.activeTask = { ...state.activeTask, ...updated };
    openTaskDetail(state.activeTask);
    await Promise.all([loadBoard(), loadSummary()]);
  } catch (e) { toast('更新失败: ' + e.message, 'error'); }
}

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

// ── Task-scoped chat ───────────────────────────────────────────────────────

function appendTaskMessage(role, text) {
  const el  = document.getElementById('tdp-messages');
  const div = document.createElement('div');
  div.className  = `msg ${role === 'user' ? 'user' : 'agent'}`;
  div.style.cssText = 'max-width:100%';
  const isAgent = role !== 'user';
  div.innerHTML = `
    ${isAgent ? '<span class="msg-avatar" style="font-size:16px">🤖</span>' : ''}
    <div class="msg-bubble" style="font-size:13px">${esc(text)}</div>
    ${!isAgent ? '<span class="msg-avatar" style="font-size:16px">🙂</span>' : ''}
  `;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return div.querySelector('.msg-bubble');
}

async function sendTaskMessage(text) {
  if (!text.trim() || state.taskSending || !state.activeTask) return;
  state.taskSending = true;

  const taskName = state.activeTask.name;
  const sendBtn  = document.getElementById('tdp-send-btn');
  const input    = document.getElementById('tdp-input');
  sendBtn.disabled = true;
  input.value      = '';
  input.style.height = 'auto';

  appendTaskMessage('user', text);

  // Typing dots
  const typingDiv = document.createElement('div');
  typingDiv.className = 'msg agent';
  typingDiv.id        = 'tdp-typing';
  typingDiv.innerHTML = '<span class="msg-avatar" style="font-size:16px">🤖</span>'
    + '<div class="typing-dots"><span></span><span></span><span></span></div>';
  document.getElementById('tdp-messages').appendChild(typingDiv);
  document.getElementById('tdp-messages').scrollTop = 99999;

  const history    = state.taskHistories[taskName] || [];
  let   agentBubble = null;
  let   fullReply   = '';

  try {
    const resp = await fetch(`/api/chat/task/${encodeURIComponent(taskName)}`, {
      method:  'POST',
      headers: { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text, history }),
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
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (raw === '[DONE]') break;
        try {
          const chunk = JSON.parse(raw);
          if (chunk.error) { toast(chunk.error, 'error'); break; }
          if (chunk.char !== undefined) {
            if (!agentBubble) {
              typingDiv.remove();
              agentBubble = appendTaskMessage('agent', '');
              agentBubble.innerHTML = '<span class="cursor"></span>';
            }
            fullReply += chunk.char;
            agentBubble.innerHTML = esc(fullReply) + '<span class="cursor"></span>';
            document.getElementById('tdp-messages').scrollTop = 99999;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    typingDiv.remove();
    toast('发送失败: ' + e.message, 'error');
  } finally {
    if (agentBubble) agentBubble.innerHTML = esc(fullReply);
    state.taskSending = false;
    sendBtn.disabled  = false;

    // Save to per-task history (keep last 12 messages)
    const hist = state.taskHistories[taskName] || [];
    hist.push({ role: 'user',      content: text });
    hist.push({ role: 'assistant', content: fullReply });
    state.taskHistories[taskName] = hist.slice(-12);

    // Refresh detail panel in case agent updated the task
    if (state.activeTask && state.activeTask.name === taskName) {
      try {
        const tasks = await api.get('/api/tasks?limit=200');
        const fresh = tasks.find(t => t.name === taskName);
        if (fresh) { state.activeTask = fresh; openTaskDetail(fresh); }
      } catch (_) {}
    }
    await Promise.all([loadBoard(), loadSummary()]);
  }
}

// Wire up task chat input
document.getElementById('tdp-send-btn').addEventListener('click', () => {
  sendTaskMessage(document.getElementById('tdp-input').value);
});
document.getElementById('tdp-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendTaskMessage(document.getElementById('tdp-input').value);
  }
});
document.getElementById('tdp-input').addEventListener('input', () => {
  const el = document.getElementById('tdp-input');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 80) + 'px';
});

// ── File upload ────────────────────────────────────────────────────────────

const _TEXT_EXTS = new Set([
  'txt', 'md', 'json', 'csv', 'py', 'js', 'ts', 'jsx', 'tsx',
  'html', 'css', 'xml', 'yaml', 'yml', 'toml', 'ini', 'sh', 'bat',
]);

async function uploadFile(file) {
  const ext      = (file.name.split('.').pop() || '').toLowerCase();
  let   content  = '';
  let   filename = file.name;

  if (ext === 'pdf') {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const r = await fetch('/api/upload', {
        method:  'POST',
        headers: { 'X-Auth-Token': state.token },
        body:    formData,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const data = await r.json();
      content  = data.content;
      filename = data.filename;
      if (data.truncated) toast('文件内容已截断至 8000 字符', 'info');
    } catch (e) {
      toast('文件读取失败: ' + e.message, 'error');
      return;
    }
  } else if (_TEXT_EXTS.has(ext) || file.type.startsWith('text/')) {
    content = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = e => resolve(e.target.result);
      reader.onerror = () => reject(new Error('读取失败'));
      reader.readAsText(file, 'utf-8');
    });
  } else {
    toast('不支持此格式，请上传文本文件或 PDF', 'error');
    return;
  }

  // Show collapsible file preview in chat
  const preview    = esc(content.slice(0, 300)) + (content.length > 300 ? '…' : '');
  const userBubble = appendMessage('user', `📎 ${filename}`);
  userBubble.insertAdjacentHTML('afterend', `
    <details class="file-block">
      <summary>📄 ${esc(filename)} (${content.length} 字符)</summary>
      <pre>${preview}</pre>
    </details>
  `);

  // Send content to agent (truncated to 8000 chars)
  await sendMessage(`[文件: ${filename}]\n${content.slice(0, 8000)}`);
}

// Wire up 📎 button
document.getElementById('file-btn').addEventListener('click', () => {
  document.getElementById('file-input').click();
});
document.getElementById('file-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) uploadFile(file);
  e.target.value = '';  // reset so same file can be re-uploaded
});

// Drag-and-drop onto chat panel
document.getElementById('chat-panel').addEventListener('dragover', e => {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
});
document.getElementById('chat-panel').addEventListener('drop', e => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});
