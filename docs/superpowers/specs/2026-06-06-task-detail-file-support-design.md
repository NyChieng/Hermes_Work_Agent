# Design: Task Detail Panel + File Support

**Date:** 2026-06-06  
**Status:** Approved

---

## Overview

Two features added to the existing Web UI:

1. **Task Detail Panel** — three-column layout where clicking a task opens a full detail view with an independent agent chat scoped to that task.
2. **File Support** — upload files to extract tasks, export task list as CSV or Markdown.

---

## 1. Layout

### Three-Column Layout

```
┌──────────────┬──────────────────┬─────────────────────┐
│  Task Board  │   Main Chat      │   Task Detail        │
│  (30%)       │   (40%)          │   (30%)              │
└──────────────┴──────────────────┴─────────────────────┘
```

- **Default state:** two columns (board + chat). Right panel hidden.
- **On task card click:** right panel slides in from right; left panel narrows to make room.
- **Close:** `Esc` key or `✕` button. Right panel slides out, layout returns to two columns.
- **Narrow screens (<900px):** right panel overlays on top of chat (full width).

---

## 2. Task Detail Panel

### Header
- Task name — click to edit inline (blur to save via `PATCH /api/tasks/{name}`)
- `[归档]` button — calls `DELETE /api/tasks/{name}`
- `✕` close button

### Status & Priority
- Colored status badge — click cycles through: `todo → in_progress → done → blocked → todo`
- Priority badge — click cycles: `low → medium → high → low`
- Both trigger `PATCH /api/tasks/{name}` immediately on click

### Quick-action buttons
Four buttons in a row: `⬜ Todo` `🟡 进行中` `✅ 完成` `🔴 阻塞`  
Clicking any sets that status directly. Active button is highlighted.

### Details section
- Tags displayed as colored pills (parsed from comma-separated `tags` field)
- Full `notes` text (not truncated)
- `🕐 更新: YYYY-MM-DD HH:MM`
- `🔗 Notion` — shows "已同步" with link if `notion_id` is set, "未同步" otherwise

### Task-scoped Agent Chat
- Independent message history per task (keyed by task name, stored in `state.taskHistories`)
- System context pre-loads current task data: name, status, priority, notes, tags
- Agent can call all 6 tools normally — updates to this task reflect immediately in the detail panel
- Full-height scrollable message area, same SSE streaming as main chat
- Input: textarea + send button, `Enter` to send, `Shift+Enter` for newline

---

## 3. File Support

### Upload (📎 button in main chat input area)

**Supported formats:**
| Format | Processing |
|--------|-----------|
| `.txt` `.md` `.json` `.csv` `.py` `.js` (and other text) | Read client-side via `FileReader` |
| `.pdf` | POST to `/api/upload`, server extracts text |

**Flow:**
1. User clicks 📎 → file picker opens
2. File read → content shown as collapsible `<details>` block in chat
3. Agent receives: `[文件: filename.ext]\n<content up to 8000 chars>`
4. Agent responds — typically creates tasks or adds notes

**Error handling:** unsupported binary files show toast "不支持此格式，请上传文本文件或 PDF"

### Export (📥 button in board footer, opens dropdown)

| Option | Endpoint | Output |
|--------|----------|--------|
| 下载 CSV | `GET /api/export/csv` | `tasks.csv` — columns: name, status, priority, notes, tags, updated |
| 下载 Markdown | `GET /api/export/md` | `tasks.md` — grouped by status with checkboxes |

---

## 4. Backend Changes (api.py)

### New endpoints

**`POST /api/upload`**
- Accepts `multipart/form-data` with `file` field
- Returns `{ filename, content }` (content capped at 8000 chars)
- PDF: uses `pypdf` if installed; falls back to error message if not
- Auth: `X-Auth-Token` required

**`GET /api/export/csv`**
- Returns `text/csv` with `Content-Disposition: attachment; filename=tasks.csv`
- Includes all non-archived tasks
- Auth: `X-Auth-Token` required

**`GET /api/export/md`**
- Returns `text/markdown` with `Content-Disposition: attachment; filename=tasks.md`
- Groups tasks by status with emoji headers and `- [ ]` / `- [x]` checkboxes
- Auth: `X-Auth-Token` required

**`POST /api/chat/task/{task_name}`**
- Same as `/api/chat` but prepends task context to the message
- Body: `{ message, history }`
- Injects task data into user message: `[任务上下文: name=..., status=..., notes=...]`
- Returns SSE stream identical to `/api/chat`
- Auth: `X-Auth-Token` required

---

## 5. Frontend Changes

### index.html
- Wrap existing two-column layout in a flex container that supports three columns
- Add task detail panel `<div id="task-detail-panel">` with all sub-sections
- Add file input `<input type="file" id="file-input" hidden>` + 📎 button
- Add export dropdown in board footer

### style.css
- `.three-col` layout class (activated when detail panel is open)
- `.task-detail-panel` — slide-in animation, full height, scrollable
- `.tag-pill` — colored pill for tags
- `.status-badge` — clickable, color per status
- `.quick-actions` — 4-button row
- `.file-block` — collapsible file content preview in chat
- `.export-dropdown` — small dropdown above the 📥 button

### app.js
- `openTaskDetail(task)` — populates detail panel, loads task history, slides panel in
- `closeTaskDetail()` — slides panel out, resets layout
- `sendTaskMessage(taskName, text)` — SSE chat scoped to task, hits `/api/chat/task/{name}`
- `uploadFile(file)` — reads text client-side or POSTs to `/api/upload` for PDF
- `exportTasks(format)` — triggers download from `/api/export/csv` or `/api/export/md`
- `state.taskHistories` — `{ [taskName]: [{role, content}] }` — per-task chat history

---

## 6. What Does NOT Change

- `agent.py`, `tools.py`, `db.py`, `cache.py`, `memory.py`, `prompts.py`
- `notifier.py`, `telegram_bot.py`, `scheduler.py`, `notion_sync.py`
- Existing `/api/chat`, `/api/tasks`, `/api/summary` endpoints (unchanged)

---

## 7. Dependencies

- `pypdf` (optional, for PDF extraction) — add to `requirements.txt`
- All other changes use existing dependencies
