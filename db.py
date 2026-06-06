"""
SQLite access layer — schema, connections, and thin state helpers.
All business logic lives in tools.py / memory.py / notion_sync.py.
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

# Allow Dockerfile / Railway to override DB location via env var
_env_db = os.environ.get("DB_PATH", "")
DB_PATH = Path(_env_db) if _env_db else Path(__file__).parent / "tasks.db"

_VALID_MOODS  = {"friend", "drill", "boss"}
_DEFAULT_MOOD = "friend"


# ── connection ────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── schema ────────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if missing; migrate legacy tables safely."""
    with get_conn() as conn:
        conn.executescript("""
            -- Main task store
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL UNIQUE,
                status      TEXT    NOT NULL DEFAULT 'todo',
                priority    TEXT    NOT NULL DEFAULT 'medium',
                notes       TEXT    DEFAULT '',
                tags        TEXT    DEFAULT '',
                notion_id   TEXT    DEFAULT '',
                last_synced TEXT    DEFAULT '',
                created     TEXT    NOT NULL,
                updated     TEXT    NOT NULL
            );

            -- Precomputed stats cache (single row)
            CREATE TABLE IF NOT EXISTS summary_cache (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                total      INTEGER DEFAULT 0,
                done       INTEGER DEFAULT 0,
                in_prog    INTEGER DEFAULT 0,
                blocked    INTEGER DEFAULT 0,
                todo       INTEGER DEFAULT 0,
                top3_json  TEXT    DEFAULT '[]',
                updated_at TEXT    NOT NULL
            );

            -- Per-day behaviour snapshot
            CREATE TABLE IF NOT EXISTS daily_log (
                date            TEXT PRIMARY KEY,
                tasks_done      INTEGER DEFAULT 0,
                tasks_added     INTEGER DEFAULT 0,
                completion_rate REAL    DEFAULT 0.0,
                mood_used       TEXT    DEFAULT 'friend',
                note            TEXT    DEFAULT ''
            );

            -- Running streaks (single row)
            CREATE TABLE IF NOT EXISTS streak (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                good_streak     INTEGER DEFAULT 0,
                bad_streak      INTEGER DEFAULT 0,
                best_streak     INTEGER DEFAULT 0,
                last_updated    TEXT    NOT NULL,
                last_week_notes TEXT    DEFAULT '[]'
            );

            -- Global agent state (single row)
            CREATE TABLE IF NOT EXISTS agent_state (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                current_mood   TEXT    DEFAULT 'friend',
                notion_db_id   TEXT    DEFAULT '',
                notion_page_id TEXT    DEFAULT ''
            );
        """)

        # Migrate: add notion columns to tasks if they don't exist yet
        for col, definition in [
            ("notion_id",   "TEXT DEFAULT ''"),
            ("last_synced", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {definition}")
            except Exception:
                pass  # column already exists

        # Ensure agent_state has its default row
        conn.execute("""
            INSERT OR IGNORE INTO agent_state (id, current_mood, notion_db_id, notion_page_id)
            VALUES (1, 'friend', '', '')
        """)

        # Ensure streak has its default row
        conn.execute("""
            INSERT OR IGNORE INTO streak
                (id, good_streak, bad_streak, best_streak, last_updated, last_week_notes)
            VALUES (1, 0, 0, 0, ?, '[]')
        """, (_today(),))


# ── mood state ────────────────────────────────────────────────────────────────

def get_mood() -> str:
    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT current_mood FROM agent_state WHERE id=1").fetchone()
    return (row["current_mood"] or _DEFAULT_MOOD) if row else _DEFAULT_MOOD


def save_mood(mode: str) -> None:
    if mode not in _VALID_MOODS:
        raise ValueError(f"Unknown mood '{mode}'. Valid: {sorted(_VALID_MOODS)}")
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_state SET current_mood=? WHERE id=1", (mode,)
        )


# ── Notion IDs ────────────────────────────────────────────────────────────────

def get_notion_ids() -> tuple[str, str]:
    """Returns (notion_db_id, notion_page_id). Empty strings if not yet set."""
    init_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT notion_db_id, notion_page_id FROM agent_state WHERE id=1"
        ).fetchone()
    if row:
        return row["notion_db_id"] or "", row["notion_page_id"] or ""
    return "", ""


def save_notion_ids(db_id: str, page_id: str) -> None:
    init_db()
    with get_conn() as conn:
        conn.execute(
            "UPDATE agent_state SET notion_db_id=?, notion_page_id=? WHERE id=1",
            (db_id, page_id),
        )
