"""
Emotional memory — daily behaviour snapshots, streak tracking, and
a compact memory block (~100 tokens) injected into the agent's system prompt
so each persona can "dredge up the past" authentically.
"""

import json
import logging
import os
from datetime import datetime, timedelta

from db import _now, _today, get_conn, get_mood, init_db

logger = logging.getLogger(__name__)

_GOOD_THRESHOLD = 0.50   # completion_rate >= this → good day


# ── write ─────────────────────────────────────────────────────────────────────

def record_today(
    tasks_done: int,
    tasks_added: int,
    completion_rate: float,
    mood: str,
    note: str = "",
) -> None:
    """
    Upsert today's entry in daily_log and update streak counters.
    Call once per day from the evening scheduler.
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

        # Update streak
        row = conn.execute("SELECT * FROM streak WHERE id=1").fetchone()
        if row:
            last = row["last_updated"]
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            # Only update streak if we haven't already recorded today
            if last != today:
                if good:
                    new_good = (row["good_streak"] + 1) if last == yesterday else 1
                    new_bad  = 0
                else:
                    new_good = 0
                    new_bad  = (row["bad_streak"] + 1) if last == yesterday else 1

                new_best = max(row["best_streak"], new_good)

                # Rolling 7-day notes list
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


# ── read ──────────────────────────────────────────────────────────────────────

def get_memory_context() -> dict:
    """
    Return structured memory: streaks + last 3 daily_log entries.
    Safe to call even if tables are empty.
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
    Compact text (~80-100 tokens) injected into the system prompt.
    Returns an empty string when there's no history yet.
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


# ── auto-generate today's note via DeepSeek (optional, used by scheduler) ─────

def generate_daily_note(completion_rate: float) -> str:
    """
    Call DeepSeek to produce a ≤10-char, in-character daily note.
    Returns empty string on any error (note is optional).
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
