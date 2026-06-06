"""
Telegram Bot — front-end for the Work Progress Agent.
load_dotenv() must run before importing agent so DEEPSEEK_API_KEY is set.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from agent import run_agent, set_mood  # noqa: E402
from db import get_mood, get_notion_ids  # noqa: E402
from notifier import build_evening_report, build_morning_report  # noqa: E402
from prompts import MOOD_LABELS  # noqa: E402
from scheduler import (  # noqa: E402
    start_background_scheduler,
    trigger_notion_pull_now,
    trigger_notion_push_all,
)

logging.basicConfig(
    format="%(asctime)s  [%(levelname)-8s]  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

_histories: dict[str, list[dict]] = {}

_HELP_TEXT = (
    "👋 *工作进度 Agent*\n\n"
    "直接发消息更新任务，例如：\n"
    "「API 模块今天做完了」\n"
    "「把文档编写改成阻塞，等设计评审」\n\n"
    "*命令*\n"
    "/morning — ☀️ 今日任务计划\n"
    "/report  — 🌙 今日收工汇报\n"
    "/list    — 📋 列出所有任务\n"
    "/mood    — 🎭 切换鞭策风格\n"
    "/notion  — 🔗 查看 Notion 数据库链接\n"
    "/sync    — 🔄 手动触发 Notion 同步\n"
    "/help    — ❓ 显示此帮助"
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_history(chat_id: str) -> list[dict]:
    return _histories.get(chat_id, [])


def _save_history(chat_id: str, history: list[dict]) -> None:
    _histories[chat_id] = history[-12:]


async def _typing_and_run(
    update: Update,
    ctx: ContextTypes.DEFAULT_TYPE,
    user_text: str,
) -> str | None:
    chat_id = str(update.effective_chat.id)
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    history = _get_history(chat_id)
    try:
        answer, new_history = await asyncio.to_thread(run_agent, user_text, history)
        _save_history(chat_id, new_history)
        return answer
    except Exception:
        logger.exception("Agent 调用失败 (chat_id=%s)", chat_id)
        await update.message.reply_text("❌ 处理出错，请重试。")
        return None


def _mood_keyboard() -> InlineKeyboardMarkup:
    current = get_mood()
    buttons = [
        InlineKeyboardButton(
            f"✓ {label}" if mode == current else label,
            callback_data=f"mood_{mode}",
        )
        for mode, label in MOOD_LABELS.items()
    ]
    return InlineKeyboardMarkup([buttons])


# ── command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(build_morning_report(), parse_mode="Markdown")
    except Exception:
        logger.exception("早报构建失败")
        await update.message.reply_text("❌ 生成早报失败，请重试。")


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(build_evening_report(), parse_mode="Markdown")
    except Exception:
        logger.exception("晚报构建失败")
        await update.message.reply_text("❌ 生成晚报失败，请重试。")


async def cmd_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    answer = await _typing_and_run(update, ctx, "列出所有任务，按优先级和状态分组")
    if answer:
        await update.message.reply_text(answer)


async def cmd_mood(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    args = ctx.args
    if args:
        result = await asyncio.to_thread(set_mood, args[0].strip().lower())
        await update.message.reply_text(result)
    else:
        current_label = MOOD_LABELS.get(get_mood(), "未知")
        await update.message.reply_text(
            f"当前人格：*{current_label}*\n选择新模式：",
            parse_mode="Markdown",
            reply_markup=_mood_keyboard(),
        )


async def cmd_notion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_id, _ = get_notion_ids()
    if not db_id:
        await update.message.reply_text(
            "Notion 数据库尚未初始化。\n"
            "请先在 .env 中配置 NOTION_TOKEN 和 NOTION_PARENT_PAGE_ID，"
            "然后重启 bot——首次启动会自动创建数据库。"
        )
        return
    # Construct Notion URL from DB ID (remove hyphens for URL)
    clean_id = db_id.replace("-", "")
    url = f"https://www.notion.so/{clean_id}"
    await update.message.reply_text(
        f"🔗 Notion 数据库链接：\n{url}\n\n"
        f"同步延迟：最多 5 分钟（每 5 分钟自动轮询一次）"
    )


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ 正在同步 Notion…")
    await ctx.bot.send_chat_action(
        chat_id=str(update.effective_chat.id), action="typing"
    )
    try:
        pulled = await asyncio.to_thread(trigger_notion_pull_now)
        pushed = await asyncio.to_thread(trigger_notion_push_all)
        await update.message.reply_text(
            f"✅ Notion 同步完成\n"
            f"  Notion → SQLite：{pulled} 个更新\n"
            f"  SQLite → Notion：{pushed} 个推送"
        )
    except Exception:
        logger.exception("手动同步失败")
        await update.message.reply_text("❌ 同步失败，请查看日志。")


# ── callback: inline keyboard ─────────────────────────────────────────────────

async def handle_mood_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    mode   = query.data.replace("mood_", "")
    result = await asyncio.to_thread(set_mood, mode)
    try:
        await query.edit_message_text(
            text=f"{result}\n\n切换其他模式：",
            reply_markup=_mood_keyboard(),
        )
    except Exception:
        pass


# ── message handler ───────────────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = (update.message.text or "").strip()
    if not user_text:
        return
    answer = await _typing_and_run(update, ctx, user_text)
    if answer:
        await update.message.reply_text(answer)


# ── error handler ─────────────────────────────────────────────────────────────

async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("PTB error: %s", ctx.error, exc_info=ctx.error)


# ── main ──────────────────────────────────────────────────────────────────────

def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未设置，请检查 .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("morning", cmd_morning))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("list",    cmd_list))
    app.add_handler(CommandHandler("mood",    cmd_mood))
    app.add_handler(CommandHandler("notion",  cmd_notion))
    app.add_handler(CommandHandler("sync",    cmd_sync))
    app.add_handler(CallbackQueryHandler(handle_mood_callback, pattern=r"^mood_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    logger.info("Telegram Bot 已启动…  (Ctrl+C 退出)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_background_scheduler()
    run_telegram_bot()
