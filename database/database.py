import sqlite3
import os
from datetime import datetime, timezone

DB_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(DB_DIR, "leftover.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ra_username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            ra_ulid TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recent_activity (
            dedupe_key TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            avatar TEXT,
            achievement_id INTEGER NOT NULL,
            achievement_title TEXT NOT NULL,
            achievement_description TEXT,
            achievement_badge TEXT,
            game_title TEXT NOT NULL,
            game_id INTEGER NOT NULL,
            points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            unlock_time TEXT NOT NULL,
            unlock_time_display TEXT NOT NULL,
            hardcore INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def get_tracked_users():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, ra_username, ra_ulid, created_at FROM tracked_users ORDER BY created_at ASC")
        return [dict(r) for r in cur.fetchall()]


def tracked_user_exists(ra_username: str, ra_ulid: str | None = None) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        if ra_ulid:
            cur.execute(
                "SELECT 1 FROM tracked_users WHERE ra_username = ? OR ra_ulid = ?",
                (ra_username, ra_ulid),
            )
        else:
            cur.execute("SELECT 1 FROM tracked_users WHERE ra_username = ?", (ra_username,))
        return cur.fetchone() is not None


def add_tracked_user(ra_username: str, ra_ulid: str | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO tracked_users (ra_username, ra_ulid, created_at) VALUES (?, ?, ?)",
            (ra_username, ra_ulid, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def remove_tracked_user(user_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tracked_users WHERE id = ?", (user_id,))
        conn.commit()


def get_recent_activity(limit: int = 5):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                dedupe_key,
                username,
                avatar,
                achievement_id,
                achievement_title,
                achievement_description,
                achievement_badge,
                game_title,
                game_id,
                points,
                retro_points,
                unlock_time,
                unlock_time_display,
                hardcore
            FROM recent_activity
            ORDER BY unlock_time DESC, dedupe_key ASC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


def save_recent_activity(activity: dict, keep_limit: int = 5):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO recent_activity (
                dedupe_key,
                username,
                avatar,
                achievement_id,
                achievement_title,
                achievement_description,
                achievement_badge,
                game_title,
                game_id,
                points,
                retro_points,
                unlock_time,
                unlock_time_display,
                hardcore,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                username = excluded.username,
                avatar = excluded.avatar,
                achievement_title = excluded.achievement_title,
                achievement_description = excluded.achievement_description,
                achievement_badge = excluded.achievement_badge,
                game_title = excluded.game_title,
                game_id = excluded.game_id,
                points = excluded.points,
                retro_points = excluded.retro_points,
                unlock_time = excluded.unlock_time,
                unlock_time_display = excluded.unlock_time_display,
                hardcore = excluded.hardcore
            """,
            (
                activity["dedupe_key"],
                activity["username"],
                activity.get("avatar"),
                activity["achievement_id"],
                activity["achievement_title"],
                activity.get("achievement_description", ""),
                activity.get("achievement_badge"),
                activity["game_title"],
                activity["game_id"],
                activity["points"],
                activity["retro_points"],
                activity["unlock_time_iso"],
                activity["unlock_time_display"],
                1 if activity.get("hardcore") else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        prune_recent_activity(cur, keep_limit)
        conn.commit()


def save_recent_activities(activities: list[dict], keep_limit: int = 5):
    for activity in sorted(activities, key=lambda a: a["unlock_time"], reverse=True):
        save_recent_activity(activity, keep_limit=keep_limit)


def prune_recent_activity(cur, keep_limit: int):
    cur.execute(
        """
        DELETE FROM recent_activity
        WHERE dedupe_key NOT IN (
            SELECT dedupe_key
            FROM recent_activity
            ORDER BY unlock_time DESC, dedupe_key ASC
            LIMIT ?
        )
        """,
        (keep_limit,),
    )
