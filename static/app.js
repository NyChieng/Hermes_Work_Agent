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
  ocrTasks:      [],
  pastedImage:   null,   // {file, previewUrl}
  searchQuery:   '',
};

// ── Utility ────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function now()  { const d = new Date(); return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}`; }

// ── API ────────────────────────────────────────────────────────────────────
const api = {
  _h() { return { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' }; },
  async get(url) {
    const r = await fetch(url, { headers: this._h() });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
  async post(url, body = {}) {
    const r = await fetch(url, { method:'POST', headers: this._h(), body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
  async patch(url, body = {}) {
    const r = await fetch(url, { method:'PATCH', headers: this._h(), body: JSON.stringify(body) });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
  async delete(url) {
    const r = await fetch(url, { method:'DELETE', headers: this._h() });
    if (!r.ok) throw new Error(`${r.status}`);
    return r.json();
  },
};

// ── Toast ──────────────────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.transition='opacity .3s'; el.style.opacity='0'; setTimeout(()=>el.remove(),300); }, 2800);
}

// ── Deadline helpers ───────────────────────────────────────────────────────
function dlUrgency(dl) {
  if (!dl) return null;
  const today  = new Date(); today.setHours(0,0,0,0);
  const target = new Date(dl); target.setHours(0,0,0,0);
  const d = Math.round((target - today) / 86400000);
  if (d < 0)   return { label: `逾期${-d}天`, cls: 'overdue' };
  if (d === 0) return { label: '今天',        cls: 'urgent' };
  if (d === 1) return { label: '明天',        cls: 'urgent' };
  if (d <= 3)  return { label: `${d}天后`,    cls: 'soon' };
  return              { label: `${d}天后`,    cls: 'future' };
}

// ── Login ──────────────────────────────────────────────────────────────────
async function doLogin() {
  const pw = $('pwd-input').value.trim();
  if (!pw) return;
  try {
    const r = await fetch('/api/login', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ password: pw }),
    });
    if (!r.ok) throw new Error('密码错误');
    state.token = pw;
    sessionStorage.setItem('wa_token', pw);
    const ov = $('login-overlay');
    ov.classList.add('fade-out');
    setTimeout(() => { ov.style.display='none'; $('app').classList.remove('hidden'); initApp(); }, 280);
  } catch (e) {
    $('login-err').textContent = e.message;
    const inp = $('pwd-input');
    inp.classList.add('shake');
    setTimeout(() => inp.classList.remove('shake'), 400);
  }
}
$('login-btn').addEventListener('click', doLogin);
$('pwd-input').addEventListener('keydown', e => { if (e.key==='Enter') doLogin(); });
if (state.token) { $('login-overlay').style.display='none'; $('app').classList.remove('hidden'); initApp(); }

// ── App init ───────────────────────────────────────────────────────────────
async function initApp() {
  initTheme();
  initResizablePanels();
  initSidebarCollapse();
  initKeyboardShortcuts();
  await Promise.all([loadSummary(), loadBoard(), loadMood(), loadNotionStatus()]);
}

// ── Theme toggle ───────────────────────────────────────────────────────────
function initTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  applyTheme(saved);
  $('theme-toggle-btn')?.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    applyTheme(current === 'dark' ? 'light' : 'dark');
  });
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
  const darkIcon  = $('theme-icon-dark');
  const lightIcon = $('theme-icon-light');
  if (darkIcon)  darkIcon.classList.toggle('hidden',  theme === 'light');
  if (lightIcon) lightIcon.classList.toggle('hidden', theme === 'dark');
}

// ── Resizable panels ───────────────────────────────────────────────────────
function initResizablePanels() {
  // Sidebar resize handle
  makeResizable({
    handle:    $('rz-sidebar'),
    target:    $('sidebar'),
    direction: 'right',
    min: 200, max: 520,
    storageKey: 'sidebar-w',
  });
  // Task detail resize handle (right panel — drag left = wider)
  makeResizable({
    handle:    $('rz-detail'),
    target:    $('task-detail-panel'),
    direction: 'left',
    min: 260, max: 540,
    storageKey: 'detail-w',
  });
  // Restore saved widths
  restoreWidth($('sidebar'),           'sidebar-w');
  restoreWidth($('task-detail-panel'), 'detail-w');
}

// Global safety: if window loses focus during drag, stop immediately
window.addEventListener('blur', () => {
  document.body.classList.remove('is-resizing');
  document.querySelectorAll('.resize-handle').forEach(h => h.classList.remove('active'));
});

