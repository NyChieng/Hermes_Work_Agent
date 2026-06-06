"""
Telegram message formatting and delivery.

Formatting uses Markdown v1 (supported by all Telegram clients).
Agent free-text replies are sent WITHOUT parse_mode to avoid
special-character escaping issues in arbitrary task names.
"""

import logging
import os
from datetime import datetime

import httpx

from db import get_mood
from tools import get_summary, list_tasks

# ── mood closing lines ────────────────────────────────────────────────────────

_MOOD_CLOSINGS: dict[str, dict[str, str]] = {
    "morning": {
        "friend": "今天别又给我摸鱼啊，盯着你呢。",
        "drill":  "任务已下达。开始执行，不接受借口。",
        "boss":   "希望今天能让我少失望一次。",
    },
    "evening": {
        "friend": "今天就这样？行吧，明天继续，别让我失望。",
        "drill":  "今日任务结束。明日 09:00 继续，不许懈怠。",
        "boss":   "……就这些。我不说什么了，明天继续吧。",
    },
}

logger = logging.getLogger(__name__)

_TG_URL = "https://api.telegram.org/bot{token}/{method}"

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

_STATUS_EMOJI = {
    "todo":        "⬜",
    "in_progress": "🟡",
    "done":        "✅",
    "blocked":     "🔴",
}


# ── delivery ──────────────────────────────────────────────────────────────────

def send_message(text: str, parse_mode: str | None = "Markdown") -> bool:
    """
    Post a message to the configured chat.
    Returns True on success, False on any error (logs the reason).
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置，跳过发送")
        return False

    url = _TG_URL.format(token=token, method="sendMessage")
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            logger.error("Telegram API error %s: %s", resp.status_code, resp.text[:200])
            return False
        return True
    except httpx.RequestError as exc:
        logger.error("发送消息网络错误: %s", exc)
        return False


def send_plain(text: str) -> bool:
    """Send without any Markdown formatting — safe for arbitrary task text."""
    return send_message(text, parse_mode=None)


# ── report builders ───────────────────────────────────────────────────────────

def build_morning_report() -> str:
    summary   = get_summary()
    today     = datetime.now()
    weekday   = _WEEKDAYS[today.weekday()]

    high_todo = list_tasks(priority="high", status="todo")        or []
    high_wip  = list_tasks(priority="high", status="in_progress") or []
    urgent    = (high_todo + high_wip)[:5]
    blocked   = list_tasks(status="blocked") or []

    lines = [
        f"☀️ *早安！今日工作计划*",
        f"📅 {today.strftime('%Y-%m-%d')} {weekday}",
        "",
        (
            f"📊 总览：{summary['total']} 个任务  "
            f"完成率 *{summary['completion_rate']}*"
        ),
        (
            f"✅ {summary['done']} 完成  "
            f"🟡 {summary['in_progress']} 进行中  "
            f"🔴 {summary['blocked']} 阻塞  "
            f"⬜ {summary['todo']} 未开始"
        ),
    ]

    if urgent:
        lines += ["", "🔴 *今日重点任务*"]
        for t in urgent:
            emoji = _STATUS_EMOJI.get(t["status"], "⬜")
            note  = f"  _{t['notes'][:35]}_" if t.get("notes") else ""
            lines.append(f"  {emoji} {t['name']}{note}")

    if blocked:
        lines += ["", "⚠️ *阻塞中，需关注*"]
        for t in blocked[:3]:
            note = f" — {t['notes'][:40]}" if t.get("notes") else ""
            lines.append(f"  🔴 {t['name']}{note}")

    lines += ["", "💬 直接回复这个 bot 可随时更新任务进度"]
    closing = _MOOD_CLOSINGS["morning"].get(get_mood(), "")
    if closing:
        lines.append(f"_{closing}_")
    return "\n".join(lines)


def build_evening_report() -> str:
    summary  = get_summary()
    done     = list_tasks(status="done",        limit=8) or []
    in_prog  = list_tasks(status="in_progress", limit=5) or []
    blocked  = list_tasks(status="blocked",     limit=3) or []

    lines = [
        f"🌙 *今日收工汇报*",
        f"📅 {datetime.now().strftime('%Y-%m-%d')}",
        "",
        (
            f"📊 完成率：*{summary['completion_rate']}*"
            f"（{summary['done']}/{summary['total']}）"
        ),
    ]

    if done:
        lines += ["", "✅ *今日完成*"]
        for t in done:
            lines.append(f"  ✅ {t['name']}")

    if in_prog:
        lines += ["", "🟡 *进行中（明日继续）*"]
        for t in in_prog:
            note = f" — {t['notes'][:35]}" if t.get("notes") else ""
            lines.append(f"  🟡 {t['name']}{note}")

    if blocked:
        lines += ["", "🔴 *仍在阻塞*"]
        for t in blocked:
            lines.append(f"  🔴 {t['name']}")

    if not done and not in_prog:
        lines += ["", "今天还没有进度记录。"]
    else:
        lines += [""]
    closing = _MOOD_CLOSINGS["evening"].get(get_mood(), "明天继续。")
    lines.append(f"_{closing}_")
    return "\n".join(lines)
