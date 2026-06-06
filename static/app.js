'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  token:         sessionStorage.getItem('wa_token') || '',
  history:       [],
  currentMood:   'friend',
  tasks:         [],
  sending:       false,
  activeTask:    null,
  taskHistories: {},
  taskSending:   false,
  ocrTasks:      [],   // draft tasks from OCR
};

// ── API ────────────────────────────────────────────────────────────────────
const api = {
  _h() { return { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' }; },
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

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity .3s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, 3000);
}

// ── Escape HTML ────────────────────────────────────────────────────────────
function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Deadline helpers ───────────────────────────────────────────────────────
function deadlineUrgency(dl) {
  if (!dl) return null;
  const now    = new Date(); now.setHours(0,0,0,0);
  const target = new Date(dl); target.setHours(0,0,0,0);
  const diff   = Math.round((target - now) / 86400000);
  if (diff < 0)   return { label: `逾期 ${-diff}天`, cls: 'overdue' };
  if (diff === 0) return { label: '今天截止',         cls: 'urgent'  };
  if (diff === 1) return { label: '明天截止',         cls: 'urgent'  };
  if (diff <= 3)  return { label: `${diff}天后`,      cls: 'soon'    };
  return            { label: `${diff}天后`,            cls: 'future'  };
}

function formatDeadlineShort(dl) {
  if (!dl) return '';
  const d = new Date(dl);
  return `${d.getMonth()+1}/${d.getDate()}`;
}

// ── Login ──────────────────────────────────────────────────────────────────
const $loginOverlay = document.getElementById('login-overlay');
const $pwdInput     = document.getElementById('pwd-input');
const $loginBtn     = document.getElementById('login-btn');
const $loginErr     = document.getElementById('login-err');
const $app          = document.getElementById('app');

async function doLogin() {
  const pw = $pwdInput.value.trim();
  if (!pw) return;
  try {
    const res = await fetch('/api/login', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ password: pw }),
    });
    if (!res.ok) throw new Error('密码错误');
    state.token = pw;
    sessionStorage.setItem('wa_token', pw);
    $loginOverlay.classList.add('fade-out');
    setTimeout(() => {
      $loginOverlay.style.display = 'none';
      $app.classList.remove('hidden');
      initApp();
    }, 280);
  } catch (e) {
    $loginErr.textContent = e.message;
    $pwdInput.classList.add('shake');
    setTimeout(() => $pwdInput.classList.remove('shake'), 400);
  }
}
$loginBtn.addEventListener('click', doLogin);
$pwdInput.addEventListener('keydown', e => { if (e.key === 'Enter') doLogin(); });

if (state.token) {
  $loginOverlay.style.display = 'none';
  $app.classList.remove('hidden');
  initApp();
}

// ── App init ───────────────────────────────────────────────────────────────
async function initApp() {
  await Promise.all([loadSummary(), loadBoard(), loadMood(), loadNotionStatus()]);
}

// ── Summary ────────────────────────────────────────────────────────────────
async function loadSummary() {
  try {
    const s = await api.get('/api/summary');
    animateCount($('stat-total'),   s.total       || 0);
    animateCount($('stat-done'),    s.done        || 0);
    animateCount($('stat-wip'),     s.in_progress || 0);
    animateCount($('stat-blocked'), s.blocked     || 0);

    const total = s.total || 0;
    const done  = s.done  || 0;
    const pct   = total > 0 ? Math.round(done / total * 100) : 0;
    const fill  = document.getElementById('progress-fill');
    const pctEl = document.getElementById('progress-pct');
    if (fill)  fill.style.width  = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
  } catch (e) { toast('摘要加载失败', 'error'); }
}

function $(id) { return document.getElementById(id); }

function animateCount(el, target) {
  if (!el) return;
  let cur  = 0;
  const step = Math.max(1, Math.ceil(target / 18));
  const id   = setInterval(() => {
    cur = Math.min(cur + step, target);
    el.textContent = cur;
    if (cur >= target) clearInterval(id);
  }, 35);
}

// ── Board ──────────────────────────────────────────────────────────────────
async function loadBoard() {
  try {
    const tasks = await api.get('/api/tasks');
    state.tasks = tasks;
    renderBoard(tasks);
  } catch (e) { toast('任务加载失败', 'error'); }
}