function makeResizable({ handle, target, direction, min, max, storageKey }) {
  let dragging = false, startX, startW;

  const stopDrag = () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('is-resizing');
    handle.classList.remove('active');
    if (storageKey && target.style.width) localStorage.setItem(storageKey, target.style.width);
  };

  handle.addEventListener('mousedown', e => {
    dragging = true;
    startX   = e.clientX;
    startW   = target.getBoundingClientRect().width;
    document.body.classList.add('is-resizing');
    handle.classList.add('active');
    e.preventDefault();
  });

  handle.addEventListener('touchstart', e => {
    dragging = true;
    startX   = e.touches[0].clientX;
    startW   = target.getBoundingClientRect().width;
    document.body.classList.add('is-resizing');
    e.preventDefault();
  }, { passive: false });

  const onMove = (clientX) => {
    if (!dragging) return;
    const dx = direction === 'right' ? clientX - startX : startX - clientX;
    const w  = clamp(startW + dx, min, max);
    target.style.width    = w + 'px';
    target.style.minWidth = w + 'px';
    target.style.flex     = 'none';
  };

  document.addEventListener('mousemove', e => onMove(e.clientX));
  document.addEventListener('touchmove', e => onMove(e.touches[0].clientX), { passive: true });
  document.addEventListener('mouseup',   stopDrag);
  document.addEventListener('touchend',  stopDrag);

  // Double-click resets to default
  handle.addEventListener('dblclick', () => {
    target.style.width    = '';
    target.style.minWidth = '';
    target.style.flex     = '';
    if (storageKey) localStorage.removeItem(storageKey);
  });
}

function restoreWidth(el, key) {
  const saved = localStorage.getItem(key);
  if (saved && el) { el.style.width = saved; el.style.minWidth = saved; el.style.flex = 'none'; }
}

// ── Sidebar collapse ───────────────────────────────────────────────────────
function initSidebarCollapse() {
  $('sidebar-collapse-btn').addEventListener('click', toggleSidebar);
}
function toggleSidebar() {
  const s        = $('sidebar');
  const collapsed = s.classList.toggle('collapsed');
  $('sidebar-collapse-btn').textContent = collapsed ? '›' : '‹';
  $('rz-sidebar').style.display = collapsed ? 'none' : '';
  const tab = $('sidebar-tab');
  if (tab) tab.classList.toggle('visible', collapsed);
  localStorage.setItem('sidebar-collapsed', collapsed);
}
// Sidebar expand tab click
document.addEventListener('DOMContentLoaded', () => {
  $('sidebar-tab')?.addEventListener('click', toggleSidebar);
});
// Also wire immediately in case DOMContentLoaded already fired
$('sidebar-tab')?.addEventListener('click', toggleSidebar);

