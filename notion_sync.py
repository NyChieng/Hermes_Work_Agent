"""
Notion 双向同步。

方向 A（推送）：SQLite → Notion，每次写操作后在后台线程执行。
方向 B（拉取）：Notion → SQLite，每 5 分钟由调度器轮询。
冲突规则：以最新修改时间戳的一方为准。

所有 HTTP 调用带指数退避重试（最多3次），避免网络抖动导致同步失败无提示。
"""

import logging
import os
import time
from datetime import datetime

import httpx

from db import _now, _today, get_conn, get_notion_ids, init_db, save_notion_ids

logger = logging.getLogger(__name__)

_BASE = "https://api.notion.com/v1"
_VER  = "2022-06-28"


# ── HTTP 工具 ─────────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = os.getenv("NOTION_TOKEN", "")
    return {
        "Authorization":  f"Bearer {token}",
        "Notion-Version": _VER,
        "Content-Type":   "application/json",
    }


def _notion_ok() -> bool:
    if not os.getenv("NOTION_TOKEN") or not os.getenv("NOTION_PARENT_PAGE_ID"):
        logger.debug("Notion 凭据未配置，跳过同步")
        return False
    return True


def _get(path: str, **kwargs) -> dict | None:
    """GET 请求，最多重试3次（指数退避）。"""
    for attempt in range(3):
        try:
            r = httpx.get(f"{_BASE}{path}", headers=_headers(), timeout=15, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt < 2:
                wait = 2 ** attempt
                logger.debug("Notion GET 第%d次重试（等待%ds）: %s", attempt + 2, wait, exc)
                time.sleep(wait)
            else:
                logger.warning("Notion GET %s 失败（已重试3次）: %s", path, exc)
    return None


def _post(path: str, payload: dict) -> dict | None:
    """POST 请求，最多重试3次（指数退避）。"""
    for attempt in range(3):
        try:
            r = httpx.post(f"{_BASE}{path}", headers=_headers(), json=payload, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt < 2:
                wait = 2 ** attempt
                logger.debug("Notion POST 第%d次重试（等待%ds）: %s", attempt + 2, wait, exc)
                time.sleep(wait)
            else:
                logger.warning("Notion POST %s 失败（已重试3次）: %s", path, exc)
    return None


def _patch(path: str, payload: dict) -> dict | None:
    """PATCH 请求，最多重试3次（指数退避）。"""
    for attempt in range(3):
        try:
            r = httpx.patch(f"{_BASE}{path}", headers=_headers(), json=payload, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            if attempt < 2:
                wait = 2 ** attempt
                logger.debug("Notion PATCH 第%d次重试（等待%ds）: %s", attempt + 2, wait, exc)
                time.sleep(wait)
            else:
                logger.warning("Notion PATCH %s 失败（已重试3次）: %s", path, exc)
    return None


# ── 属性构建器 ────────────────────────────────────────────────────────────────

def _title_prop(text: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": text}}]}


def _select_prop(value: str) -> dict:
    return {"select": {"name": value}}


def _rich_text_prop(text: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}


def _multi_select_prop(csv: str) -> dict:
    names = [t.strip() for t in csv.split(",") if t.strip()]
    return {"multi_select": [{"name": n[:100]} for n in names]}


def _date_prop(iso_str: str) -> dict:
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%d %H:%M")
        return {"date": {"start": dt.strftime("%Y-%m-%dT%H:%M:%S")}}
    except Exception:
        return {"date": {"start": _today()}}


def _task_properties(task: dict) -> dict:
    return {
        "Name":     _title_prop(task["name"]),
        "Status":   _select_prop(task["status"]),
        "Priority": _select_prop(task["priority"]),
        "Notes":    _rich_text_prop(task.get("notes") or ""),
        "Tags":     _multi_select_prop(task.get("tags") or ""),
        "Updated":  _date_prop(task.get("updated") or _now()),
    }


# ── Notion 页面解析 ───────────────────────────────────────────────────────────

def _norm_page_id(raw: str) -> str:
    s = raw.replace("-", "")
    if len(s) != 32:
        return raw
    return f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"


def _parse_select(props: dict, key: str) -> str:
    sel = props.get(key, {}).get("select")
    return sel["name"] if sel else ""


def _parse_rich_text(props: dict, key: str) -> str:
    items = props.get(key, {}).get("rich_text", [])
    return "".join(i.get("text", {}).get("content", "") for i in items)


def _parse_multi_select(props: dict, key: str) -> str:
    items = props.get(key, {}).get("multi_select", [])
    return ",".join(i["name"] for i in items)


def _parse_title(props: dict) -> str:
    items = props.get("Name", {}).get("title", [])
    return "".join(i.get("text", {}).get("content", "") for i in items)


def _notion_ts_to_local(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        local = dt.replace(tzinfo=None)
        return local.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


# ── 首次初始化 ────────────────────────────────────────────────────────────────

def setup_notion() -> str:
    """
    在 NOTION_PARENT_PAGE_ID 下创建 '工作进度追踪' 数据库。
    将新 db_id 存入 agent_state，返回页面 URL 或错误信息。
    """
    if not _notion_ok():
        return "Notion 凭据未配置。请先填写 NOTION_TOKEN 和 NOTION_PARENT_PAGE_ID。"

    parent_raw = os.getenv("NOTION_PARENT_PAGE_ID", "")
    parent_id  = _norm_page_id(parent_raw.strip())

    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "title":  [{"type": "text", "text": {"content": "工作进度追踪"}}],
        "properties": {
            "Name":     {"title": {}},
            "Status":   {"select": {"options": [
                {"name": "todo",        "color": "gray"},
                {"name": "in_progress", "color": "yellow"},
                {"name": "done",        "color": "green"},
                {"name": "blocked",     "color": "red"},
                {"name": "archived",    "color": "default"},
            ]}},
            "Priority": {"select": {"options": [
                {"name": "high",   "color": "red"},
                {"name": "medium", "color": "yellow"},
                {"name": "low",    "color": "blue"},
            ]}},
            "Notes":    {"rich_text": {}},
            "Tags":     {"multi_select": {}},
            "Updated":  {"date": {}},
        },
    }

    result = _post("/databases", payload)
    if not result:
        return "Notion 数据库创建失败，请查看日志。"

    db_id   = result.get("id", "")
    url     = result.get("url", "https://notion.so")
    save_notion_ids(db_id, db_id)
    logger.info("Notion 数据库已创建: %s", url)
    return url


# ── 推送：SQLite → Notion ─────────────────────────────────────────────────────

def push_task_to_notion(task: dict) -> str:
    """
    创建或更新单个任务对应的 Notion 页面。
    返回 notion_id（失败时返回空字符串）。
    """
    if not _notion_ok():
        return ""

    db_id, _ = get_notion_ids()
    if not db_id:
        logger.debug("Notion DB 未初始化，跳过推送")
        return ""

    props     = _task_properties(task)
    notion_id = task.get("notion_id") or ""

    if notion_id:
        result = _patch(f"/pages/{notion_id}", {"properties": props})
    else:
        result = _post("/pages", {
            "parent":     {"database_id": db_id},
            "properties": props,
        })

    if not result:
        return ""

    new_id = result.get("id", "")
    if new_id and new_id != notion_id:
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE tasks SET notion_id=?, last_synced=? WHERE name=?",
                    (new_id, _now(), task["name"]),
                )
        except Exception as exc:
            logger.warning("回写 notion_id 失败: %s", exc)

    return new_id


def push_all_to_notion() -> int:
    """批量推送所有非归档任务到 Notion（首次同步用）。返回成功推送数。"""
    if not _notion_ok():
        return 0

    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status != 'archived'"
        ).fetchall()

    pushed = 0
    for row in rows:
        task = dict(row)
        nid  = push_task_to_notion(task)
        if nid:
            pushed += 1
    logger.info("批量推送完成: %d/%d", pushed, len(rows))
    return pushed


# ── 拉取：Notion → SQLite ─────────────────────────────────────────────────────

def pull_from_notion() -> int:
    """
    拉取 Notion 数据库中的所有页面，按时间戳冲突规则更新 SQLite。
    返回更新/新增的记录数。
    """
    if not _notion_ok():
        return 0

    db_id, _ = get_notion_ids()
    if not db_id:
        return 0

    pages: list[dict] = []
    cursor = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        result = _post(f"/databases/{db_id}/query", body)
        if not result:
            break
        pages.extend(result.get("results", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor")

    if not pages:
        return 0

    updated = 0
    init_db()
    for page in pages:
        try:
            updated += _apply_notion_page(page)
        except Exception as exc:
            logger.warning("处理 Notion 页面失败: %s", exc)

    if updated:
        from cache import _refresh_cache
        _refresh_cache()
        logger.info("Notion → SQLite: 更新了 %d 个任务", updated)

    return updated


def _apply_notion_page(page: dict) -> int:
    """将一个 Notion 页面应用到 SQLite，有变化返回1，否则返回0。"""
    props     = page.get("properties", {})
    notion_id = page.get("id", "")
    name      = _parse_title(props).strip()
    if not name:
        return 0

    notion_edited_raw = page.get("last_edited_time", "")
    notion_edited     = _notion_ts_to_local(notion_edited_raw)

    status   = _parse_select(props, "Status")   or "todo"
    priority = _parse_select(props, "Priority") or "medium"
    notes    = _parse_rich_text(props, "Notes")
    tags     = _parse_multi_select(props, "Tags")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE notion_id=?", (notion_id,)
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM tasks WHERE name=?", (name,)
            ).fetchone()

        if row is None:
            now = _now()
            conn.execute(
                """
                INSERT INTO tasks
                    (name, status, priority, notes, tags, notion_id, last_synced, created, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, status, priority, notes, tags, notion_id, now, now, now),
            )
            return 1

        sqlite_updated = row["updated"] or ""
        if notion_edited and notion_edited > sqlite_updated:
            conn.execute(
                """
                UPDATE tasks SET
                    status=?, priority=?, notes=?, tags=?,
                    notion_id=?, last_synced=?, updated=?
                WHERE id=?
                """,
                (status, priority, notes, tags, notion_id, _now(), notion_edited, row["id"]),
            )
            return 1

    return 0
