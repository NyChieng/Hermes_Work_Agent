"""
Telegram Bot — Hermes 工作进度助手的 Telegram 前端。
"""

import asyncio
import logging
import os
from datetime import datetime

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
from db import get_conn, get_mood, get_notion_ids, init_db  # noqa: E402
from notifier import build_evening_report, build_morning_report  # noqa: E402
from prompts import MOOD_LABELS  # noqa: E402
from scheduler import (  # noqa: E402
    start_background_scheduler,
    trigger_notion_pull_now,
    trigger_notion_push_all,
    trigger_weekly_report_now,
)

logging.basicConfig(
    format="%(asctime)s  [%(levelname)-8s]  %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# 对话历史（chat_id → 消息列表）
_histories: dict[str, list[dict]] = {}

# OCR 待确认任务（chat_id → task list）
_pending_ocr: dict[str, list[dict]] = {}

# 活跃番茄钟（chat_id → {session_id, task_name, timer_task, started_at}）
_active_pomodoros: dict[str, dict] = {}

_HELP_TEXT = (
    "👋 *Hermes — your personal work assistant*\n\n"
    "Just talk naturally:\n"
    "_\"API module is done\"_\n"
    "_\"Block the design review, waiting on feedback\"_\n"
    "_\"Add a deadline of Friday for the report\"_\n\n"
    "Send a photo of a whiteboard, sticky note or screenshot and I'll pull out the tasks for you.\n\n"
    "*Commands*\n"
    "/morning  — today's plan\n"
    "/report   — end of day summary\n"
    "/weekly   — weekly report (or auto-sends Sunday 21:00)\n"
    "/list     — list all tasks\n"
    "/mood     — switch persona (Buddy / Guide / Boss)\n"
    "/pomo     — start a 25-min focus timer\n"
    "/pomo stop — cancel current timer\n"
    "/pomo stats — focus time stats\n"
    "/notion   — Notion database link\n"
    "/sync     — manual Notion sync\n"
    "/help     — show this"
)


# ── 工具函数 ──────────────────────────────────────────────────────────────────

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
        await update.message.reply_text("出了点问题，再试一次？")
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


def _format_pomodoro_stats(chat_id: str) -> str:
    """格式化番茄钟统计数据。"""
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now().replace(hour=0, minute=0) -
                  __import__('datetime').timedelta(days=datetime.now().weekday())
                  ).strftime("%Y-%m-%d")

    with get_conn() as conn:
        today_rows = conn.execute(
            "SELECT * FROM pomodoro_sessions WHERE started_at LIKE ? AND completed=1",
            (f"{today}%",),
        ).fetchall()
        week_rows = conn.execute(
            "SELECT * FROM pomodoro_sessions WHERE started_at >= ? AND completed=1",
            (week_start + " 00:00",),
        ).fetchall()
        incomplete = conn.execute(
            "SELECT * FROM pomodoro_sessions WHERE started_at LIKE ? AND completed=0",
            (f"{today}%",),
        ).fetchall()

    today_mins = sum(r["duration_minutes"] for r in today_rows)
    week_mins  = sum(r["duration_minutes"] for r in week_rows)

    lines = [
        "🍅 *番茄钟统计*",
        f"",
        f"今日专注：{len(today_rows)} 个 = {today_mins} 分钟",
        f"本周专注：{len(week_rows)} 个 = {week_mins} 分钟",
    ]
    if incomplete:
        lines.append(f"中断记录：{len(incomplete)} 个未完成")

    if chat_id in _active_pomodoros:
        pomo     = _active_pomodoros[chat_id]
        elapsed  = (datetime.now() - pomo["started_at"]).seconds // 60
        remaining = pomo["duration"] - elapsed
        lines.append(f"\n⏳ 当前番茄：{pomo['task_name']}（还剩 {remaining} 分钟）")

    return "\n".join(lines)


# ── 命令处理器 ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(_HELP_TEXT, parse_mode="Markdown")


