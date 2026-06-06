"""
Scheduled background tasks (runs in a daemon thread).

Jobs:
  09:00  → push morning report to Telegram
  21:00  → push evening report to Telegram + record today's snapshot
  every 5 min → poll Notion → SQLite
"""

import logging
import threading
import time

import schedule

logger = logging.getLogger(__name__)


# ── jobs ──────────────────────────────────────────────────────────────────────

def _morning_job() -> None:
    try:
        from notifier import build_morning_report, send_message
        ok = send_message(build_morning_report())
        logger.info("早报推送 %s", "✅" if ok else "❌")
    except Exception:
        logger.exception("早报推送异常")


def _evening_job() -> None:
    try:
        from notifier import build_evening_report, send_message
        ok = send_message(build_evening_report())
        logger.info("晚报推送 %s", "✅" if ok else "❌")
    except Exception:
        logger.exception("晚报推送异常")

    # Record today's snapshot in daily_log after the evening report
    try:
        from cache import get_cached_summary
        from db import get_mood
        from memory import generate_daily_note, record_today

        s    = get_cached_summary()
        total = s["total"] or 0
        done  = s["done"]  or 0
        rate  = done / total if total > 0 else 0.0

        # Count tasks added today
        from db import _today, get_conn
        with get_conn() as conn:
            added = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE created LIKE ?",
                (f"{_today()}%",),
            ).fetchone()[0]

        note = generate_daily_note(rate)
        record_today(
            tasks_done=done,
            tasks_added=added,
            completion_rate=rate,
            mood=get_mood(),
            note=note,
        )
        logger.info("今日快照已记录 (done=%d, rate=%.0f%%)", done, rate * 100)
    except Exception:
        logger.exception("记录今日快照异常")


def _notion_pull_job() -> None:
    try:
        from notion_sync import pull_from_notion
        updated = pull_from_notion()
        if updated:
            logger.info("Notion → SQLite: 更新 %d 个任务", updated)
    except Exception:
        logger.exception("Notion 轮询异常")


# ── scheduler loop ────────────────────────────────────────────────────────────

def _loop() -> None:
    schedule.every().day.at("09:00").do(_morning_job)
    schedule.every().day.at("21:00").do(_evening_job)
    schedule.every(5).minutes.do(_notion_pull_job)

    logger.info("定时任务已注册：09:00 早报 | 21:00 晚报 | 每 5 分钟 Notion 轮询")
    while True:
        schedule.run_pending()
        time.sleep(30)


def start_background_scheduler() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="scheduler")
    t.start()
    return t


# ── manual triggers (for testing / Telegram /sync) ───────────────────────────

def trigger_morning_now() -> None:
    _morning_job()


def trigger_evening_now() -> None:
    _evening_job()


def trigger_notion_pull_now() -> int:
    """Synchronous full pull. Returns count of changes."""
    try:
        from notion_sync import pull_from_notion
        return pull_from_notion()
    except Exception as exc:
        logger.exception("手动 Notion 轮询失败: %s", exc)
        return 0


def trigger_notion_push_all() -> int:
    """Synchronous full push. Returns count of tasks pushed."""
    try:
        from notion_sync import push_all_to_notion
        return push_all_to_notion()
    except Exception as exc:
        logger.exception("手动 Notion 全量推送失败: %s", exc)
        return 0
