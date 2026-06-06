"""
后台定时任务（在 daemon 线程里跑）。

已注册的任务：
  09:00        → 早报推送 Telegram
  21:00        → 晚报推送 Telegram + 记录今日快照
  每小时       → 检查截止日期提醒
  每周日 21:00 → 生成并推送周报
  每 5 分钟    → Notion → SQLite 轮询
"""

import logging
import threading
import time
from datetime import datetime, timedelta

import schedule

logger = logging.getLogger(__name__)


# ── 定时任务 ───────────────────────────────────────────────────────────────────

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

    try:
        from cache import get_cached_summary
        from db import _today, get_conn, get_mood
        from memory import generate_daily_note, record_today

        s     = get_cached_summary()
        total = s["total"] or 0
        done  = s["done"]  or 0
        rate  = done / total if total > 0 else 0.0

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


def check_deadlines() -> None:
    """
    检查截止日期提醒，通过 Telegram 推送：
    - deadline 在未来 24 小时内且未完成 → 发一次提醒
    - deadline 在未来 1 小时内且未完成  → 发紧急提醒
    由调度器每小时触发一次。
    """
    try:
        from db import get_conn, get_mood, init_db
        from notifier import send_message

        init_db()
        now   = datetime.now()
        in_1h = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        in_24h= (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        today_str = now.strftime("%Y-%m-%d")

        with get_conn() as conn:
            urgent_rows = conn.execute(
                """
                SELECT name, deadline FROM tasks
                WHERE deadline != ''
                  AND deadline <= ?
                  AND deadline >= ?
                  AND status NOT IN ('done', 'archived')
                ORDER BY deadline ASC
                """,
                (in_1h, today_str),
            ).fetchall()

            warn_rows = conn.execute(
                """
                SELECT name, deadline FROM tasks
                WHERE deadline != ''
                  AND deadline > ?
                  AND deadline <= ?
                  AND status NOT IN ('done', 'archived')
                ORDER BY deadline ASC
                """,
                (in_1h, in_24h),
            ).fetchall()

        mood = get_mood()

        _urgent_msgs = {
            "friend": "🚨 哎！{name} 一小时内就要截止了，你还没搞定！赶紧的！",
            "drill":  "🚨 紧急。{name} 一小时内截止。立即处理。",
            "boss":   "🚨 {name}……还有一小时，你真的……算了，快去做。",
        }
        _warn_msgs = {
            "friend": "⏰ 提醒一下，{name} 还有不到24小时截止，别忘了。",
            "drill":  "⏰ {name} 24小时内截止。检查进度，确保完成。",
            "boss":   "⏰ {name} 就快到期了……希望你心里有数。",
        }

        for row in urgent_rows:
            msg = _urgent_msgs.get(mood, _urgent_msgs["friend"]).format(name=row["name"])
            msg += f"\n📅 截止：{row['deadline']}"
            send_message(msg, parse_mode=None)
            logger.info("发送紧急截止提醒: %s", row["name"])

        for row in warn_rows:
            msg = _warn_msgs.get(mood, _warn_msgs["friend"]).format(name=row["name"])
            msg += f"\n📅 截止：{row['deadline']}"
            send_message(msg, parse_mode=None)
            logger.info("发送截止日期提醒: %s", row["name"])

    except Exception:
        logger.exception("截止日期检查异常")


def _weekly_report_job() -> None:
    """每周日 21:00 自动生成并推送周报。"""
    try:
        from memory import build_weekly_report
        from notifier import send_message

        report = build_weekly_report()
        ok = send_message(report)
        logger.info("周报推送 %s", "✅" if ok else "❌")
    except Exception:
        logger.exception("周报推送异常")


# ── 调度循环 ───────────────────────────────────────────────────────────────────

def _loop() -> None:
    schedule.every().day.at("09:00").do(_morning_job)
    schedule.every().day.at("21:00").do(_evening_job)
    schedule.every().hour.do(check_deadlines)
    schedule.every().sunday.at("21:00").do(_weekly_report_job)
    schedule.every(5).minutes.do(_notion_pull_job)

    logger.info(
        "定时任务已注册：09:00 早报 | 21:00 晚报 | 每小时截止提醒 | "
        "每周日21:00 周报 | 每5分钟 Notion 轮询"
    )
    while True:
        schedule.run_pending()
        time.sleep(30)


def start_background_scheduler() -> threading.Thread:
    t = threading.Thread(target=_loop, daemon=True, name="scheduler")
    t.start()
    return t


# ── 手动触发（测试 / Telegram /sync 用）────────────────────────────────────────

def trigger_morning_now() -> None:
    _morning_job()


def trigger_evening_now() -> None:
    _evening_job()


def trigger_notion_pull_now() -> int:
    try:
        from notion_sync import pull_from_notion
        return pull_from_notion()
    except Exception as exc:
        logger.exception("手动 Notion 轮询失败: %s", exc)
        return 0


def trigger_notion_push_all() -> int:
    try:
        from notion_sync import push_all_to_notion
        return push_all_to_notion()
    except Exception as exc:
        logger.exception("手动 Notion 全量推送失败: %s", exc)
        return 0


def trigger_weekly_report_now() -> None:
    _weekly_report_job()


def trigger_deadline_check_now() -> None:
    check_deadlines()
