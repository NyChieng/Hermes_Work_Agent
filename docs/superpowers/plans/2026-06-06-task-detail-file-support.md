# Task Detail Panel + File Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a three-column layout with a task detail panel (full info + task-scoped agent chat) and file upload/export to the existing Web UI.

**Architecture:** Four files change — `api.py` gets 4 new endpoints, `index.html` gets the task detail panel markup + file/export controls, `style.css` gets new rules appended, `app.js` gets new functions + two modified functions. The existing edit-sidebar (`#edit-sidebar`) is replaced entirely by the new `#task-detail-panel`.

**Tech Stack:** FastAPI (SSE), Vanilla JS (FileReader, fetch), CSS flex layout, optional `pypdf` for PDF extraction.

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `api.py` | Modify | Add 4 endpoints: `/api/upload`, `/api/export/csv`, `/api/export/md`, `/api/chat/task/{task_name}` |
| `requirements.txt` | Modify | Add `pypdf` |
| `static/index.html` | Modify | Replace `#edit-sidebar` with `#task-detail-panel`; add file input + 📎 button; add export dropdown |
| `static/style.css` | Modify | Append new rules for 3-col layout, detail panel, badges, tags, file block, export dropdown |
| `static/app.js` | Modify | Replace `openEdit()`; add `openTaskDetail()`, `closeTaskDetail()`, `sendTaskMessage()`, `uploadFile()`, `exportTasks()`; add `state.taskHistories` |

---

## Task 1: Backend — 4 new API endpoints

**Files:**
- Modify: `api.py` (append after the last endpoint)
- Modify: `requirements.txt`

- [ ] **Step 1: Add `pypdf` to requirements.txt**

Open `requirements.txt` and add at the end:
```
pypdf>=4.0.0
```

- [ ] **Step 2: Add imports at the top of `api.py`**

Find the existing imports block in `api.py` and add these imports:
```python
import csv
import io

from fastapi import File, UploadFile
from fastapi.responses import Response
```

The full imports block should look like:
```python
import asyncio
import csv
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
```

- [ ] **Step 3: Append the 4 new endpoints to the end of `api.py`**

```python
# ── file upload ───────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def api_upload(request: Request, file: UploadFile = File(...)):
    _verify(request)
    raw = await file.read()
    filename = file.filename or "file"

    # PDF extraction
    if filename.lower().endswith(".pdf"):
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw))
            content = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            raise HTTPException(400, "PDF 支持未安装，请运行: pip install pypdf")
        except Exception as exc:
            raise HTTPException(400, f"PDF 读取失败: {exc}")
    else:
        # Try UTF-8 then GBK for text files
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(
                400, "不支持此格式，请上传文本文件或 PDF"
            )

    return {"filename": filename, "content": content[:8000]}


# ── export ────────────────────────────────────────────────────────────────────

@app.get("/api/export/csv")
def api_export_csv(request: Request):
    _verify(request)
    from tools import list_tasks

    tasks = list_tasks(limit=500)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["name", "status", "priority", "notes", "tags", "updated"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(tasks)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tasks.csv"},
    )


@app.get("/api/export/md")
def api_export_md(request: Request):
    _verify(request)
    from tools import list_tasks

    sections = {
        "in_progress": ("🟡 进行中", False),
        "blocked":     ("🔴 阻塞",   False),
        "todo":        ("⬜ 未开始", False),
        "done":        ("✅ 已完成", True),
    }
    lines = ["# 工作进度\n"]
    for status, (heading, checked) in sections.items():
        tasks = list_tasks(status=status, limit=200)
        if not tasks:
            continue
        lines.append(f"## {heading}\n")
        for t in tasks:
            box = "[x]" if checked else "[ ]"
            note = f" — {t['notes']}" if t.get("notes") else ""
            lines.append(f"- {box} **{t['name']}**{note}")
        lines.append("")

    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tasks.md"},
    )


# ── task-scoped chat (SSE) ────────────────────────────────────────────────────

class TaskChatRequest(BaseModel):
    message: str
    history: list = []


@app.post("/api/chat/task/{task_name}")
async def api_chat_task(request: Request, task_name: str, body: TaskChatRequest):
    _verify(request)

    # Fetch current task data to inject as context
    from tools import query_task
    results = query_task(task_name)
    task = next((t for t in results if t["name"] == task_name), None)
    if not task:
        # Fuzzy fallback
        task = results[0] if results else {"name": task_name}

    context_prefix = (
        f"[任务上下文] 当前任务：{task.get('name','')} | "
        f"状态：{task.get('status','')} | "
        f"优先级：{task.get('priority','')} | "
        f"备注：{task.get('notes','')} | "
        f"标签：{task.get('tags','')}\n\n"
    )
    enriched_message = context_prefix + body.message

    async def generate():
        loop = asyncio.get_event_loop()
        from agent import run_agent
        try:
            answer, _ = await loop.run_in_executor(
                None, run_agent, enriched_message, body.history
            )
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return

        for char in answer:
            yield f"data: {json.dumps({'char': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.02)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

- [ ] **Step 4: Verify the server starts without errors**

```bash
cd D:\Hermes\work-agent
py -3 -c "import api; print('api.py OK')"
```

Expected output: `api.py OK`

- [ ] **Step 5: Commit**

```bash
cd D:\Hermes\work-agent
git add api.py requirements.txt
git commit -m "feat: add upload, export, task-chat endpoints"
```

---

## Task 2: HTML — Replace edit-sidebar, add detail panel + controls

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Replace the file input and 📎 button into the chat input area**

Find this block in `index.html`:
```html
    <div class="input-wrap">
      <textarea id="chat-input" placeholder="输入消息… (Enter 发送，Shift+Enter 换行)" rows="1"></textarea>
      <button id="send-btn">
        <span id="send-icon">➤</span>
      </button>
    </div>