function renderBoard(tasks) {
  const groups = { todo: [], in_progress: [], done: [], blocked: [] };
  tasks.forEach(t => { if (groups[t.status]) groups[t.status].push(t); });

  for (const [status, list] of Object.entries(groups)) {
    const body  = $('list-' + status);
    const count = $('cnt-'  + status);
    if (!body) continue;
    body.innerHTML = '';
    if (count) count.textContent = list.length;

    if (!list.length) {
      const empty = document.createElement('div');
      empty.className = 'col-empty';
      empty.textContent = '空的';
      body.appendChild(empty);
      continue;
    }

    list.forEach((t, i) => {
      const card = document.createElement('div');
      card.className = `task-card priority-${t.priority}`;
      card.style.animationDelay = `${i * 40}ms`;

      const urg = deadlineUrgency(t.deadline);
      const dlHtml = urg
        ? `<span class="deadline-tag ${urg.cls}">⏰ ${urg.label}</span>`
        : '';
      const notesHtml = t.notes
        ? `<span class="task-notes-snippet">${esc(t.notes)}</span>`
        : '';

      card.innerHTML = `
        <div class="task-name">${esc(t.name)}</div>
        <div class="task-footer">
          <span class="priority-pill ${t.priority}">${_PRIORITY_LABELS[t.priority] || t.priority}</span>
          ${notesHtml}
          ${dlHtml}
        </div>`;
      card.addEventListener('click', () => openTaskDetail(t));
      body.appendChild(card);
    });
  }
}

// ── Add task form ──────────────────────────────────────────────────────────
$('new-task-btn').addEventListener('click', () => {
  $('add-form').classList.toggle('hidden');
  $('new-name').focus();
});
$('add-cancel-btn').addEventListener('click', () => $('add-form').classList.add('hidden'));
$('add-submit-btn').addEventListener('click', async () => {
  const name     = $('new-name').value.trim();
  const priority = $('new-priority').value;
  const notes    = $('new-notes').value.trim();
  const deadline = $('new-deadline').value;
  if (!name) return;
  try {
    await api.post('/api/tasks', { name, priority, notes, deadline });
    $('new-name').value = $('new-notes').value = $('new-deadline').value = '';
    $('add-form').classList.add('hidden');
    await Promise.all([loadBoard(), loadSummary()]);
    toast(`已添加：${name}`, 'ok');
  } catch (e) { toast('添加失败: ' + e.message, 'error'); }
});

// ── Task detail panel ──────────────────────────────────────────────────────
const _STATUS_LABELS   = { todo:'⬜ Todo', in_progress:'🟡 进行中', done:'✅ 完成', blocked:'🔴 阻塞' };
const _PRIORITY_LABELS = { high:'🔴 高', medium:'🟡 中', low:'🔵 低' };
const _STATUS_CYCLE    = ['todo', 'in_progress', 'done', 'blocked'];
const _PRIORITY_CYCLE  = ['low', 'medium', 'high'];

function openTaskDetail(task) {
  state.activeTask = task;
  $('tdp-name').textContent = task.name;

  const sb = $('tdp-status-badge');
  sb.dataset.status = task.status;
  sb.textContent    = _STATUS_LABELS[task.status] || task.status;

  const pb = $('tdp-priority-badge');
  pb.dataset.priority = task.priority;
  pb.textContent      = _PRIORITY_LABELS[task.priority] || task.priority;

  // Deadline badge
  const dlInput = $('tdp-deadline-input');
  const dlBadge = $('tdp-deadline-badge');
  if (dlInput) dlInput.value = task.deadline || '';
  if (dlBadge) {
    const urg = deadlineUrgency(task.deadline);
    if (urg) {
      dlBadge.textContent = `⏰ ${urg.label}`;
      dlBadge.className   = `deadline-badge ${urg.cls}`;
    } else {
      dlBadge.className = 'deadline-badge hidden';
    }
  }

  document.querySelectorAll('.qa-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.status === task.status);
  });

  const tagsEl = $('tdp-tags');
  tagsEl.innerHTML = '';
  (task.tags || '').split(',').map(t => t.trim()).filter(Boolean).forEach(tag => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.textContent = tag;
    tagsEl.appendChild(pill);
  });

  const notesEl = $('tdp-notes');
  if (notesEl) notesEl.textContent = task.notes || '（暂无备注）';

  $('tdp-meta').textContent   = task.updated ? `🕐 ${task.updated}` : '';
  const notionEl = $('tdp-notion');
  if (task.notion_id) {
    const url = `https://www.notion.so/${task.notion_id.replace(/-/g,'')}`;
    notionEl.innerHTML = `🔗 Notion <a href="${url}" target="_blank">已同步</a>`;
  } else {
    notionEl.textContent = 'Notion：未同步';
  }

  const msgEl = $('tdp-messages');
  msgEl.innerHTML = '';
  (state.taskHistories[task.name] || []).forEach(m =>
    appendTaskMessage(m.role === 'user' ? 'user' : 'agent', m.content)
  );

  $('task-detail-panel').classList.remove('hidden');
  $('app').classList.add('app-3col');
  $('tdp-input').focus();
}