// Restore collapsed state
if (localStorage.getItem('sidebar-collapsed') === 'true') {
  setTimeout(() => {
    const s   = $('sidebar');
    const tab = $('sidebar-tab');
    if (s)   { s.classList.add('collapsed'); $('sidebar-collapse-btn').textContent = '›'; $('rz-sidebar').style.display = 'none'; }
    if (tab) tab.classList.add('visible');
  }, 0);
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────
function initKeyboardShortcuts() {
  document.addEventListener('keydown', e => {
    const tag = document.activeElement.tagName.toLowerCase();
    const editing = ['input','textarea'].includes(tag) || document.activeElement.isContentEditable;

    if (e.key === 'Escape') {
      if (state.searchQuery) { clearSearch(); return; }
      closeTaskDetail();
      closeModals();
      clearPastedImage();
      return;
    }
    if (editing) return;
    if (e.key === 'n' || e.key === 'N') { e.preventDefault(); openNewTaskForm(); }
    if (e.key === '/') { e.preventDefault(); $('search-input').focus(); }
    if (e.key === 'b' || e.key === 'B') { e.preventDefault(); toggleSidebar(); }
    if (e.key === '?') { e.preventDefault(); $('shortcuts-modal').classList.remove('hidden'); }
  });

  $('shortcuts-btn').addEventListener('click', () => $('shortcuts-modal').classList.remove('hidden'));
  $('shortcuts-close').addEventListener('click', () => $('shortcuts-modal').classList.add('hidden'));
}
function closeModals() {
  $('shortcuts-modal').classList.add('hidden');
  $('ocr-modal').classList.add('hidden');
}

// ── Summary ────────────────────────────────────────────────────────────────
async function loadSummary() {
  try {
    const s = await api.get('/api/summary');
    animCount($('stat-total'),   s.total       || 0);
    animCount($('stat-done'),    s.done        || 0);
    animCount($('stat-wip'),     s.in_progress || 0);
    animCount($('stat-blocked'), s.blocked     || 0);
    const pct   = s.total > 0 ? Math.round((s.done||0)/s.total*100) : 0;
    const fill  = $('progress-fill');
    const pctEl = $('progress-pct');
    if (fill)  fill.style.width  = pct + '%';
    if (pctEl) pctEl.textContent = pct + '%';
  } catch (_) {}
}
function animCount(el, target) {
  if (!el) return;
  let cur = 0;
  const step = Math.max(1, Math.ceil(target / 16));
  const id   = setInterval(() => { cur = Math.min(cur+step, target); el.textContent = cur; if(cur>=target) clearInterval(id); }, 32);
}

// ── Task board ─────────────────────────────────────────────────────────────
async function loadBoard() {
  try {
    const tasks = await api.get('/api/tasks');
    state.tasks = tasks;
    renderBoard(tasks, state.searchQuery);
  } catch (_) {}
}

function renderBoard(tasks, filter = '') {
  const q = filter.trim().toLowerCase();
  const filtered = q ? tasks.filter(t =>
    t.name.toLowerCase().includes(q) ||
    (t.notes||'').toLowerCase().includes(q) ||
    (t.tags||'').toLowerCase().includes(q)
  ) : tasks;

  const groups = { todo:[], in_progress:[], done:[], blocked:[] };
  filtered.forEach(t => { if (groups[t.status]) groups[t.status].push(t); });

  for (const [status, list] of Object.entries(groups)) {
    const body  = $('list-' + status);
    const count = $('cnt-'  + status);
    if (!body) continue;
    // Clear all but the add-hint
    Array.from(body.children).forEach(ch => { if (!ch.classList.contains('col-add-hint')) ch.remove(); });
    if (count) count.textContent = list.length;

    if (!list.length && !q) {
      // hint is already there as DOM node, ensure visible
      const hint = body.querySelector('.col-add-hint');
      if (hint) hint.style.display = '';
      continue;
    } else {
      const hint = body.querySelector('.col-add-hint');
      if (hint) hint.style.display = q ? 'none' : '';
    }

    list.forEach((t, i) => {
      const card = document.createElement('div');
      card.className = `task-card priority-${t.priority}`;
      card.style.animationDelay = `${i * 35}ms`;

      const urg    = dlUrgency(t.deadline);
      const dlHtml = urg ? `<span class="dl-tag ${urg.cls}">⏰ ${esc(urg.label)}</span>` : '';
      const noteHtml = t.notes ? `<span class="task-notes-snip">${esc(t.notes)}</span>` : '';
      const priorityLabels = { high:'高', medium:'中', low:'低' };

      card.innerHTML = `
        <div class="task-card-top">
          <div class="task-name">${esc(t.name)}</div>
          <button class="task-quick-done" title="标记完成" data-name="${esc(t.name)}">✓</button>
        </div>
        <div class="task-footer">
          <span class="p-pill ${t.priority}">${priorityLabels[t.priority]||t.priority}</span>
          ${noteHtml}
          ${dlHtml}
        </div>`;

      // Quick complete
      card.querySelector('.task-quick-done').addEventListener('click', async e => {
        e.stopPropagation();
        try {
          await api.patch(`/api/tasks/${encodeURIComponent(t.name)}`, { status: 'done' });
          await Promise.all([loadBoard(), loadSummary()]);
          toast('已完成 ✓', 'ok');
        } catch(err) { toast('操作失败', 'error'); }
      });

      card.addEventListener('click', () => openTaskDetail(t));
      body.insertBefore(card, body.querySelector('.col-add-hint'));
    });
  }
}

// ── Search ─────────────────────────────────────────────────────────────────
const $searchInput = $('search-input');
const $searchClear = $('search-clear');

$searchInput.addEventListener('input', () => {
  state.searchQuery = $searchInput.value;
  $searchClear.classList.toggle('hidden', !state.searchQuery);
  renderBoard(state.tasks, state.searchQuery);
});
$searchClear.addEventListener('click', clearSearch);
function clearSearch() {
  state.searchQuery = '';
  $searchInput.value = '';
  $searchClear.classList.add('hidden');
  renderBoard(state.tasks, '');
  $searchInput.blur();
}

// ── Column collapse ────────────────────────────────────────────────────────
document.querySelectorAll('.col-header').forEach(hd => {
  hd.addEventListener('click', () => hd.closest('.col').classList.toggle('collapsed'));
});

// ── Column quick-add hint ──────────────────────────────────────────────────
document.querySelectorAll('.col-add-hint').forEach(hint => {
  hint.addEventListener('click', () => {
    const status = hint.dataset.col;
    openNewTaskForm(status);
  });
});

// ── New task form ──────────────────────────────────────────────────────────
function openNewTaskForm(prefillStatus) {
  $('add-form').classList.remove('hidden');
  $('new-name').focus();
}
$('new-task-btn').addEventListener('click', () => openNewTaskForm());
$('add-cancel-btn').addEventListener('click', () => $('add-form').classList.add('hidden'));
$('add-submit-btn').addEventListener('click', submitNewTask);
$('new-name').addEventListener('keydown', e => { if (e.key==='Enter') submitNewTask(); });

async function submitNewTask() {
  const name     = $('new-name').value.trim();
  const priority = $('new-priority').value;
  const notes    = $('new-notes').value.trim();
  const deadline = $('new-deadline').value;
  if (!name) { $('new-name').focus(); return; }
  try {
    await api.post('/api/tasks', { name, priority, notes, deadline });
    $('new-name').value = $('new-notes').value = $('new-deadline').value = '';
    $('add-form').classList.add('hidden');
    await Promise.all([loadBoard(), loadSummary()]);
    toast(`已添加 "${name}"`, 'ok');
  } catch (e) { toast('添加失败: ' + e.message, 'error'); }
}

// ── Task detail panel ──────────────────────────────────────────────────────
const _STATUS_LABELS   = { todo:'⬜ Todo', in_progress:'🟡 进行中', done:'✅ 完成', blocked:'🔴 阻塞' };
const _PRIORITY_LABELS = { high:'🔴 高优', medium:'🟡 中优', low:'🔵 低优' };
const _STATUS_CYCLE    = ['todo','in_progress','done','blocked'];
const _PRIORITY_CYCLE  = ['low','medium','high'];

function openTaskDetail(task) {
  state.activeTask = task;

  $('tdp-name').textContent = task.name;
  const sb = $('tdp-status-badge');
  sb.dataset.status = task.status;
  sb.textContent    = _STATUS_LABELS[task.status] || task.status;

  const pb = $('tdp-priority-badge');
  pb.dataset.priority = task.priority;
  pb.textContent      = _PRIORITY_LABELS[task.priority] || task.priority;

  const dlInput = $('tdp-deadline-input');
  const dlBadge = $('tdp-deadline-badge');
  if (dlInput) dlInput.value = task.deadline || '';
  if (dlBadge) {
    const urg = dlUrgency(task.deadline);
    if (urg) { dlBadge.textContent = `⏰ ${urg.label}`; dlBadge.className = `deadline-badge ${urg.cls}`; }
    else     { dlBadge.className = 'deadline-badge hidden'; }
  }

  document.querySelectorAll('.qa-btn').forEach(b => b.classList.toggle('active', b.dataset.status===task.status));

  const tagsEl = $('tdp-tags');
  tagsEl.innerHTML = '';
  (task.tags||'').split(',').map(t=>t.trim()).filter(Boolean).forEach(tag => {
    const pill = document.createElement('span'); pill.className='tag-pill'; pill.textContent=tag;
    tagsEl.appendChild(pill);
  });

  $('tdp-notes').textContent = task.notes || '（暂无备注）';
  $('tdp-meta').textContent  = task.updated ? `🕐 ${task.updated}` : '';
  const nEl = $('tdp-notion');
  if (task.notion_id) {
    const url = `https://www.notion.so/${task.notion_id.replace(/-/g,'')}`;
    nEl.innerHTML = `🔗 Notion <a href="${url}" target="_blank">已同步</a>`;
  } else { nEl.textContent = 'Notion：未同步'; }

  const msgEl = $('tdp-messages');
  msgEl.innerHTML = '';
  (state.taskHistories[task.name]||[]).forEach(m => appendTaskMsg(m.role==='user'?'user':'agent', m.content));

  $('task-detail-panel').classList.remove('hidden');
  $('rz-detail').classList.remove('hidden');
  $('app').classList.add('app-3col');
  restoreWidth($('task-detail-panel'), 'detail-w');
  $('tdp-input').focus();
}

function closeTaskDetail() {
  $('task-detail-panel').classList.add('hidden');
  $('rz-detail').classList.add('hidden');
  $('app').classList.remove('app-3col');
  state.activeTask = null;
}

$('tdp-close-btn').addEventListener('click', closeTaskDetail);

$('tdp-archive-btn').addEventListener('click', async () => {
  if (!state.activeTask) return;
  if (!confirm(`归档「${state.activeTask.name}」？`)) return;
  try {
    await api.delete(`/api/tasks/${encodeURIComponent(state.activeTask.name)}`);
    closeTaskDetail();
    await Promise.all([loadBoard(), loadSummary()]);
    toast('已归档', 'ok');
  } catch (e) { toast('归档失败', 'error'); }
});

$('tdp-name').addEventListener('blur', async () => {
  if (!state.activeTask) return;
  // name edit is cosmetic; real edit needs backend rename support — skip silently
});

$('tdp-status-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const next = _STATUS_CYCLE[(_STATUS_CYCLE.indexOf(state.activeTask.status)+1) % _STATUS_CYCLE.length];
  await _patchActive({ status: next });
});
$('tdp-priority-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const next = _PRIORITY_CYCLE[(_PRIORITY_CYCLE.indexOf(state.activeTask.priority)+1) % _PRIORITY_CYCLE.length];
  await _patchActive({ priority: next });
});
document.querySelectorAll('.qa-btn').forEach(b => b.addEventListener('click', () => _patchActive({ status: b.dataset.status })));