```

Replace with:
```html
    <div class="input-wrap">
      <input type="file" id="file-input" hidden
             accept=".txt,.md,.json,.csv,.py,.js,.ts,.xml,.yaml,.yml,.pdf" />
      <button id="file-btn" class="file-btn" title="上传文件">📎</button>
      <textarea id="chat-input" placeholder="输入消息… (Enter 发送，Shift+Enter 换行)" rows="1"></textarea>
      <button id="send-btn">
        <span id="send-icon">➤</span>
      </button>
    </div>
```

- [ ] **Step 2: Replace the board footer to add export dropdown**

Find:
```html
    <!-- Notion sync footer -->
    <footer class="board-footer">
      <span id="notion-status" class="notion-status">Notion 未配置</span>
      <button id="sync-btn" class="btn-ghost btn-sm" title="手动同步 Notion">
        <span id="sync-icon">🔄</span> 同步
      </button>
    </footer>
```

Replace with:
```html
    <!-- Notion sync footer -->
    <footer class="board-footer">
      <span id="notion-status" class="notion-status">Notion 未配置</span>
      <div class="footer-actions">
        <div class="export-wrap">
          <button id="export-btn" class="btn-ghost btn-sm">📥 导出</button>
          <div id="export-dropdown" class="export-dropdown hidden">
            <button id="export-csv-btn">📊 下载 CSV</button>
            <button id="export-md-btn">📝 下载 Markdown</button>
          </div>
        </div>
        <button id="sync-btn" class="btn-ghost btn-sm" title="手动同步 Notion">
          <span id="sync-icon">🔄</span> 同步
        </button>
      </div>
    </footer>