function closeTaskDetail() {
  $('task-detail-panel').classList.add('hidden');
  $('app').classList.remove('app-3col');
  state.activeTask = null;
}

$('tdp-close-btn').addEventListener('click', closeTaskDetail);
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeTaskDetail(); });

$('tdp-archive-btn').addEventListener('click', async () => {
  if (!state.activeTask) return;
  if (!confirm(`归档任务「${state.activeTask.name}」？`)) return;
  try {
    await api.delete(`/api/tasks/${encodeURIComponent(state.activeTask.name)}`);
    closeTaskDetail();
    await Promise.all([loadBoard(), loadSummary()]);
    toast('已归档', 'ok');
  } catch (e) { toast('归档失败: ' + e.message, 'error'); }
});

$('tdp-status-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const idx  = _STATUS_CYCLE.indexOf(state.activeTask.status);
  const next = _STATUS_CYCLE[(idx + 1) % _STATUS_CYCLE.length];
  await _updateActiveTask({ status: next });
});

$('tdp-priority-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const idx  = _PRIORITY_CYCLE.indexOf(state.activeTask.priority);
  const next = _PRIORITY_CYCLE[(idx + 1) % _PRIORITY_CYCLE.length];
  await _updateActiveTask({ priority: next });
});

document.querySelectorAll('.qa-btn').forEach(btn => {
  btn.addEventListener('click', () => _updateActiveTask({ status: btn.dataset.status }));
});

// Save deadline on change
const tdpDeadlineInput = $('tdp-deadline-input');
if (tdpDeadlineInput) {
  tdpDeadlineInput.addEventListener('change', async () => {
    if (!state.activeTask) return;
    await _updateActiveTask({ deadline: tdpDeadlineInput.value });
  });
}

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
  } catch (_) {}
}

function setMoodUI(mode, label) {
  state.currentMood = mode;
  $('mood-label').textContent = label || mode;
  document.querySelectorAll('.persona-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mood === mode);
  });
  const avatar = $('agent-avatar');
  avatar.classList.add('pulse');
  setTimeout(() => avatar.classList.remove('pulse'), 400);
}

document.querySelectorAll('.persona-btn').forEach(btn => {
  btn.addEventListener('click', async () => {
    try {
      const res    = await api.post(`/api/mood/${btn.dataset.mood}`);
      const labels = { friend:'😏 损友模式', drill:'🪖 军训教官模式', boss:'😔 怨念上司模式' };
      setMoodUI(btn.dataset.mood, labels[btn.dataset.mood]);
      toast(res.message || '人格已切换', 'ok');
    } catch (e) { toast('切换失败: ' + e.message, 'error'); }
  });
});

// ── Notion status ──────────────────────────────────────────────────────────
async function loadNotionStatus() {
  try {
    const n   = await api.get('/api/notion/status');
    const dot = $('notion-dot') || $('notion-status');
    const lbl = $('notion-label');
    if (n.configured) {
      if (dot) { dot.className = 'notion-dot connected'; }
      if (lbl) lbl.innerHTML = `<a href="${n.url}" target="_blank" style="color:inherit;text-decoration:none">Notion 已连接</a>`;
    }
  } catch (_) {}
}

