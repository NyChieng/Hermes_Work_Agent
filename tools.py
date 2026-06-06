"""
6 tools exposed to the agent.

Every write operation:
  1. Calls _refresh_cache() — keeps the in-process summary current.
  2. Spawns a daemon thread to push the task to Notion asynchronously
     so the agent reply is never delayed by a Notion API round-trip.
"""

import threading

from cache import _refresh_cache, get_cached_summary
from db import _now, get_conn, init_db

_STATUS   = {"todo", "in_progress", "done", "blocked"}
_PRIORITY = {"high", "medium", "low"}


# ── Notion push (fire-and-forget) ─────────────────────────────────────────────

def _push_async(task: dict) -> None:
    """Push one task to Notion in a background thread."""
    def _worker():
        try:
            from notion_sync import push_task_to_notion
            push_task_to_notion(task)
        except Exception:
            pass  # Notion sync is best-effort; never crash the agent
    threading.Thread(target=_worker, daemon=True).start()


# ── DB helpers ────────────────────────────────────────────────────────────────

def _find_task(conn, name: str):
    """Exact match first, then LIKE fallback. Returns sqlite3.Row or None."""
    row = conn.execute(
        "SELECT * FROM tasks WHERE name = ? AND status != 'archived'", (name,)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM tasks WHERE name LIKE ? AND status != 'archived'",
            (f"%{name}%",),
        ).fetchone()
    return row


def _row(conn, name: str) -> dict:
    return dict(conn.execute("SELECT * FROM tasks WHERE name = ?", (name,)).fetchone())


# ── public tools ──────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """
    Return cached progress summary (~80 tokens).
    """
    return get_cached_summary()


def query_task(keyword: str) -> list[dict]:
    """
    Full-text search across name, tags, and notes.
    Returns up to 20 non-archived matching tasks.
    """
    init_db()
    pat = f"%{keyword}%"
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, status, priority, notes, tags, updated
            FROM tasks
            WHERE status != 'archived'
              AND (name LIKE ? OR tags LIKE ? OR notes LIKE ?)
            ORDER BY
                CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                updated DESC
            LIMIT 20
            """,
            (pat, pat, pat),
        ).fetchall()
    return [dict(r) for r in rows]


def add_task(
    name: str,
    priority: str = "medium",
    notes: str = "",
    tags: str = "",
) -> dict:
    """
    Insert a new task.
    Returns the created task dict, or {"error": ...} if name already exists.
    """
    init_db()
    if priority not in _PRIORITY:
        priority = "medium"
    now = _now()
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks (name, status, priority, notes, tags, created, updated)
                VALUES (?, 'todo', ?, ?, ?, ?, ?)
                """,
                (name, priority, notes, tags, now, now),
            )
            result = _row(conn, name)
    except Exception as exc:
        return {"error": str(exc)}

    _refresh_cache()
    _push_async(result)
    return result


def update_task(
    name: str,
    status: str | None = None,
    notes: str | None = None,
    priority: str | None = None,
) -> dict:
    """
    Partial update — pass only the fields you want to change.
    Fuzzy-matches on name. Auto-creates if not found.
    """
    init_db()
    with get_conn() as conn:
        row = _find_task(conn, name)

        if row is None:
            now = _now()
            conn.execute(
                """
                INSERT INTO tasks (name, status, priority, notes, tags, created, updated)
                VALUES (?, ?, ?, ?, '', ?, ?)
                """,
                (
                    name,
                    status   if status   in _STATUS   else "todo",
                    priority if priority in _PRIORITY else "medium",
                    notes or "",
                    now, now,
                ),
            )
            result = _row(conn, name)
            _refresh_cache()
            _push_async(result)
            return {**result, "_created": True}

        task_name    = row["name"]
        new_status   = status   if status   in _STATUS   else row["status"]
        new_priority = priority if priority in _PRIORITY else row["priority"]
        new_notes    = notes    if notes    is not None  else row["notes"]

        conn.execute(
            "UPDATE tasks SET status=?, priority=?, notes=?, updated=? WHERE name=?",
            (new_status, new_priority, new_notes, _now(), task_name),
        )
        result = _row(conn, task_name)

    _refresh_cache()
    _push_async(result)
    return result


def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Return tasks ordered by priority then urgency.
    """
    init_db()
    conditions = ["status != 'archived'"]
    params: list = []

    if status and status in _STATUS:
        conditions.append("status = ?")
        params.append(status)
    if priority and priority in _PRIORITY:
        conditions.append("priority = ?")
        params.append(priority)

    params.append(min(limit, 50))
    where = " AND ".join(conditions)

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, name, status, priority, notes, tags, updated
            FROM tasks
            WHERE {where}
            ORDER BY
                CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                CASE status   WHEN 'blocked'     THEN 1
                               WHEN 'in_progress' THEN 2
                               WHEN 'todo'        THEN 3
                               ELSE 4 END,
                updated DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def delete_task(name: str) -> dict:
    """
    Soft-delete: set status to 'archived'. Fuzzy name match.
    """
    init_db()
    with get_conn() as conn:
        row = _find_task(conn, name)
        if row is None:
            return {"error": f"Task '{name}' not found"}
        conn.execute(
            "UPDATE tasks SET status='archived', updated=? WHERE name=?",
            (_now(), row["name"]),
        )
        result = _row(conn, row["name"])

    _refresh_cache()
    _push_async(result)
    return {"archived": row["name"], "message": f"任务 '{row['name']}' 已归档"}