$('tdp-deadline-input').addEventListener('change', async () => {
  if (!state.activeTask) return;
  await _patchActive({ deadline: $('tdp-deadline-input').value });
});

async function _patchActive(patch) {
  if (!state.activeTask) return;
  try {
    const updated = await api.patch(`/api/tasks/${encodeURIComponent(state.activeTask.name)}`, patch);
    state.activeTask = { ...state.activeTask, ...updated };
    openTaskDetail(state.activeTask);
    await Promise.all([loadBoard(), loadSummary()]);
  } catch (e) { toast('更新失败', 'error'); }
}

// ── Mood ───────────────────────────────────────────────────────────────────
async function loadMood() {
  try {
    const m = await api.get('/api/mood');
    setMoodUI(m.mode, m.label);
  } catch (_) {}
}
function setMoodUI(mode, label) {
  state.currentMood = mode;
  $('mood-label').textContent = label || mode;
  document.querySelectorAll('.persona-btn').forEach(b => b.classList.toggle('active', b.dataset.mood===mode));
  const av = $('agent-avatar'); av.classList.add('pulse'); setTimeout(()=>av.classList.remove('pulse'),400);
}
document.querySelectorAll('.persona-btn').forEach(b => {
  b.addEventListener('click', async () => {
    try {
      const r = await api.post(`/api/mood/${b.dataset.mood}`);
      const L = { friend:'😏 损友模式', drill:'🪖 军训教官模式', boss:'😔 怨念上司模式' };
      setMoodUI(b.dataset.mood, L[b.dataset.mood]);
      toast(r.message||'人格已切换', 'ok');
    } catch (e) { toast('切换失败', 'error'); }
  });
});

