"""
Summary cache — one row in summary_cache keeps a precomputed snapshot
so every conversation start costs ~80 tokens instead of dumping the full table.
"""

import json
from datetime import datetime

from db import get_conn, init_db


def _refresh_cache() -> None:
    """Recompute stats from tasks and overwrite the single summary_cache row."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*)                                    AS total,
                SUM(status = 'done')                        AS done,
                SUM(status = 'in_progress')                 AS in_prog,
                SUM(status = 'blocked')                     AS blocked,
                SUM(status = 'todo')                        AS todo
            FROM tasks
            WHERE status != 'archived'
        """).fetchone()

        top3 = conn.execute("""
            SELECT name, status, priority
            FROM tasks
            WHERE priority = 'high'
              AND status NOT IN ('done', 'archived')
            ORDER BY updated DESC
            LIMIT 3
        """).fetchall()

        conn.execute("""
            INSERT INTO summary_cache
                (id, total, done, in_prog, blocked, todo, top3_json, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total      = excluded.total,
                done       = excluded.done,
                in_prog    = excluded.in_prog,
                blocked    = excluded.blocked,
                todo       = excluded.todo,
                top3_json  = excluded.top3_json,
                updated_at = excluded.updated_at
        """, (
            row["total"]   or 0,
            row["done"]    or 0,
            row["in_prog"] or 0,
            row["blocked"] or 0,
            row["todo"]    or 0,
            json.dumps([dict(t) for t in top3], ensure_ascii=False),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ))


def get_cached_summary() -> dict:
    """
    Return the cached summary dict.  Auto-initialises DB and rebuilds cache
    if the summary_cache table is empty.
    """
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM summary_cache WHERE id = 1").fetchone()

    if row is None:
        _refresh_cache()
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM summary_cache WHERE id = 1").fetchone()

    total = row["total"] or 0
    done  = row["done"]  or 0
    rate  = f"{done / total * 100:.0f}%" if total > 0 else "0%"

    return {
        "total":           total,
        "done":            done,
        "in_progress":     row["in_prog"]  or 0,
        "blocked":         row["blocked"]  or 0,
        "todo":            row["todo"]     or 0,
        "completion_rate": rate,
        "top3_urgent":     json.loads(row["top3_json"]),
        "last_updated":    row["updated_at"],
    }