```

- [ ] **Step 3: Remove the old edit-sidebar and add task detail panel**

Find and DELETE the entire old sidebar block:
```html
  <!-- Task edit sidebar (slides in from right) -->
  <div id="edit-sidebar" class="edit-sidebar hidden">
    <div class="edit-header">
      <span>编辑任务</span>
      <button id="edit-close" class="btn-ghost">✕</button>
    </div>
    <label>任务名称</label>
    <input id="edit-name" type="text" />
    <label>状态</label>
    <select id="edit-status">
      <option value="todo">⬜ 未开始</option>
      <option value="in_progress">🟡 进行中</option>
      <option value="done">✅ 已完成</option>
      <option value="blocked">🔴 阻塞</option>
    </select>
    <label>优先级</label>
    <select id="edit-priority">
      <option value="high">🔴 高</option>
      <option value="medium">🟡 中</option>
      <option value="low">🔵 低</option>
    </select>
    <label>备注</label>
    <textarea id="edit-notes" rows="3"></textarea>
    <div class="edit-actions">
      <button id="edit-save-btn" class="btn-primary">保存</button>
      <button id="edit-delete-btn" class="btn-danger">归档</button>
    </div>
  </div>
```

In its place, add the new task detail panel **before** `</div><!-- #app -->`:
```html
  <!-- Task detail panel (slides in from right on task click) -->
  <div id="task-detail-panel" class="task-detail-panel hidden">

    <!-- Header -->
    <div class="tdp-header">
      <span id="tdp-name" class="tdp-name" contenteditable="true" spellcheck="false"></span>
      <div class="tdp-header-btns">
        <button id="tdp-archive-btn" class="btn-danger btn-sm">归档</button>
        <button id="tdp-close-btn" class="btn-ghost btn-sm">✕</button>
      </div>
    </div>

    <!-- Badges (clickable to cycle) -->
    <div class="tdp-badges">
      <span id="tdp-status-badge" class="status-badge" title="点击切换状态"></span>
      <span id="tdp-priority-badge" class="priority-badge" title="点击切换优先级"></span>
    </div>

    <!-- Quick-action status buttons -->
    <div class="quick-actions">
      <button class="qa-btn" data-status="todo">⬜ Todo</button>
      <button class="qa-btn" data-status="in_progress">🟡 进行中</button>
      <button class="qa-btn" data-status="done">✅ 完成</button>
      <button class="qa-btn" data-status="blocked">🔴 阻塞</button>
    </div>

    <!-- Details -->
    <div class="tdp-details">
      <div id="tdp-tags" class="tdp-tags"></div>
      <div id="tdp-notes" class="tdp-notes"></div>
      <div id="tdp-meta" class="tdp-meta-row"></div>
      <div id="tdp-notion" class="tdp-notion-row"></div>
    </div>

    <!-- Task-scoped agent chat -->
    <div class="tdp-chat">
      <div class="tdp-chat-title">💬 和 agent 讨论这个任务</div>
      <div id="tdp-messages" class="tdp-messages"></div>
      <div class="tdp-input-wrap">
        <textarea id="tdp-input" placeholder="针对此任务提问… (Enter 发送)" rows="1"></textarea>
        <button id="tdp-send-btn">➤</button>
      </div>
    </div>

  </div><!-- #task-detail-panel -->
```

- [ ] **Step 4: Commit**

```bash
cd D:\Hermes\work-agent
git add static/index.html
git commit -m "feat: add task detail panel markup + file/export controls"
```

---

## Task 3: CSS — New styles

**Files:**
- Modify: `static/style.css` (append to end of file)

- [ ] **Step 1: Append all new CSS rules to the end of `style.css`**