async def cmd_morning(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(build_morning_report(), parse_mode="Markdown")
    except Exception:
        logger.exception("早报构建失败")
        await update.message.reply_text("早报生成出问题了，稍后再试？")


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.reply_text(build_evening_report(), parse_mode="Markdown")
    except Exception:
        logger.exception("晚报构建失败")
        await update.message.reply_text("晚报生成出问题了，稍后再试？")


async def cmd_weekly(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """手动触发周报生成。"""
    await update.message.reply_text("⏳ 正在生成本周报告，稍等一下…")
    try:
        from memory import build_weekly_report
        report = await asyncio.to_thread(build_weekly_report)
        await update.message.reply_text(report, parse_mode="Markdown")
    except Exception:
        logger.exception("周报生成失败")
        await update.message.reply_text("周报生成失败了，稍后再试？")


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
            "Notion 数据库还没初始化。\n"
            "先在 .env 里配置 NOTION_TOKEN 和 NOTION_PARENT_PAGE_ID，重启后自动创建。"
        )
        return
    clean_id = db_id.replace("-", "")
    url = f"https://www.notion.so/{clean_id}"
    await update.message.reply_text(
        f"🔗 Notion 数据库：\n{url}\n\n同步延迟最多 5 分钟。"
    )


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ 正在同步 Notion…")
    try:
        pulled = await asyncio.to_thread(trigger_notion_pull_now)
        pushed = await asyncio.to_thread(trigger_notion_push_all)
        await update.message.reply_text(
            f"✅ 同步完成\n  Notion → SQLite：{pulled} 个更新\n  SQLite → Notion：{pushed} 个推送"
        )
    except Exception:
        logger.exception("手动同步失败")
        await update.message.reply_text("同步失败了，看一眼日志？")


# ── 番茄钟 ────────────────────────────────────────────────────────────────────

async def cmd_pomo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /pomo <任务名>  — 开始 25 分钟番茄钟
    /pomo stop      — 中断当前番茄钟
    /pomo stats     — 查看专注统计
    """
    chat_id = str(update.effective_chat.id)
    args    = ctx.args or []
    sub     = args[0].lower() if args else ""

    if sub == "stop":
        if chat_id not in _active_pomodoros:
            await update.message.reply_text("现在没有进行中的番茄钟。")
            return
        pomo = _active_pomodoros.pop(chat_id)
        pomo["timer_task"].cancel()
        elapsed = (datetime.now() - pomo["started_at"]).seconds // 60
        _mark_pomodoro_incomplete(pomo["session_id"])
        await update.message.reply_text(
            f"⏹ 番茄钟已中断\n任务：{pomo['task_name']}\n专注了 {elapsed} 分钟"
        )
        return

    if sub == "stats":
        stats_text = await asyncio.to_thread(_format_pomodoro_stats, chat_id)
        await update.message.reply_text(stats_text, parse_mode="Markdown")
        return

    # 开始新番茄钟
    if chat_id in _active_pomodoros:
        existing = _active_pomodoros[chat_id]
        elapsed  = (datetime.now() - existing["started_at"]).seconds // 60
        remaining = existing["duration"] - elapsed
        await update.message.reply_text(
            f"你现在已经在专注「{existing['task_name']}」了（还剩约 {remaining} 分钟）。\n"
            f"发 /pomo stop 可以中断。"
        )
        return

    task_name = " ".join(args).strip() if args else ""
    if not task_name:
        await update.message.reply_text(
            "用法：\n"
            "/pomo 任务名   — 开始 25 分钟番茄钟\n"
            "/pomo stop     — 中断\n"
            "/pomo stats    — 统计"
        )
        return

    duration = 25
    session_id = _start_pomodoro_session(task_name, duration)

    mood = get_mood()
    _start_msgs = {
        "friend": f"行吧，专注 {duration} 分钟，别给我偷懒。任务：{task_name}",
        "drill":  f"开始。{task_name}。{duration} 分钟。专注。",
        "boss":   f"……{task_name}，{duration} 分钟，希望你能认真对待。",
    }
    await update.message.reply_text(_start_msgs.get(mood, _start_msgs["friend"]))

    timer_task = asyncio.create_task(
        _pomo_timer(
            chat_id=chat_id,
            session_id=session_id,
            task_name=task_name,
            bot=ctx.bot,
            minutes=duration,
        )
    )
    _active_pomodoros[chat_id] = {
        "session_id": session_id,
        "task_name":  task_name,
        "timer_task": timer_task,
        "started_at": datetime.now(),
        "duration":   duration,
    }


async def _pomo_timer(
    chat_id: str, session_id: int, task_name: str, bot, minutes: int
) -> None:
    """番茄钟倒计时，结束后发消息。"""
    try:
        await asyncio.sleep(minutes * 60)
        if chat_id in _active_pomodoros and _active_pomodoros[chat_id]["session_id"] == session_id:
            _active_pomodoros.pop(chat_id)
            _mark_pomodoro_complete(session_id, task_name)

            mood = get_mood()
            _done_msgs = {
                "friend": f"叮！{minutes} 分钟到了，{task_name} 做得怎么样？快去休息一下，别当铁人。",
                "drill":  f"时间到。{task_name}。汇报状态。现在休息 5 分钟。",
                "boss":   f"……{minutes} 分钟了。{task_name}……做得怎么样，我希望有点进展。",
            }
            await bot.send_message(
                chat_id=int(chat_id),
                text=_done_msgs.get(mood, _done_msgs["friend"])
            )
    except asyncio.CancelledError:
        pass


def _start_pomodoro_session(task_name: str, duration: int) -> int:
    """在 DB 里创建番茄钟记录，返回 session_id。"""
    init_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_conn() as conn:
        # 尝试找到对应任务的 ID
        task_row = conn.execute(
            "SELECT id FROM tasks WHERE name LIKE ? AND status != 'archived'",
            (f"%{task_name}%",),
        ).fetchone()
        task_id = task_row["id"] if task_row else None

        conn.execute(
            """
            INSERT INTO pomodoro_sessions (task_id, task_name, started_at, duration_minutes, completed)
            VALUES (?, ?, ?, ?, 0)
            """,
            (task_id, task_name, now, duration),
        )
        row = conn.execute(
            "SELECT id FROM pomodoro_sessions WHERE started_at=? AND task_name=? ORDER BY id DESC LIMIT 1",
            (now, task_name),
        ).fetchone()
        return row["id"] if row else 0


def _mark_pomodoro_complete(session_id: int, task_name: str) -> None:
    """标记番茄钟为完成，并把专注时长写入任务备注。"""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE pomodoro_sessions SET completed=1 WHERE id=?", (session_id,)
        )
        row = conn.execute(
            "SELECT duration_minutes FROM pomodoro_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if row:
            mins = row["duration_minutes"]
            now  = datetime.now().strftime("%Y-%m-%d %H:%M")
            task = conn.execute(
                "SELECT notes FROM tasks WHERE name LIKE ? AND status != 'archived'",
                (f"%{task_name}%",),
            ).fetchone()
            if task:
                old_notes = task["notes"] or ""
                new_notes = f"{old_notes}\n🍅 {now} 专注 {mins} 分钟".strip()
                conn.execute(
                    "UPDATE tasks SET notes=?, updated=? WHERE name LIKE ? AND status != 'archived'",
                    (new_notes[:500], now, f"%{task_name}%"),
                )


def _mark_pomodoro_incomplete(session_id: int) -> None:
    """标记番茄钟为未完成（中断）。"""
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE pomodoro_sessions SET completed=0 WHERE id=?", (session_id,)
        )


# ── 内联键盘回调 ──────────────────────────────────────────────────────────────

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


async def handle_ocr_confirm_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 OCR 确认/取消按钮。"""
    query   = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    action  = query.data  # "ocr_confirm" or "ocr_cancel"

    if action == "ocr_cancel":
        _pending_ocr.pop(chat_id, None)
        await query.edit_message_text("已取消，没有创建任何任务。")
        return

    if action == "ocr_confirm":
        tasks = _pending_ocr.pop(chat_id, [])
        if not tasks:
            await query.edit_message_text("没有待确认的任务了。")
            return

        from tools import add_task
        created = []
        errors  = []
        for t in tasks:
            result = await asyncio.to_thread(
                add_task,
                name=t.get("name", "未命名任务"),
                priority=t.get("priority", "medium"),
                notes=t.get("notes", ""),
                deadline=t.get("deadline", ""),
            )
            if "error" in result:
                errors.append(t.get("name", "?"))
            else:
                created.append(result["name"])

        lines = [f"✅ 已创建 {len(created)} 个任务："]
        for name in created:
            lines.append(f"  • {name}")
        if errors:
            lines.append(f"\n⚠️ {len(errors)} 个创建失败：{', '.join(errors)}")

        await query.edit_message_text("\n".join(lines))


# ── 图片消息处理（OCR）──────────────────────────────────────────────────────────

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """用户发图片 → 自动 OCR 识别任务 → 发确认消息。"""
    chat_id = str(update.effective_chat.id)
    await ctx.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    await update.message.reply_text("🔍 正在识别图片中的任务…")

    # 取最高分辨率图片
    photo   = update.message.photo[-1]
    tg_file = await photo.get_file()
    raw     = await tg_file.download_as_bytearray()

    from ocr import extract_tasks_from_image
    result = await asyncio.to_thread(
        extract_tasks_from_image, bytes(raw), "image/jpeg"
    )

    if isinstance(result, str):
        await update.message.reply_text(f"识别失败：{result}")
        return

    if not result:
        await update.message.reply_text("没有在图片中找到任务，换一张试试？")
        return

    _pending_ocr[chat_id] = result

    lines = [f"📋 识别到 {len(result)} 个任务，确认后批量创建：\n"]
    for i, t in enumerate(result, 1):
        priority_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(t.get("priority", "medium"), "🟡")
        dl = f" ⏰{t['deadline']}" if t.get("deadline") else ""
        note = f"\n    💬 {t['notes']}" if t.get("notes") else ""
        lines.append(f"{i}. {priority_emoji} {t['name']}{dl}{note}")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ 全部创建", callback_data="ocr_confirm"),
        InlineKeyboardButton("❌ 取消",    callback_data="ocr_cancel"),
    ]])
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboard,
    )