// ── Notion ─────────────────────────────────────────────────────────────────
async function loadNotionStatus() {
  try {
    const n   = await api.get('/api/notion/status');
    const dot = $('notion-dot'); const lbl = $('notion-label');
    if (n.configured) {
      if (dot) dot.className = 'notion-dot ok';
      if (lbl) lbl.innerHTML = `<a href="${n.url}" target="_blank" style="color:inherit;text-decoration:none">Notion 已连接</a>`;
    }
  } catch (_) {}
}
$('sync-btn').addEventListener('click', async () => {
  const ic = $('sync-icon'); ic.style.animation='spin .7s linear infinite';
  try {
    const r = await api.post('/api/notion/sync');
    toast(`同步完成 ↑${r.pushed} ↓${r.pulled}`, 'ok');
  } catch (e) { toast('同步失败', 'error'); }
  finally { ic.style.animation=''; ic.textContent='⟳'; await Promise.all([loadBoard(),loadSummary()]); }
});

// ── Weekly report ──────────────────────────────────────────────────────────
$('weekly-btn').addEventListener('click', async () => {
  $('weekly-btn').textContent = '⏳…'; $('weekly-btn').disabled = true;
  try { const r = await api.post('/api/weekly'); appendMsg('agent', r.report||'周报生成失败'); }
  catch (e) { toast('周报失败: '+e.message,'error'); }
  finally { $('weekly-btn').textContent='📋 周报'; $('weekly-btn').disabled=false; }
});

// ── Chat ───────────────────────────────────────────────────────────────────
const $msgs      = $('messages');
const $chatInput = $('chat-input');
const $sendBtn   = $('send-btn');
// No text send-icon in this build — spinner handled via CSS class on button

const _AGENT_AV = `<div class="msg-av-wrap"><svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M7 17L12 7l5 10M9.5 14h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></div>`;
const _USER_AV  = `<div class="msg-av-wrap"><svg viewBox="0 0 24 24" fill="none" width="13" height="13"><circle cx="12" cy="8" r="4" stroke="currentColor" stroke-width="1.6"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></div>`;

function appendMsg(role, text, withTs = true) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  const ts = withTs ? `<div class="msg-ts">${now()}</div>` : '';
  div.innerHTML =
    (role === 'agent' ? _AGENT_AV : '') +
    `<div class="msg-content"><div class="msg-bubble">${esc(text)}</div>${ts}</div>` +
    (role !== 'agent' ? _USER_AV : '');
  $msgs.appendChild(div);
  $msgs.scrollTop = $msgs.scrollHeight;
  return div.querySelector('.msg-bubble');
}

function appendTypingEl() {
  const div = document.createElement('div');
  div.className='msg agent'; div.id='typing-ind';
  div.innerHTML=_AGENT_AV+'<div class="typing-dots"><span></span><span></span><span></span></div>';
  $msgs.appendChild(div); $msgs.scrollTop=$msgs.scrollHeight;
  return div;
}