$('sync-btn').addEventListener('click', async () => {
  const icon = $('sync-icon');
  icon.style.display = 'inline-block';
  icon.style.animation = 'spin .8s linear infinite';
  try {
    const r = await api.post('/api/notion/sync');
    toast(`同步完成 ↑${r.pushed} ↓${r.pulled}`, 'ok');
  } catch (e) { toast('同步失败: ' + e.message, 'error'); }
  finally {
    icon.style.animation = '';
    icon.textContent = '⟳';
    await Promise.all([loadBoard(), loadSummary()]);
  }
});

// ── Weekly report button ───────────────────────────────────────────────────
$('weekly-btn').addEventListener('click', async () => {
  $('weekly-btn').textContent = '⏳ 生成中…';
  $('weekly-btn').disabled    = true;
  try {
    const r = await api.post('/api/weekly');
    appendMessage('agent', r.report || '周报生成失败');
  } catch (e) { toast('周报生成失败: ' + e.message, 'error'); }
  finally {
    $('weekly-btn').textContent = '📋 周报';
    $('weekly-btn').disabled    = false;
  }
});

// ── Chat ───────────────────────────────────────────────────────────────────
const $messages  = $('messages');
const $chatInput = $('chat-input');
const $sendBtn   = $('send-btn');
const $sendIcon  = $('send-icon');

function appendMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const isAgent = role === 'agent';
  const avatar  = isAgent ? '⚡' : '🙂';
  div.innerHTML = `
    ${isAgent ? `<span class="msg-avatar">${avatar}</span>` : ''}
    <div class="msg-bubble">${esc(text)}</div>
    ${!isAgent ? `<span class="msg-avatar">${avatar}</span>` : ''}
  `;
  $messages.appendChild(div);
  $messages.scrollTop = $messages.scrollHeight;
  return div.querySelector('.msg-bubble');
}

function appendTypingDots() {
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.id = 'typing-indicator';
  div.innerHTML = `<span class="msg-avatar">⚡</span>
    <div class="typing-dots"><span></span><span></span><span></span></div>`;
  $messages.appendChild(div);
  $messages.scrollTop = $messages.scrollHeight;
  return div;
}

async function sendMessage(text) {
  if (!text.trim() || state.sending) return;
  state.sending = true;
  $sendBtn.disabled    = true;
  $sendIcon.className  = 'spin';
  $sendIcon.textContent = '↻';

  appendMessage('user', text);
  $chatInput.value = '';
  $chatInput.style.height = 'auto';

  const typingEl   = appendTypingDots();
  let   agentBubble = null;
  let   fullReply   = '';

  try {
    const resp = await fetch('/api/chat', {
      method:  'POST',
      headers: { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' },
      body:    JSON.stringify({ message: text, history: state.history }),
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
              typingEl.remove();
              agentBubble = appendMessage('agent', '');
              agentBubble.innerHTML = '<span class="cursor"></span>';
            }
            fullReply += chunk.char;
            agentBubble.innerHTML = esc(fullReply) + '<span class="cursor"></span>';
            $messages.scrollTop = $messages.scrollHeight;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    typingEl.remove();
    toast('发送失败: ' + e.message, 'error');
  } finally {
    if (agentBubble) agentBubble.innerHTML = esc(fullReply);
    state.sending = false;
    $sendBtn.disabled = false;
    $sendIcon.className = ''; $sendIcon.textContent = '↑';
    state.history.push({ role: 'user',      content: text });
    state.history.push({ role: 'assistant', content: fullReply });
    if (state.history.length > 12) state.history = state.history.slice(-12);
    loadBoard();
    loadSummary();
  }
}

$sendBtn.addEventListener('click', () => sendMessage($chatInput.value));
$chatInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage($chatInput.value); }
});
$chatInput.addEventListener('input', () => {
  $chatInput.style.height = 'auto';
  $chatInput.style.height = Math.min($chatInput.scrollHeight, 120) + 'px';
});

document.querySelectorAll('.chip').forEach(btn => {
  btn.addEventListener('click', () => sendMessage(btn.dataset.msg));
});