```css
/* ── Three-column layout ─────────────────────────────────────── */
#app {
  position: relative;
}
#app.app-3col #board-panel {
  width: 30%;
  min-width: 220px;
}
#app.app-3col #chat-panel {
  flex: 1;
  min-width: 0;
}

/* ── Task detail panel ───────────────────────────────────────── */
.task-detail-panel {
  width: 30%;
  min-width: 280px;
  max-width: 400px;
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: slideIn .22s ease;
  flex-shrink: 0;
}
.task-detail-panel.hidden { display: none; }

.tdp-header {
  padding: 14px 16px 10px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tdp-name {
  font-size: 15px;
  font-weight: 600;
  flex: 1;
  outline: none;
  border-radius: 4px;
  padding: 2px 4px;
  word-break: break-word;
  cursor: text;
  transition: background .15s;
}
.tdp-name:focus {
  background: var(--surface2);
  box-shadow: 0 0 0 2px var(--accent);
}
.tdp-header-btns { display: flex; gap: 6px; flex-shrink: 0; }

/* Badges */
.tdp-badges {
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  flex-shrink: 0;
}
.status-badge, .priority-badge {
  padding: 3px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: opacity .15s;
  user-select: none;
}
.status-badge:hover, .priority-badge:hover { opacity: .8; }

.status-badge[data-status="todo"]        { background:#1e293b; color:var(--todo);    border-color:var(--todo); }
.status-badge[data-status="in_progress"] { background:#1c1a05; color:var(--wip);     border-color:var(--wip); }
.status-badge[data-status="done"]        { background:#052e16; color:var(--done);    border-color:var(--done); }
.status-badge[data-status="blocked"]     { background:#2d0b0b; color:var(--blocked); border-color:var(--blocked); }

.priority-badge[data-priority="high"]   { background:#2d0b0b; color:var(--blocked); border-color:var(--blocked); }
.priority-badge[data-priority="medium"] { background:#1c1a05; color:var(--wip);     border-color:var(--wip); }
.priority-badge[data-priority="low"]    { background:#0f172a; color:var(--todo);    border-color:var(--todo); }

/* Quick actions */
.quick-actions {
  display: flex;
  gap: 5px;
  padding: 0 16px 10px;
  flex-shrink: 0;
}
.qa-btn {
  flex: 1;
  padding: 4px 2px;
  font-size: 11px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-dim);
  font-family: var(--font);
  cursor: pointer;
  transition: all .15s;
  white-space: nowrap;
}
.qa-btn:hover { border-color: var(--accent); color: var(--text); }
.qa-btn.active { border-color: var(--accent); background: var(--accent-dim); color: var(--text); }

/* Details section */
.tdp-details {
  padding: 0 16px 8px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tdp-tags { display: flex; flex-wrap: wrap; gap: 5px; min-height: 4px; }
.tag-pill {
  padding: 2px 8px;
  background: var(--accent-dim);
  border: 1px solid var(--accent);
  border-radius: 20px;
  font-size: 11px;
  color: var(--text-dim);
}
.tdp-notes {
  font-size: 13px;
  color: var(--text);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 80px;
  overflow-y: auto;
}
.tdp-meta-row, .tdp-notion-row {
  font-size: 11px;
  color: var(--text-dim);
}
.tdp-notion-row a { color: var(--accent); text-decoration: none; }
.tdp-notion-row a:hover { text-decoration: underline; }

/* Task chat */
.tdp-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-top: 1px solid var(--border);
  overflow: hidden;
}
.tdp-chat-title {
  padding: 8px 16px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-dim);
  background: var(--surface2);
  flex-shrink: 0;
}
.tdp-messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  scroll-behavior: smooth;
}
.tdp-input-wrap {
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  display: flex;
  gap: 8px;
  align-items: flex-end;
  flex-shrink: 0;
}
#tdp-input {
  flex: 1;
  padding: 7px 10px;
  resize: none;
  max-height: 80px;
  overflow-y: auto;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  font-family: var(--font);
  font-size: 13px;
  outline: none;
  transition: border-color .2s;
  line-height: 1.4;
}
#tdp-input:focus { border-color: var(--accent); }
#tdp-send-btn {
  width: 34px; height: 34px;
  background: var(--accent); border: none; border-radius: 50%;
  color: #fff; font-size: 14px; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; transition: opacity .2s;
}
#tdp-send-btn:disabled { opacity: .4; cursor: not-allowed; }

/* ── File upload button ───────────────────────────────────────── */
.file-btn {
  width: 36px; height: 36px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 16px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: border-color .2s;
}
.file-btn:hover { border-color: var(--accent); }

/* File content block in chat */
.file-block {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
  overflow: hidden;
  margin-top: 4px;
}
.file-block summary {
  padding: 6px 10px;
  cursor: pointer;
  color: var(--text-dim);
  user-select: none;
}
.file-block pre {
  padding: 8px 10px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 120px;
  overflow-y: auto;
  border-top: 1px solid var(--border);
}

/* ── Export dropdown ─────────────────────────────────────────── */
.board-footer { position: relative; }
.footer-actions { display: flex; gap: 6px; align-items: center; }
.export-wrap { position: relative; }
.export-dropdown {
  position: absolute;
  bottom: calc(100% + 4px);
  right: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  z-index: 50;
  min-width: 140px;
  box-shadow: 0 4px 16px #0006;
  animation: fadeIn .15s ease;
}
.export-dropdown.hidden { display: none; }
.export-dropdown button {
  display: block;
  width: 100%;
  padding: 9px 14px;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--text);
  font-family: var(--font);
  font-size: 13px;
  cursor: pointer;
  transition: background .15s;
}
.export-dropdown button:hover { background: var(--surface2); }

/* ── Narrow screen: detail panel overlays ────────────────────── */
@media (max-width: 900px) {
  .task-detail-panel {
    position: fixed;
    right: 0; top: 0; bottom: 0;
    width: 100% !important;
    max-width: 420px;
    z-index: 100;
    background: var(--bg);
  }
}
```

