"""
情绪记忆 — 每日行为快照、streak 追踪，以及注入 system prompt 的记忆块。
还包括周报生成器（DeepSeek 驱动，三种人格各有语气）。
"""

import json
import logging
import os
from datetime import datetime, timedelta

from db import _now, _today, get_conn, get_mood, init_db

logger = logging.getLogger(__name__)

_GOOD_THRESHOLD = 0.50


# ── 写入 ───────────────────────────────────────────────────────────────────────

def record_today(
    tasks_done: int,
    tasks_added: int,
    completion_rate: float,
    mood: str,
    note: str = "",
) -> None:
    """
    将今日数据写入 daily_log 并更新 streak 计数器。
    由晚报定时任务每天调用一次。
    """
    init_db()
    today = _today()
    good  = completion_rate >= _GOOD_THRESHOLD

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO daily_log (date, tasks_done, tasks_added, completion_rate, mood_used, note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                tasks_done      = excluded.tasks_done,
                tasks_added     = excluded.tasks_added,
                completion_rate = excluded.completion_rate,
                mood_used       = excluded.mood_used,
                note            = excluded.note
            """,
            (today, tasks_done, tasks_added, round(completion_rate, 3), mood, note),
        )

        row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
        if row:
            last      = row["last_updated"]
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            if last != today:
                if good:
                    new_good = (row["good_streak"] + 1) if last == yesterday else 1
                    new_bad  = 0
                else:
                    new_good = 0
                    new_bad  = (row["bad_streak"] + 1) if last == yesterday else 1

                new_best = max(row["best_streak"], new_good)

                week_notes: list = json.loads(row["last_week_notes"] or "[]")
                week_notes.append({
                    "date":  today,
                    "rate":  round(completion_rate * 100),
                    "good":  good,
                    "note":  note[:30] if note else "",
                })
                week_notes = week_notes[-7:]

                conn.execute(
                    """
                    UPDATE streak SET
                        good_streak     = ?,
                        bad_streak      = ?,
                        best_streak     = ?,
                        last_updated    = ?,
                        last_week_notes = ?
                    WHERE id = 1
                    """,
                    (new_good, new_bad, new_best, today, json.dumps(week_notes)),
                )


# ── 读取 ───────────────────────────────────────────────────────────────────────

def get_memory_context() -> dict:
    """
    返回结构化记忆：streak + 最近3天的 daily_log。
    即使表为空也安全。
    """
    init_db()
    with get_conn() as conn:
        streak_row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
        recent     = conn.execute(
            "SELECT * FROM daily_log ORDER BY date DESC LIMIT 3"
        ).fetchall()

    streak = {}
    if streak_row:
        streak = {
            "good_streak":  streak_row["good_streak"],
            "bad_streak":   streak_row["bad_streak"],
            "best_streak":  streak_row["best_streak"],
            "last_updated": streak_row["last_updated"],
        }

    history = [
        {
            "date":   r["date"],
            "done":   r["tasks_done"],
            "added":  r["tasks_added"],
            "rate":   round(r["completion_rate"] * 100),
            "mood":   r["mood_used"],
            "note":   r["note"],
        }
        for r in recent
    ]

    return {"streak": streak, "history": history}


def build_memory_block(ctx: dict) -> str:
    """
    生成约 80-100 tokens 的记忆文本，注入到 system prompt 里。
    没有历史时返回空字符串。
    """
    streak  = ctx.get("streak", {})
    history = ctx.get("history", [])
    if not streak and not history:
        return ""

    good = streak.get("good_streak", 0)
    bad  = streak.get("bad_streak",  0)
    best = streak.get("best_streak", 0)

    lines = [
        "[近期行为记录]",
        f"连好:{good}天 | 连差:{bad}天 | 最佳连续:{best}天",
    ]

    if history:
        lines.append("最近记录(日期 完成率 情绪备注):")
        for h in history:
            note_str = f" [{h['note'][:20]}]" if h.get("note") else ""
            lines.append(
                f"  {h['date']} {h['rate']}% mood:{h['mood']}{note_str}"
            )

    return "\n".join(lines)


# ── 每日评语生成（调度器用）────────────────────────────────────────────────────

def generate_daily_note(completion_rate: float) -> str:
    """
    调用 DeepSeek 生成 ≤10 字的口语化今日评语。
    任何错误都静默返回空字符串（评语是可选的）。
    """
    try:
        from openai import OpenAI
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return ""

        mood      = get_mood()
        pct       = round(completion_rate * 100)
        _names    = {"friend": "损友", "drill": "军训教官", "boss": "怨念上司"}
        mood_name = _names.get(mood, mood)
        prompt = (
            f"你是{mood_name}。"
            f"今天完成率 {pct}%。用 10 字以内口语化中文写一句今日评语，不要加引号，不要解释。"
        )

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp   = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=30,
            temperature=0.7,
        )
        note = resp.choices[0].message.content.strip()[:30]
        return note
    except Exception as exc:
        logger.warning("生成今日评语失败: %s", exc)
        return ""


# ── 周报生成 ───────────────────────────────────────────────────────────────────

# 三种人格的周报写作指令
_WEEKLY_VOICES: dict[str, str] = {
    "friend": (
        "你是一个损友，帮用户总结这周的工作情况。"
        "风格：嘴贱但真心，先点一下成绩，然后毫不留情地说拖延的事，最后顺带说下周要干嘛。"
        "口语化，带点刺，不要废话，三段各2-3句。"
    ),
    "drill": (
        "你是军训教官，用精简命令式语言写周报总结。"
        "三部分：本周战绩（用数字说话）、拖延清单（点名）、下周目标（具体指令）。"
        "每部分不超过3句，全程没有废话。"
    ),
    "boss": (
        "你是带着克制失望的上司，写一份周报总结给下属。"
        "先简短认可成果，然后说说那些让你暗自叹气的地方（省略号要出现），最后交代下周重点。"
        "语气克制，不发火，但让人感觉到你的期望和失望。不超过8句话。"
    ),
}


def build_weekly_report() -> str:
    """
    读取过去7天的 daily_log，统计数据，调用 DeepSeek 生成自然语言周报。
    包含"本周亮点 / 本周拖延 / 下周重点"三段，文风跟随当前人格。
    失败时返回纯文本统计摘要作为降级方案。
    """
    init_db()
    today = datetime.now()
    seven_days_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_log
            WHERE date >= ?
            ORDER BY date ASC
            """,
            (seven_days_ago,),
        ).fetchall()

    if not rows:
        return "📊 过去7天暂无数据记录，周报无法生成。"

    # 统计
    total_done     = sum(r["tasks_done"]  for r in rows)
    total_added    = sum(r["tasks_added"] for r in rows)
    rates          = [r["completion_rate"] for r in rows if r["completion_rate"] > 0]
    avg_rate       = sum(rates) / len(rates) if rates else 0
    good_days      = sum(1 for r in rows if r["completion_rate"] >= _GOOD_THRESHOLD)
    bad_days       = len(rows) - good_days

    # 连续完成天数（从最近往前数）
    streak = 0
    for r in reversed(rows):
        if r["completion_rate"] >= _GOOD_THRESHOLD:
            streak += 1
        else:
            break

    # 构建数据摘要供 LLM 参考
    daily_detail = "\n".join(
        f"  {r['date']}: 完成率{round(r['completion_rate']*100)}%"
        f"，完成{r['tasks_done']}个，新增{r['tasks_added']}个"
        + (f"，备注：{r['note']}" if r['note'] else "")
        for r in rows
    )

    stats_summary = (
        f"本周统计：\n"
        f"- 总完成任务数：{total_done}\n"
        f"- 总新增任务数：{total_added}\n"
        f"- 平均完成率：{round(avg_rate * 100)}%\n"
        f"- 完成天数：{good_days}天 / 未达标天数：{bad_days}天\n"
        f"- 当前连续完成天数：{streak}天\n\n"
        f"每日详情：\n{daily_detail}"
    )

    mood     = get_mood()
    voice    = _WEEKLY_VOICES.get(mood, _WEEKLY_VOICES["friend"])

    try:
        from openai import OpenAI
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY 未配置")

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        prompt = (
            f"{voice}\n\n"
            f"以下是这周的数据，请据此写周报：\n\n{stats_summary}\n\n"
            f"写三段：【本周亮点】【本周拖延】【下周重点】，每段有标题。"
        )

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.6,
        )
        ai_report = resp.choices[0].message.content.strip()

        mood_labels = {"friend": "😏 损友", "drill": "🪖 军训教官", "boss": "😔 怨念上司"}
        header = (
            f"📋 *本周工作周报*\n"
            f"📅 {(today - timedelta(days=6)).strftime('%m/%d')} — {today.strftime('%m/%d')}\n"
            f"👤 {mood_labels.get(mood, mood)}视角\n\n"
            f"📊 {total_done}个任务完成 | 平均完成率{round(avg_rate*100)}% | "
            f"连续达标{streak}天\n\n"
        )
        return header + ai_report

    except Exception as exc:
        logger.warning("周报 AI 生成失败，降级为纯文本: %s", exc)
        return (
            f"📋 本周工作周报（{(today - timedelta(days=6)).strftime('%m/%d')}—{today.strftime('%m/%d')}）\n\n"
            + stats_summary
        )