// ── Task-scoped chat ───────────────────────────────────────────────────────
function appendTaskMessage(role, text) {
  const el  = $('tdp-messages');
  const div = document.createElement('div');
  div.className = `msg ${role === 'user' ? 'user' : 'agent'}`;
  div.style.maxWidth = '100%';
  const isAgent = role !== 'user';
  div.innerHTML = `
    ${isAgent ? '<span class="msg-avatar" style="font-size:15px">⚡</span>' : ''}
    <div class="msg-bubble" style="font-size:12.5px">${esc(text)}</div>
    ${!isAgent ? '<span class="msg-avatar" style="font-size:15px">🙂</span>' : ''}
  `;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return div.querySelector('.msg-bubble');
}

async function sendTaskMessage(text) {
  if (!text.trim() || state.taskSending || !state.activeTask) return;
  state.taskSending = true;

  const taskName = state.activeTask.name;
  const btn   = $('tdp-send-btn');
  const input = $('tdp-input');
  btn.disabled = true;
  input.value  = '';
  input.style.height = 'auto';

  appendTaskMessage('user', text);

  const typingDiv = document.createElement('div');
  typingDiv.className = 'msg agent';
  typingDiv.innerHTML = '<span class="msg-avatar" style="font-size:15px">⚡</span>'
    + '<div class="typing-dots"><span></span><span></span><span></span></div>';
  $('tdp-messages').appendChild(typingDiv);
  $('tdp-messages').scrollTop = 99999;

  const history     = state.taskHistories[taskName] || [];
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
            $('tdp-messages').scrollTop = 99999;
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
    btn.disabled      = false;

    const hist = state.taskHistories[taskName] || [];
    hist.push({ role: 'user',      content: text });
    hist.push({ role: 'assistant', content: fullReply });
    state.taskHistories[taskName] = hist.slice(-12);

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

$('tdp-send-btn').addEventListener('click', () => sendTaskMessage($('tdp-input').value));
$('tdp-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendTaskMessage($('tdp-input').value); }
});
$('tdp-input').addEventListener('input', () => {
  const el = $('tdp-input');
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 80) + 'px';
});

// ── File upload ────────────────────────────────────────────────────────────
const _TEXT_EXTS = new Set([
  'txt','md','json','csv','py','js','ts','jsx','tsx',
  'html','css','xml','yaml','yml','toml','ini','sh','bat',
]);

async function uploadTextFile(file) {
  const ext     = (file.name.split('.').pop() || '').toLowerCase();
  let   content = '';
  let   filename = file.name;

  if (ext === 'pdf') {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const r = await fetch('/api/upload', {
        method: 'POST', headers: { 'X-Auth-Token': state.token }, body: formData,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const data = await r.json();
      content  = data.content;
      filename = data.filename;
      if (data.truncated) toast('文件内容已截断至 8000 字符');
    } catch (e) { toast('文件读取失败: ' + e.message, 'error'); return; }
  } else if (_TEXT_EXTS.has(ext) || file.type.startsWith('text/')) {
    content = await new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload  = e => resolve(e.target.result);
      r.onerror = () => reject(new Error('读取失败'));
      r.readAsText(file, 'utf-8');
    });
  } else {
    toast('不支持此格式，请上传文本文件或 PDF', 'error');
    return;
  }

  const preview    = esc(content.slice(0, 300)) + (content.length > 300 ? '…' : '');
  const userBubble = appendMessage('user', `📎 ${filename}`);
  userBubble.insertAdjacentHTML('afterend', `
    <details class="file-block">
      <summary>📄 ${esc(filename)} (${content.length} 字)</summary>
      <pre>${preview}</pre>
    </details>
  `);
  await sendMessage(`[文件: ${filename}]\n${content.slice(0, 8000)}`);
}

$('file-btn').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) uploadTextFile(file);
  e.target.value = '';
});

// ── OCR image upload ───────────────────────────────────────────────────────
$('ocr-btn').addEventListener('click', () => $('img-input').click());
$('img-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) runOcr(file);
  e.target.value = '';
});

// Drag image onto chat panel
$('chat-panel').addEventListener('dragover', e => {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'copy';
});
$('chat-panel').addEventListener('drop', e => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (!file) return;
  if (file.type.startsWith('image/')) {
    runOcr(file);
  } else {
    uploadTextFile(file);
  }
});