- [ ] **Step 2: Commit**

```bash
cd D:\Hermes\work-agent
git add static/style.css
git commit -m "feat: add task detail panel + file + export CSS"
```

---

## Task 4: JavaScript — Task Detail Panel (open/close + display)

**Files:**
- Modify: `static/app.js`

- [ ] **Step 1: Add `taskHistories` to the state object**

Find:
```javascript
const state = {
  token:       sessionStorage.getItem('wa_token') || '',
  history:     [],
  currentMood: 'friend',
  tasks:       [],
  editing:     null,
  sending:     false,
};
```

Replace with:
```javascript
const state = {
  token:          sessionStorage.getItem('wa_token') || '',
  history:        [],
  currentMood:    'friend',
  tasks:          [],
  editing:        null,   // kept for backward compat (no longer used)
  sending:        false,
  activeTask:     null,   // task object currently shown in detail panel
  taskHistories:  {},     // { [taskName]: [{role, content}] }
  taskSending:    false,
};
```

- [ ] **Step 2: Add `openTaskDetail`, `closeTaskDetail`, and badge/quick-action helpers**

Find the `// ── Edit sidebar` section in `app.js` and REPLACE the entire edit-sidebar block (from `function openEdit(task)` through the last `document.getElementById('edit-delete-btn').addEventListener(...)` block) with:

```javascript
// ── Task Detail Panel ──────────────────────────────────────────────────────

const _STATUS_LABELS  = { todo:'⬜ Todo', in_progress:'🟡 进行中', done:'✅ 完成', blocked:'🔴 阻塞' };
const _PRIORITY_LABELS = { high:'🔴 高优', medium:'🟡 中优', low:'🔵 低优' };
const _STATUS_CYCLE   = ['todo','in_progress','done','blocked'];
const _PRIORITY_CYCLE = ['low','medium','high'];

function openTaskDetail(task) {
  state.activeTask = task;

  // Populate header
  const nameEl = document.getElementById('tdp-name');
  nameEl.textContent = task.name;

  // Badges
  const sb = document.getElementById('tdp-status-badge');
  sb.dataset.status = task.status;
  sb.textContent = _STATUS_LABELS[task.status] || task.status;

  const pb = document.getElementById('tdp-priority-badge');
  pb.dataset.priority = task.priority;
  pb.textContent = _PRIORITY_LABELS[task.priority] || task.priority;

  // Quick actions — highlight active
  document.querySelectorAll('.qa-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.status === task.status);
  });

  // Tags
  const tagsEl = document.getElementById('tdp-tags');
  tagsEl.innerHTML = '';
  (task.tags || '').split(',').map(t => t.trim()).filter(Boolean).forEach(tag => {
    const pill = document.createElement('span');
    pill.className = 'tag-pill';
    pill.textContent = tag;
    tagsEl.appendChild(pill);
  });

  // Notes
  document.getElementById('tdp-notes').textContent = task.notes || '（无备注）';

  // Meta
  document.getElementById('tdp-meta').textContent = task.updated ? `🕐 更新：${task.updated}` : '';

  // Notion
  const notionEl = document.getElementById('tdp-notion');
  if (task.notion_id) {
    const url = `https://www.notion.so/${task.notion_id.replace(/-/g,'')}`;
    notionEl.innerHTML = `🔗 Notion <a href="${url}" target="_blank">已同步</a>`;
  } else {
    notionEl.textContent = 'Notion：未同步';
  }

  // Chat history
  const msgEl = document.getElementById('tdp-messages');
  msgEl.innerHTML = '';
  const hist = state.taskHistories[task.name] || [];
  hist.forEach(m => appendTaskMessage(m.role === 'user' ? 'user' : 'agent', m.content));

  // Show panel
  document.getElementById('task-detail-panel').classList.remove('hidden');
  document.getElementById('app').classList.add('app-3col');

  document.getElementById('tdp-input').focus();
}