# ── 普通文本消息 ──────────────────────────────────────────────────────────────

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id   = str(update.effective_chat.id)
    user_text = (update.message.text or "").strip()
    if not user_text:
        return

    # 检查是否有待确认的 OCR 任务
    if chat_id in _pending_ocr:
        lower = user_text.lower().strip()
        if lower in ("确认", "yes", "y", "创建", "ok", "好"):
            tasks = _pending_ocr.pop(chat_id, [])
            from tools import add_task
            created = []
            for t in tasks:
                r = await asyncio.to_thread(
                    add_task,
                    name=t.get("name", "未命名"),
                    priority=t.get("priority", "medium"),
                    notes=t.get("notes", ""),
                    deadline=t.get("deadline", ""),
                )
                if "error" not in r:
                    created.append(r["name"])
            await update.message.reply_text(f"✅ 已创建 {len(created)} 个任务。")
            return
        elif lower in ("取消", "cancel", "no", "n", "算了"):
            _pending_ocr.pop(chat_id, None)
            await update.message.reply_text("已取消，没有创建任何任务。")
            return

    answer = await _typing_and_run(update, ctx, user_text)
    if answer:
        await update.message.reply_text(answer)


# ── 错误处理 ──────────────────────────────────────────────────────────────────

async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("PTB error: %s", ctx.error, exc_info=ctx.error)


# ── 启动 ──────────────────────────────────────────────────────────────────────

def run_telegram_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未设置，请检查 .env")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("help",    cmd_help))
    application.add_handler(CommandHandler("morning", cmd_morning))
    application.add_handler(CommandHandler("report",  cmd_report))
    application.add_handler(CommandHandler("weekly",  cmd_weekly))
    application.add_handler(CommandHandler("list",    cmd_list))
    application.add_handler(CommandHandler("mood",    cmd_mood))
    application.add_handler(CommandHandler("notion",  cmd_notion))
    application.add_handler(CommandHandler("sync",    cmd_sync))
    application.add_handler(CommandHandler("pomo",    cmd_pomo))

    application.add_handler(CallbackQueryHandler(handle_mood_callback,        pattern=r"^mood_"))
    application.add_handler(CallbackQueryHandler(handle_ocr_confirm_callback, pattern=r"^ocr_"))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(on_error)

    logger.info("Telegram Bot 已启动…  (Ctrl+C 退出)")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_background_scheduler()
    run_telegram_bot()