async function runOcr(file) {
  appendMessage('user', `📸 ${file.name}`);
  const typingEl = appendTypingDots();

  const formData = new FormData();
  formData.append('file', file);

  try {
    const r = await fetch('/api/ocr', {
      method:  'POST',
      headers: { 'X-Auth-Token': state.token },
      body:    formData,
    });
    typingEl.remove();

    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      appendMessage('agent', `识别失败：${err.detail || r.statusText}`);
      return;
    }

    const data = await r.json();
    if (!data.tasks || !data.tasks.length) {
      appendMessage('agent', '没有在图片中找到任务，换一张试试？');
      return;
    }

    state.ocrTasks = data.tasks;
    showOcrModal(data.tasks);
  } catch (e) {
    typingEl.remove();
    toast('OCR 失败: ' + e.message, 'error');
  }
}

function showOcrModal(tasks) {
  const modal   = $('ocr-modal');
  const list    = $('ocr-task-list');
  list.innerHTML = '';

  tasks.forEach((t, i) => {
    const priorityEmoji = { high: '🔴', medium: '🟡', low: '🔵' }[t.priority] || '🟡';
    const dlText = t.deadline ? `⏰ ${t.deadline}` : '';
    const item   = document.createElement('div');
    item.className = 'ocr-task-item';
    item.innerHTML = `
      <input type="checkbox" checked data-idx="${i}" />
      <div class="ocr-task-body">
        <div class="ocr-task-name">${esc(t.name)}</div>
        <div class="ocr-task-meta">
          <span class="priority-pill ${t.priority}">${priorityEmoji} ${t.priority}</span>
          ${dlText ? `<span class="deadline-tag soon">${esc(dlText)}</span>` : ''}
        </div>
        ${t.notes ? `<div class="ocr-task-notes">${esc(t.notes)}</div>` : ''}
      </div>
    `;
    list.appendChild(item);
  });

  modal.classList.remove('hidden');
}

$('ocr-modal-close').addEventListener('click', () => {
  $('ocr-modal').classList.add('hidden');
  state.ocrTasks = [];
});
$('ocr-cancel-btn').addEventListener('click', () => {
  $('ocr-modal').classList.add('hidden');
  state.ocrTasks = [];
  appendMessage('agent', '已取消，没有创建任何任务。');
});
$('ocr-confirm-btn').addEventListener('click', async () => {
  const checkboxes = $('ocr-task-list').querySelectorAll('input[type=checkbox]:checked');
  const indices    = Array.from(checkboxes).map(cb => parseInt(cb.dataset.idx));
  const selected   = indices.map(i => state.ocrTasks[i]).filter(Boolean);

  if (!selected.length) { toast('没有选中任何任务', 'error'); return; }

  $('ocr-confirm-btn').textContent = '创建中…';
  $('ocr-confirm-btn').disabled    = true;

  let created = 0;
  for (const t of selected) {
    try {
      await api.post('/api/tasks', {
        name:     t.name,
        priority: t.priority,
        notes:    t.notes || '',
        deadline: t.deadline || '',
      });
      created++;
    } catch (_) {}
  }

  $('ocr-modal').classList.add('hidden');
  $('ocr-confirm-btn').textContent = '全部创建';
  $('ocr-confirm-btn').disabled    = false;
  state.ocrTasks = [];

  appendMessage('agent', `✅ 已创建 ${created} 个任务。`);
  await Promise.all([loadBoard(), loadSummary()]);
});

// ── Export ─────────────────────────────────────────────────────────────────
function exportTasks(format) {
  const url  = `/api/export/${format}?_t=${encodeURIComponent(state.token)}`;
  const link = document.createElement('a');
  link.href  = url;
  link.setAttribute('download', format === 'csv' ? 'tasks.csv' : 'tasks.md');
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

$('export-btn').addEventListener('click', e => {
  e.stopPropagation();
  $('export-dropdown').classList.toggle('hidden');
});
$('export-csv-btn').addEventListener('click', () => {
  $('export-dropdown').classList.add('hidden');
  exportTasks('csv');
});
$('export-md-btn').addEventListener('click', () => {
  $('export-dropdown').classList.add('hidden');
  exportTasks('md');
});
document.addEventListener('click', () => $('export-dropdown').classList.add('hidden'));