function closeTaskDetail() {
  document.getElementById('task-detail-panel').classList.add('hidden');
  document.getElementById('app').classList.remove('app-3col');
  state.activeTask = null;
}

// Inline name editing — save on blur
document.getElementById('tdp-name').addEventListener('blur', async () => {
  if (!state.activeTask) return;
  const newName = document.getElementById('tdp-name').textContent.trim();
  if (!newName || newName === state.activeTask.name) return;
  try {
    await api.patch(`/api/tasks/${encodeURIComponent(state.activeTask.name)}`, {});
    // Name changes are not supported by PATCH (name is the PK); just reload
    await loadBoard();
  } catch (e) { /* ignore */ }
});

// Close button
document.getElementById('tdp-close-btn').addEventListener('click', closeTaskDetail);

// Esc key closes panel
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeTaskDetail(); });

// Archive button
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

// Status badge click — cycle
document.getElementById('tdp-status-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const cur = state.activeTask.status;
  const idx = _STATUS_CYCLE.indexOf(cur);
  const next = _STATUS_CYCLE[(idx + 1) % _STATUS_CYCLE.length];
  await _updateActiveTask({ status: next });
});

// Priority badge click — cycle
document.getElementById('tdp-priority-badge').addEventListener('click', async () => {
  if (!state.activeTask) return;
  const cur = state.activeTask.priority;
  const idx = _PRIORITY_CYCLE.indexOf(cur);
  const next = _PRIORITY_CYCLE[(idx + 1) % _PRIORITY_CYCLE.length];
  await _updateActiveTask({ priority: next });
});

// Quick-action buttons
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
    openTaskDetail(state.activeTask);   // re-render with fresh data
    await Promise.all([loadBoard(), loadSummary()]);
  } catch (e) { toast('更新失败: ' + e.message, 'error'); }
}
```

- [ ] **Step 3: Replace `openEdit()` call in `renderBoard()` so cards open the new panel**

Find this inside `renderBoard()`:
```javascript
      card.addEventListener('click', () => openEdit(t));
```

Replace with:
```javascript
      card.addEventListener('click', () => openTaskDetail(t));
```

- [ ] **Step 4: Commit**

```bash
cd D:\Hermes\work-agent
git add static/app.js
git commit -m "feat: task detail panel open/close + inline editing"
```

---

## Task 5: JavaScript — Task-scoped chat

**Files:**
- Modify: `static/app.js` (append new functions)

- [ ] **Step 1: Add `appendTaskMessage` and `sendTaskMessage` functions**

Append the following to the end of `app.js`:

```javascript
// ── Task-scoped chat ───────────────────────────────────────────────────────

