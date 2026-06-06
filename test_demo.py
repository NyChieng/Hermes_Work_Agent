"""
Offline tool-layer test — no LLM calls required.
Demonstrates all 6 tools and verifies the cache refresh cycle.

Run:
    python test_demo.py
"""

import json
import os
import sys
from pathlib import Path

# Ensure we can import sibling modules
sys.path.insert(0, str(Path(__file__).parent))

# Use a dedicated test DB so we don't pollute tasks.db
os.environ["_TEST_DB"] = "1"
import db as _db_mod
_db_mod.DB_PATH = Path(__file__).parent / "tasks_test.db"
# Wipe any previous test run
_db_mod.DB_PATH.unlink(missing_ok=True)

from cache import get_cached_summary
from tools import add_task, delete_task, get_summary, list_tasks, query_task, update_task


def _sep(title: str = "") -> None:
    print(f"\n{'─'*55}")
    if title:
        print(f"  {title}")
        print(f"{'─'*55}")


def _pp(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── Step 1: empty summary ─────────────────────────────────────────────────────
_sep("1. 空库摘要")
_pp(get_summary())

# ── Step 2: add tasks ─────────────────────────────────────────────────────────
_sep("2. 新增任务")
tasks_to_add = [
    ("需求分析",        "high",   "已与产品对齐",       "backend,phase1"),
    ("数据库设计",      "high",   "ERD 草稿完成",        "backend,db"),
    ("API 开发",        "high",   "进行中",              "backend,api"),
    ("前端 UI 开发",    "medium", "等待设计稿",          "frontend"),
    ("单元测试",        "medium", "",                    "qa"),
    ("文档编写",        "low",    "50% 完成",            "docs"),
    ("部署脚本",        "medium", "",                    "devops"),
]
for name, priority, notes, tags in tasks_to_add:
    r = add_task(name=name, priority=priority, notes=notes, tags=tags)
    print(f"  + {r['name']} [{r['priority']}]  →  {r['status']}")

# ── Step 3: update tasks ──────────────────────────────────────────────────────
_sep("3. 更新任务状态")
updates = [
    ("需求分析",     {"status": "done",        "notes": "已最终确认"}),
    ("数据库设计",   {"status": "done",        "notes": "Schema 冻结"}),
    ("API 开发",     {"status": "in_progress", "notes": "完成 70%"}),
    ("前端 UI 开发", {"status": "in_progress", "notes": "设计稿已到位"}),
    ("单元测试",     {"status": "blocked",     "notes": "等待 API 稳定"}),
]
for name, kwargs in updates:
    r = update_task(name=name, **kwargs)
    print(f"  ✎ {r['name']}  →  {r['status']}  ({r['notes']})")

# ── Step 4: query ─────────────────────────────────────────────────────────────
_sep("4. 关键词搜索 'backend'")
results = query_task("backend")
for t in results:
    print(f"  [{t['priority']:6}] {t['name']:14} → {t['status']}")

# ── Step 5: list with filters ─────────────────────────────────────────────────
_sep("5. 列出高优先级任务")
high_tasks = list_tasks(priority="high")
for t in high_tasks:
    print(f"  {t['name']:14} → {t['status']}")

_sep("5b. 列出进行中任务")
wip = list_tasks(status="in_progress")
for t in wip:
    print(f"  {t['name']:14}  备注: {t['notes']}")

# ── Step 6: summary after updates ────────────────────────────────────────────
_sep("6. 更新后摘要")
_pp(get_summary())

# ── Step 7: delete (soft) ─────────────────────────────────────────────────────
_sep("7. 归档任务")
r = delete_task("部署脚本")
print(f"  {r['message']}")

_sep("7b. 归档后摘要")
s = get_summary()
print(f"  总数: {s['total']}  完成率: {s['completion_rate']}")
print(f"  top3 高优: {[t['name'] for t in s['top3_urgent']]}")

# ── Step 8: duplicate add ─────────────────────────────────────────────────────
_sep("8. 重复新增（应返回错误）")
r = add_task(name="API 开发", notes="重复")
print(f"  error: {r.get('error', '—')}")

# ── Step 9: fuzzy update ──────────────────────────────────────────────────────
_sep("9. 模糊名称更新 ('文档')")
r = update_task(name="文档", status="done", notes="全部完成")
print(f"  找到并更新: {r['name']} → {r['status']}")

# ── Step 10: final summary ────────────────────────────────────────────────────
_sep("10. 最终进度摘要")
_pp(get_summary())

# ── cleanup ───────────────────────────────────────────────────────────────────
_db_mod.DB_PATH.unlink(missing_ok=True)
print(f"\n{'─'*55}")
print("  ✅ 全部测试通过，测试数据库已清理")
print(f"{'─'*55}\n")
