"""
Unified entry point.

Startup order:
  1. init_db()                   — create / migrate all tables
  2. setup_notion() if first run — create Notion database
  3. push_all_to_notion()        — first-time bulk sync
  4. start_background_scheduler()— 09:00/21:00 reports + Notion poll
  5. start Telegram Bot (thread) — non-blocking
  6. uvicorn FastAPI             — blocks (Railway health-check target)

If FastAPI / uvicorn is not installed, falls back to Telegram-only mode.
"""

import logging
import os
import sys
import threading

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s  [%(levelname)-8s]  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _start_telegram() -> None:
    from telegram_bot import run_telegram_bot
    try:
        run_telegram_bot()
    except Exception:
        logger.exception("Telegram Bot 异常退出")


def main() -> None:
    # ── 1. init DB ────────────────────────────────────────────────────────────
    from db import get_notion_ids, init_db, save_notion_ids
    init_db()
    logger.info("数据库初始化完成")

    # ── 2. Notion first-run setup ─────────────────────────────────────────────
    # If NOTION_DB_ID env var is set (e.g. on Railway), seed it so we don't
    # create a duplicate database on a fresh SQLite instance.
    env_db_id = os.getenv("NOTION_DB_ID", "").strip()
    if env_db_id:
        current_db_id, _ = get_notion_ids()
        if not current_db_id:
            save_notion_ids(env_db_id, env_db_id)
            logger.info("从环境变量载入 Notion DB ID: %s", env_db_id)

    db_id, _ = get_notion_ids()
    if not db_id and os.getenv("NOTION_TOKEN") and os.getenv("NOTION_PARENT_PAGE_ID"):
        logger.info("首次运行：正在创建 Notion 数据库…")
        from notion_sync import setup_notion, push_all_to_notion
        url = setup_notion()
        if url.startswith("http"):
            logger.info("Notion 数据库已创建：%s", url)
            print(f"\n[OK] Notion 数据库链接：{url}\n")
            pushed = push_all_to_notion()
            logger.info("初始批量推送完成：%d 个任务", pushed)
        else:
            logger.warning("Notion 初始化失败: %s", url)

    # ── 3. background scheduler ───────────────────────────────────────────────
    from scheduler import start_background_scheduler
    start_background_scheduler()
    logger.info("后台调度器已启动")

    # ── 4. Telegram Bot (daemon thread) ───────────────────────────────────────
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        t = threading.Thread(target=_start_telegram, daemon=True, name="telegram-bot")
        t.start()
        logger.info("Telegram Bot 已在后台启动")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN 未设置，跳过 Telegram Bot")

    # ── 5. FastAPI / uvicorn (blocking) ───────────────────────────────────────
    try:
        import uvicorn
        from api import app as fastapi_app

        port = int(os.getenv("PORT", 8000))
        logger.info("Web UI 启动中：http://0.0.0.0:%d", port)
        uvicorn.run(fastapi_app, host="0.0.0.0", port=port, log_level="warning")
    except ImportError:
        logger.info("uvicorn/fastapi 未安装，以纯 Telegram 模式运行")
        # Keep the main thread alive so daemon threads can work
        try:
            while True:
                threading.Event().wait(60)
        except KeyboardInterrupt:
            logger.info("再见！")
            sys.exit(0)


if __name__ == "__main__":
    main()