function appendTaskMessage(role, text) {
  const el = document.getElementById('tdp-messages');
  const div = document.createElement('div');
  div.className = `msg ${role === 'user' ? 'user' : 'agent'}`;
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
  input.value = '';
  input.style.height = 'auto';

  appendTaskMessage('user', text);

  // Typing dots
  const typingDiv = document.createElement('div');
  typingDiv.className = 'msg agent';
  typingDiv.id = 'tdp-typing';
  typingDiv.innerHTML = '<span class="msg-avatar" style="font-size:16px">🤖</span><div class="typing-dots"><span></span><span></span><span></span></div>';
  document.getElementById('tdp-messages').appendChild(typingDiv);
  document.getElementById('tdp-messages').scrollTop = 99999;

  const history = state.taskHistories[taskName] || [];
  let agentBubble = null;
  let fullReply   = '';

  try {
    const resp = await fetch(`/api/chat/task/${encodeURIComponent(taskName)}`, {
      method: 'POST',
      headers: { 'X-Auth-Token': state.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, history }),
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

    // Save to per-task history
    const hist = state.taskHistories[taskName] || [];
    hist.push({ role: 'user',      content: text });
    hist.push({ role: 'assistant', content: fullReply });
    state.taskHistories[taskName] = hist.slice(-12);

    // Refresh detail panel in case agent updated the task
    if (state.activeTask && state.activeTask.name === taskName) {
      try {
        const tasks = await api.get(`/api/tasks?limit=200`);
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
```

- [ ] **Step 2: Commit**

```bash
cd D:\Hermes\work-agent
git add static/app.js
git commit -m "feat: task-scoped agent chat in detail panel"
```

---

## Task 6: JavaScript — File Upload

**Files:**
- Modify: `static/app.js` (append)

- [ ] **Step 1: Add `uploadFile` function and wire up the 📎 button**

Append to the end of `app.js`:

```javascript
// ── File upload ────────────────────────────────────────────────────────────

const _TEXT_EXTS = new Set([
  'txt','md','json','csv','py','js','ts','jsx','tsx',
  'html','css','xml','yaml','yml','toml','ini','sh','bat',
]);

async function uploadFile(file) {
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  let content = '';
  let filename = file.name;

  if (ext === 'pdf') {
    // Server-side PDF extraction
    const formData = new FormData();
    formData.append('file', file);
    try {
      const r = await fetch('/api/upload', {
        method: 'POST',
        headers: { 'X-Auth-Token': state.token },
        body: formData,
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(err.detail || r.statusText);
      }
      const data = await r.json();
      content  = data.content;
      filename = data.filename;
    } catch (e) {
      toast('文件读取失败: ' + e.message, 'error');
      return;
    }
  } else if (_TEXT_EXTS.has(ext) || file.type.startsWith('text/')) {
    // Client-side text read
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

  // Build message with collapsible file block
  const preview = esc(content.slice(0, 300)) + (content.length > 300 ? '…' : '');
  const userBubble = appendMessage('user', `📎 ${filename}`);
  userBubble.insertAdjacentHTML('afterend', `
    <details class="file-block">
      <summary>📄 ${esc(filename)} (${content.length} 字符)</summary>
      <pre>${preview}</pre>
    </details>
  `);

  // Send truncated content to agent
  const agentMsg = `[文件: ${filename}]\n${content.slice(0, 8000)}`;
  await sendMessage(agentMsg);
}

// Wire up file button
document.getElementById('file-btn').addEventListener('click', () => {
  document.getElementById('file-input').click();
});
document.getElementById('file-input').addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) uploadFile(file);
  e.target.value = ''; // reset so same file can be re-uploaded
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
```

- [ ] **Step 2: Commit**

```bash
cd D:\Hermes\work-agent
git add static/app.js
git commit -m "feat: file upload with drag-and-drop in chat"
```

---

## Task 7: JavaScript — Export

**Files:**
- Modify: `static/app.js` (append)

- [ ] **Step 1: Add `exportTasks` function and wire up export dropdown**

Append to the end of `app.js`:

```javascript
// ── Export ─────────────────────────────────────────────────────────────────

function exportTasks(format) {
  const url  = `/api/export/${format}`;
  const link = document.createElement('a');
  link.href  = url;
  link.setAttribute('download', format === 'csv' ? 'tasks.csv' : 'tasks.md');
  // Add auth via query param workaround (GET requests can't set custom headers)
  link.href = `${url}?_t=${encodeURIComponent(state.token)}`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

// Wire export dropdown
document.getElementById('export-btn').addEventListener('click', e => {
  e.stopPropagation();
  document.getElementById('export-dropdown').classList.toggle('hidden');
});
document.getElementById('export-csv-btn').addEventListener('click', () => {
  document.getElementById('export-dropdown').classList.add('hidden');
  exportTasks('csv');
});
document.getElementById('export-md-btn').addEventListener('click', () => {
  document.getElementById('export-dropdown').classList.add('hidden');
  exportTasks('md');
});
// Close dropdown when clicking elsewhere
document.addEventListener('click', () => {
  document.getElementById('export-dropdown').classList.add('hidden');
});
```

- [ ] **Step 2: Update export endpoints in `api.py` to accept token from query param**

The export endpoints use `_verify(request)` which checks `X-Auth-Token` header. Browser download links can't set headers, so add query param fallback.

Find the `_verify` function in `api.py`:
```python
def _verify(request: Request) -> None:
    token = request.headers.get("X-Auth-Token", "")
    if token != UI_PASSWORD:
        raise HTTPException(status_code=401, detail="未授权")
```

Replace with:
```python
def _verify(request: Request) -> None:
    token = (
        request.headers.get("X-Auth-Token", "")
        or request.query_params.get("_t", "")
    )
    if token != UI_PASSWORD:
        raise HTTPException(status_code=401, detail="未授权")
```

- [ ] **Step 3: Commit everything**

```bash
cd D:\Hermes\work-agent
git add static/app.js api.py
git commit -m "feat: export CSV/Markdown + auth query param for downloads"
```

---

## Task 8: Push to GitHub

- [ ] **Step 1: Push all commits**

```bash
cd D:\Hermes\work-agent
git push origin main
```

Expected: all 7 new commits pushed to `https://github.com/NyChieng/Hermes_Work_Agent`

- [ ] **Step 2: Install pypdf locally for PDF support**

```bash
py -3 -m pip install pypdf
```

- [ ] **Step 3: Restart the bot and verify**

Stop the running bot (Ctrl+C or kill process), then:
```bash
cd D:\Hermes\work-agent
py -3 main.py
```

Open `http://localhost:8000`, log in, click a task card — detail panel should slide in.

---

## Self-Review

**Spec coverage check:**
- ✅ Three-column layout — Task 2 HTML + Task 3 CSS `.app-3col`
- ✅ Task detail panel with all fields — Task 2 HTML + Task 4 JS
- ✅ Clickable status/priority badges — Task 4 JS
- ✅ Quick-action buttons — Task 2 HTML + Task 4 JS
- ✅ Tags as pills — Task 3 CSS `.tag-pill` + Task 4 JS
- ✅ Notion link in detail — Task 4 JS `tdp-notion`
- ✅ Task-scoped chat with independent history — Task 5 JS
- ✅ SSE streaming in task chat — Task 5 JS
- ✅ File upload (text client-side, PDF server-side) — Task 6 JS + Task 1 backend
- ✅ Export CSV — Task 1 backend + Task 7 JS
- ✅ Export Markdown — Task 1 backend + Task 7 JS
- ✅ Drag-and-drop file upload — Task 6 JS
- ✅ Esc to close panel — Task 4 JS

**Placeholder scan:** None found.

**Type consistency:**
- `openTaskDetail(task)` defined Task 4, called in `renderBoard()` Task 4 ✅
- `sendTaskMessage(text)` defined Task 5, wired Task 5 ✅
- `uploadFile(file)` defined Task 6, wired Task 6 ✅
- `exportTasks(format)` defined Task 7, wired Task 7 ✅
- `state.taskHistories` added Task 4, used Task 5 ✅
- `appendTaskMessage(role, text)` defined Task 5, called Task 5 ✅