async function sendMessage(text) {
  if ((!text.trim() && !state.pastedImage) || state.sending) return;
  state.sending = true;
  $sendBtn.disabled=true; $sendBtn.classList.add('loading');

  // If there's a pasted image, run OCR first
  if (state.pastedImage) {
    const imgFile = state.pastedImage.file;
    clearPastedImage();
    state.sending=false; $sendBtn.disabled=false; $sendBtn.classList.remove('loading');
    runOcr(imgFile, text);
    return;
  }

  appendMsg('user', text);
  $chatInput.value=''; $chatInput.style.height='auto';

  const typingEl = appendTypingEl();
  let   bubble   = null;
  let   fullReply = '';

  try {
    const resp = await fetch('/api/chat', {
      method:'POST', headers:{'X-Auth-Token':state.token,'Content-Type':'application/json'},
      body: JSON.stringify({ message: text, history: state.history }),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);

    const reader = resp.body.getReader(); const decoder = new TextDecoder(); let buf='';
    while (true) {
      const {value, done} = await reader.read(); if (done) break;
      buf += decoder.decode(value, {stream:true});
      const lines = buf.split('\n'); buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim(); if (raw==='[DONE]') break;
        try {
          const chunk = JSON.parse(raw);
          if (chunk.error) { toast(chunk.error,'error'); break; }
          if (chunk.char !== undefined) {
            if (!bubble) { typingEl.remove(); bubble = appendMsg('agent',''); bubble.innerHTML='<span class="cursor"></span>'; }
            fullReply += chunk.char;
            bubble.innerHTML = esc(fullReply)+'<span class="cursor"></span>';
            $msgs.scrollTop = $msgs.scrollHeight;
          }
        } catch (_) {}
      }
    }
  } catch (e) { typingEl.remove(); toast('发送失败','error'); }
  finally {
    if (bubble) bubble.innerHTML = esc(fullReply);
    state.sending=false; $sendBtn.disabled=false; $sendIcon.className=''; $sendIcon.textContent='↑';
    state.history.push({role:'user',content:text});
    state.history.push({role:'assistant',content:fullReply});
    if (state.history.length>12) state.history=state.history.slice(-12);
    loadBoard(); loadSummary();
  }
}

$sendBtn.addEventListener('click', () => sendMessage($chatInput.value));
$chatInput.addEventListener('keydown', e => { if (e.key==='Enter'&&!e.shiftKey) { e.preventDefault(); sendMessage($chatInput.value); } });
$chatInput.addEventListener('input', () => { $chatInput.style.height='auto'; $chatInput.style.height=Math.min($chatInput.scrollHeight,140)+'px'; });
document.querySelectorAll('.chip').forEach(b => b.addEventListener('click', ()=>sendMessage(b.dataset.msg)));

// ── Paste image in chat ────────────────────────────────────────────────────
$chatInput.addEventListener('paste', handlePaste);
document.addEventListener('paste', e => {
  // Only trigger if not focused on an editable element other than chat-input
  if (document.activeElement !== $chatInput && document.activeElement.isContentEditable) return;
  if (document.activeElement.tagName.toLowerCase() === 'input' && document.activeElement.id !== 'chat-input') return;
  handlePaste(e);
});

function handlePaste(e) {
  const items = e.clipboardData?.items;
  if (!items) return;
  for (const item of items) {
    if (item.type.startsWith('image/')) {
      const file = item.getAsFile();
      if (file) {
        e.preventDefault();
        showPastePreview(file);
      }
      break;
    }
  }
}

function showPastePreview(file) {
  // Remove existing preview
  const existing = document.querySelector('.paste-preview');
  if (existing) existing.remove();

  const url = URL.createObjectURL(file);
  state.pastedImage = { file, previewUrl: url };

  const preview = document.createElement('div');
  preview.className = 'paste-preview';
  preview.innerHTML = `
    <img src="${url}" class="paste-preview-img" alt="" />
    <span>图片已粘贴，按 Enter 识别任务</span>
    <span class="paste-preview-close" title="取消">✕</span>
  `;
  preview.querySelector('.paste-preview-close').addEventListener('click', clearPastedImage);
  $('textarea-wrap').appendChild(preview);
  $chatInput.placeholder = '补充说明（可选），按 Enter 发送识别';
  $chatInput.focus();
}

function clearPastedImage() {
  if (state.pastedImage) { URL.revokeObjectURL(state.pastedImage.previewUrl); state.pastedImage = null; }
  const p = document.querySelector('.paste-preview'); if (p) p.remove();
  $chatInput.placeholder = '输入消息… (Enter 发送，Shift+Enter 换行)';
}

// ── Task-scoped chat ───────────────────────────────────────────────────────
function appendTaskMsg(role, text) {
  const el  = $('tdp-messages');
  const div = document.createElement('div');
  div.className = `msg ${role==='user'?'user':'agent'}`;
  div.style.maxWidth='100%';
  div.innerHTML = `
    ${role!=='user' ? _AGENT_AV : ''}
    <div class="msg-bubble" style="font-size:12.5px">${esc(text)}</div>
    ${role==='user' ? _USER_AV : ''}
  `;
  el.appendChild(div); el.scrollTop=el.scrollHeight;
  return div.querySelector('.msg-bubble');
}

