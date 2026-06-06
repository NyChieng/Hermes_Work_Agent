"""
Agent 可用的 6 个工具。

每次写操作：
  1. 调用 _refresh_cache() 保持进程内摘要最新。
  2. 后台线程推送 Notion，不阻塞 agent 回复。
"""

import threading

from cache import _refresh_cache, get_cached_summary
from db import _now, get_conn, init_db

_STATUS   = {"todo", "in_progress", "done", "blocked"}
_PRIORITY = {"high", "medium", "low"}


# ── Notion 异步推送 ───────────────────────────────────────────────────────────

def _push_async(task: dict) -> None:
    """在后台线程将单个任务推送到 Notion（fire-and-forget）。"""
    def _worker():
        try:
            from notion_sync import push_task_to_notion
            push_task_to_notion(task)
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


# ── DB 工具函数 ────────────────────────────────────────────────────────────────

def _find_task(conn, name: str):
    """先精确匹配，再 LIKE 模糊匹配。返回 sqlite3.Row 或 None。"""
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


# ── 公开工具 ──────────────────────────────────────────────────────────────────

def get_summary() -> dict:
    """返回缓存的进度摘要（约 80 tokens）。"""
    return get_cached_summary()


def query_task(keyword: str) -> list[dict]:
    """
    按关键词在任务名称、标签、备注中全文搜索。
    最多返回 20 条非归档任务，按优先级和更新时间排序。
    """
    init_db()
    pat = f"%{keyword}%"
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, name, status, priority, notes, tags, deadline, updated
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
    deadline: str = "",
) -> dict:
    """
    新增任务。deadline 格式为 YYYY-MM-DD（可为空）。
    返回创建的任务字典，名称重复时返回 {"error": ...}。
    """
    init_db()
    if priority not in _PRIORITY:
        priority = "medium"
    now = _now()
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO tasks (name, status, priority, notes, tags, deadline, created, updated)
                VALUES (?, 'todo', ?, ?, ?, ?, ?, ?)
                """,
                (name, priority, notes, tags, deadline or "", now, now),
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
    deadline: str | None = None,
) -> dict:
    """
    局部更新任务，只传需要修改的字段。支持模糊名称匹配。
    找不到任务时自动创建。
    """
    init_db()
    with get_conn() as conn:
        row = _find_task(conn, name)

        if row is None:
            now = _now()
            conn.execute(
                """
                INSERT INTO tasks (name, status, priority, notes, tags, deadline, created, updated)
                VALUES (?, ?, ?, ?, '', ?, ?, ?)
                """,
                (
                    name,
                    status   if status   in _STATUS   else "todo",
                    priority if priority in _PRIORITY else "medium",
                    notes or "",
                    deadline or "",
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
        new_deadline = deadline if deadline is not None  else (row["deadline"] if "deadline" in row.keys() else "")

        conn.execute(
            "UPDATE tasks SET status=?, priority=?, notes=?, deadline=?, updated=? WHERE name=?",
            (new_status, new_priority, new_notes, new_deadline, _now(), task_name),
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
    按优先级和紧急程度返回任务列表，支持按状态/优先级过滤。
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
            SELECT id, name, status, priority, notes, tags, deadline, updated
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
    """软删除：把任务状态改为 'archived'，支持模糊名称匹配。"""
    init_db()
    with get_conn() as conn:
        row = _find_task(conn, name)
        if row is None:
            return {"error": f"找不到任务 '{name}'"}
        conn.execute(
            "UPDATE tasks SET status='archived', updated=? WHERE name=?",
            (_now(), row["name"]),
        )
        result = _row(conn, row["name"])

    _refresh_cache()
    _push_async(result)
    return {"archived": row["name"], "message": f"任务 '{row['name']}' 已归档"}