async function sendTaskMsg(text) {
  if (!text.trim()||state.taskSending||!state.activeTask) return;
  state.taskSending = true;
  const taskName = state.activeTask.name;
  const btn = $('tdp-send-btn'); const inp = $('tdp-input');
  btn.disabled=true; inp.value=''; inp.style.height='auto';
  appendTaskMsg('user', text);

  const typingDiv = document.createElement('div');
  typingDiv.className='msg agent';
  typingDiv.innerHTML='<span class="msg-av" style="font-size:14px">⚡</span><div class="typing-dots"><span></span><span></span><span></span></div>';
  $('tdp-messages').appendChild(typingDiv); $('tdp-messages').scrollTop=99999;

  const history = state.taskHistories[taskName]||[]; let bubble=null; let fullReply='';
  try {
    const resp = await fetch(`/api/chat/task/${encodeURIComponent(taskName)}`, {
      method:'POST', headers:{'X-Auth-Token':state.token,'Content-Type':'application/json'},
      body: JSON.stringify({message:text,history}),
    });
    if (!resp.ok) throw new Error(`${resp.status}`);
    const reader=resp.body.getReader(); const decoder=new TextDecoder(); let buf='';
    while(true) {
      const {value,done}=await reader.read(); if(done) break;
      buf+=decoder.decode(value,{stream:true});
      const lines=buf.split('\n'); buf=lines.pop();
      for(const line of lines) {
        if(!line.startsWith('data: ')) continue;
        const raw=line.slice(6).trim(); if(raw==='[DONE]') break;
        try {
          const chunk=JSON.parse(raw);
          if(chunk.char!==undefined) {
            if(!bubble){typingDiv.remove();bubble=appendTaskMsg('agent','');bubble.innerHTML='<span class="cursor"></span>';}
            fullReply+=chunk.char; bubble.innerHTML=esc(fullReply)+'<span class="cursor"></span>';
            $('tdp-messages').scrollTop=99999;
          }
        } catch(_){}
      }
    }
  } catch(e){typingDiv.remove();toast('发送失败','error');}
  finally {
    if(bubble) bubble.innerHTML=esc(fullReply);
    state.taskSending=false; btn.disabled=false;
    const hist=state.taskHistories[taskName]||[];
    hist.push({role:'user',content:text}); hist.push({role:'assistant',content:fullReply});
    state.taskHistories[taskName]=hist.slice(-12);
    if(state.activeTask&&state.activeTask.name===taskName) {
      try { const ts=await api.get('/api/tasks?limit=200'); const fresh=ts.find(t=>t.name===taskName); if(fresh){state.activeTask=fresh;openTaskDetail(fresh);} } catch(_){}
    }
    await Promise.all([loadBoard(),loadSummary()]);
  }
}

$('tdp-send-btn').addEventListener('click', ()=>sendTaskMsg($('tdp-input').value));
$('tdp-input').addEventListener('keydown', e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendTaskMsg($('tdp-input').value);}});
$('tdp-input').addEventListener('input', ()=>{const el=$('tdp-input');el.style.height='auto';el.style.height=Math.min(el.scrollHeight,80)+'px';});

// ── File upload (text/PDF) ─────────────────────────────────────────────────
const _TEXT_EXTS=new Set(['txt','md','json','csv','py','js','ts','jsx','tsx','html','css','xml','yaml','yml','toml','ini','sh','bat']);
$('file-btn').addEventListener('click',()=>$('file-input').click());
$('file-input').addEventListener('change',e=>{const f=e.target.files[0];if(f)uploadTextFile(f);e.target.value='';});

async function uploadTextFile(file) {
  const ext=(file.name.split('.').pop()||'').toLowerCase();
  let content='', filename=file.name;
  if (ext==='pdf') {
    const fd=new FormData(); fd.append('file',file);
    try {
      const r=await fetch('/api/upload',{method:'POST',headers:{'X-Auth-Token':state.token},body:fd});
      if(!r.ok){const err=await r.json().catch(()=>({detail:r.statusText}));throw new Error(err.detail||r.statusText);}
      const data=await r.json(); content=data.content; filename=data.filename;
      if(data.truncated) toast('文件已截断至 8000 字符');
    } catch(e){toast('文件读取失败: '+e.message,'error');return;}
  } else if(_TEXT_EXTS.has(ext)||file.type.startsWith('text/')) {
    content=await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=()=>rej();r.readAsText(file,'utf-8');});
  } else { toast('不支持此格式','error'); return; }
  const preview=esc(content.slice(0,300))+(content.length>300?'…':'');
  const ub=appendMsg('user',`📎 ${filename}`);
  ub.insertAdjacentHTML('afterend',`<details class="file-block"><summary>📄 ${esc(filename)} (${content.length} 字)</summary><pre>${preview}</pre></details>`);
  await sendMessage(`[文件: ${filename}]\n${content.slice(0,8000)}`);
}

// ── OCR ────────────────────────────────────────────────────────────────────
$('ocr-btn').addEventListener('click',()=>$('img-input').click());
$('img-input').addEventListener('change',e=>{const f=e.target.files[0];if(f)runOcr(f);e.target.value='';});

// Drag & drop onto chat panel
const $chatPanel = $('chat-panel');
$chatPanel.addEventListener('dragover',e=>{e.preventDefault();$('drop-overlay').classList.remove('hidden');});
$chatPanel.addEventListener('dragleave',e=>{if(!$chatPanel.contains(e.relatedTarget))$('drop-overlay').classList.add('hidden');});
$chatPanel.addEventListener('drop',e=>{
  e.preventDefault(); $('drop-overlay').classList.add('hidden');
  const f=e.dataTransfer.files[0]; if(!f) return;
  if(f.type.startsWith('image/')) runOcr(f); else uploadTextFile(f);
});

async function runOcr(file, context = '') {
  appendMsg('user', `📸 ${file.name}`);
  if (context) appendMsg('user', context);
  const typingEl = appendTypingEl();
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await fetch('/api/ocr', { method:'POST', headers:{'X-Auth-Token':state.token}, body:fd });
    typingEl.remove();
    if (!r.ok) { const err=await r.json().catch(()=>({detail:r.statusText})); appendMsg('agent',`识别失败：${err.detail||r.statusText}`); return; }
    const data = await r.json();
    if (!data.tasks?.length) { appendMsg('agent','没有找到任务，换一张图试试？'); return; }
    state.ocrTasks = data.tasks;
    showOcrModal(data.tasks);
  } catch(e) { typingEl.remove(); toast('OCR 失败: '+e.message,'error'); }
}

function showOcrModal(tasks) {
  const list = $('ocr-task-list');
  list.innerHTML = '';
  tasks.forEach((t, i) => {
    const pe = { high:'🔴', medium:'🟡', low:'🔵' }[t.priority]||'🟡';
    const dl = t.deadline ? `<span class="dl-tag soon">⏰ ${esc(t.deadline)}</span>` : '';
    const item = document.createElement('div');
    item.className = 'ocr-task-item';
    item.innerHTML = `
      <input type="checkbox" checked data-idx="${i}" />
      <div class="ocr-body">
        <input class="ocr-name-input" value="${esc(t.name)}" data-idx="${i}" />
        <div class="ocr-meta">
          <span class="p-pill ${t.priority}">${pe} ${t.priority}</span>
          ${dl}
        </div>
        ${t.notes ? `<div class="ocr-notes">${esc(t.notes)}</div>` : ''}
      </div>`;
    // Keep name in sync with state
    item.querySelector('.ocr-name-input').addEventListener('input', e => {
      state.ocrTasks[i].name = e.target.value;
    });
    list.appendChild(item);
  });
  $('ocr-modal').classList.remove('hidden');
}

$('ocr-select-all').addEventListener('click', () => {
  const cbs = $('ocr-task-list').querySelectorAll('input[type=checkbox]');
  const allChecked = Array.from(cbs).every(cb => cb.checked);
  cbs.forEach(cb => cb.checked = !allChecked);
  $('ocr-select-all').textContent = allChecked ? '全选' : '取消全选';
});
$('ocr-modal-close').addEventListener('click', ()=>{$('ocr-modal').classList.add('hidden');state.ocrTasks=[];});
$('ocr-cancel-btn').addEventListener('click',()=>{$('ocr-modal').classList.add('hidden');state.ocrTasks=[];appendMsg('agent','已取消。');});
$('ocr-confirm-btn').addEventListener('click', async () => {
  const checked = Array.from($('ocr-task-list').querySelectorAll('input[type=checkbox]:checked')).map(cb=>parseInt(cb.dataset.idx));
  const selected = checked.map(i=>state.ocrTasks[i]).filter(Boolean);
  if (!selected.length) { toast('没有选中任何任务','error'); return; }
  $('ocr-confirm-btn').textContent='创建中…'; $('ocr-confirm-btn').disabled=true;
  let created=0;
  for (const t of selected) {
    try { await api.post('/api/tasks',{name:t.name||'未命名任务',priority:t.priority||'medium',notes:t.notes||'',deadline:t.deadline||''}); created++; } catch(_){}
  }
  $('ocr-modal').classList.add('hidden');
  $('ocr-confirm-btn').textContent='创建选中'; $('ocr-confirm-btn').disabled=false;
  state.ocrTasks=[];
  appendMsg('agent', `✅ 已创建 ${created} 个任务。`);
  await Promise.all([loadBoard(),loadSummary()]);
});

// ── Export ─────────────────────────────────────────────────────────────────
$('export-btn').addEventListener('click', e=>{e.stopPropagation();$('export-dropdown').classList.toggle('hidden');});
$('export-csv-btn').addEventListener('click',()=>{$('export-dropdown').classList.add('hidden');exportTasks('csv');});
$('export-md-btn').addEventListener('click',()=>{$('export-dropdown').classList.add('hidden');exportTasks('md');});
document.addEventListener('click',()=>$('export-dropdown').classList.add('hidden'));
function exportTasks(fmt) {
  const url=`/api/export/${fmt}?_t=${encodeURIComponent(state.token)}`;
  const a=document.createElement('a'); a.href=url; a.setAttribute('download',fmt==='csv'?'tasks.csv':'tasks.md');
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}
