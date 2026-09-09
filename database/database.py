import sqlite3
import os
import json
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "leftover.db")
configured_db_path = os.getenv("LEFTOVER_ACHIEVEMENTS_DB_PATH")
if configured_db_path:
    configured_db_path = os.path.expanduser(configured_db_path)
    DB_PATH = (
        configured_db_path
        if os.path.isabs(configured_db_path)
        else os.path.join(PROJECT_ROOT, configured_db_path)
    )
else:
    DB_PATH = DEFAULT_DB_PATH
DB_PATH = os.path.abspath(DB_PATH)
DB_DIR = os.path.dirname(DB_PATH)


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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_rankings (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            hardcore_points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            refreshed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_history_weeks (
            week_start TEXT PRIMARY KEY,
            week_end TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_history_rankings (
            week_start TEXT NOT NULL,
            user_key TEXT NOT NULL COLLATE NOCASE,
            ra_username TEXT NOT NULL,
            canonical_username TEXT NOT NULL,
            ra_ulid TEXT,
            avatar TEXT,
            hardcore_points INTEGER NOT NULL DEFAULT 0,
            retro_points INTEGER NOT NULL DEFAULT 0,
            achievements_earned INTEGER NOT NULL DEFAULT 0,
            beaten_count INTEGER,
            mastery_count INTEGER,
            created_at TEXT NOT NULL,
            PRIMARY KEY (week_start, user_key),
            FOREIGN KEY (week_start) REFERENCES weekly_history_weeks(week_start)
        )
        """
    )
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_weekly_history_rankings_week
        ON weekly_history_rankings (week_start)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_profiles (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            canonical_username TEXT NOT NULL,
            ra_ulid TEXT,
            avatar TEXT,
            hardcore_points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            refreshed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS currently_playing_cache (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            active INTEGER NOT NULL,
            payload_json TEXT,
            refreshed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_achievement_unlocks (
            dedupe_key TEXT PRIMARY KEY,
            ra_username TEXT NOT NULL COLLATE NOCASE,
            achievement_id INTEGER NOT NULL,
            unlock_time TEXT NOT NULL,
            announced INTEGER NOT NULL,
            processed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS achievement_poll_state (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            initialized_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_mastery_events (
            dedupe_key TEXT PRIMARY KEY,
            ra_username TEXT NOT NULL COLLATE NOCASE,
            game_id INTEGER NOT NULL,
            awarded_at TEXT NOT NULL,
            announced INTEGER NOT NULL,
            processed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS mastery_poll_state (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            initialized_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_beaten_game_events (
            ra_username TEXT NOT NULL COLLATE NOCASE,
            game_id INTEGER NOT NULL,
            awarded_at TEXT NOT NULL,
            announced INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            PRIMARY KEY (ra_username, game_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS beaten_game_poll_state (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            initialized_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_poll_schedule (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            last_polled_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO app_settings (key, value, updated_at)
        VALUES ('audio_enabled', '1', ?)
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    cur.execute(
        """
        INSERT OR IGNORE INTO app_settings (key, value, updated_at)
        VALUES ('setup_complete', '0', ?)
        """,
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()


def get_tracked_users():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, ra_username, ra_ulid, created_at FROM tracked_users ORDER BY created_at ASC")
        return [dict(r) for r in cur.fetchall()]


def tracked_user_count() -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM tracked_users")
        return cur.fetchone()["count"]


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
        cur.execute("SELECT ra_username FROM tracked_users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        cur.execute("DELETE FROM tracked_users WHERE id = ?", (user_id,))
        if user:
            cur.execute("DELETE FROM user_poll_schedule WHERE ra_username = ?", (user["ra_username"],))
        conn.commit()


def next_tracked_user_to_poll() -> dict | None:
    """Return the tracked user least recently handled by the event poller."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT tracked_users.ra_username, user_poll_schedule.last_polled_at
            FROM tracked_users
            LEFT JOIN user_poll_schedule
              ON user_poll_schedule.ra_username = tracked_users.ra_username
            ORDER BY
              CASE WHEN user_poll_schedule.last_polled_at IS NULL THEN 0 ELSE 1 END,
              user_poll_schedule.last_polled_at ASC,
              tracked_users.created_at ASC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return dict(row) if row else None


def mark_tracked_user_polled(ra_username: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_poll_schedule (ra_username, last_polled_at)
            VALUES (?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                last_polled_at = excluded.last_polled_at
            """,
            (ra_username, datetime.now(timezone.utc).isoformat()),
        )
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


def get_weekly_rankings(week_start: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ra_username, hardcore_points, retro_points, week_start, refreshed_at
            FROM weekly_rankings
            WHERE week_start = ?
            """,
            (week_start,),
        )
        return {row["ra_username"].lower(): dict(row) for row in cur.fetchall()}


def save_weekly_ranking(ra_username: str, hardcore_points: int, retro_points: int, week_start: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO weekly_rankings (ra_username, hardcore_points, retro_points, week_start, refreshed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                week_start = excluded.week_start,
                refreshed_at = excluded.refreshed_at
            """,
            (
                ra_username,
                hardcore_points,
                retro_points,
                week_start,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def save_weekly_rankings(rankings: list[dict], week_start: str):
    refreshed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO weekly_rankings (ra_username, hardcore_points, retro_points, week_start, refreshed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                week_start = excluded.week_start,
                refreshed_at = excluded.refreshed_at
            """,
            [
                (
                    ranking["ra_username"],
                    ranking["hardcore_points"],
                    ranking["retro_points"],
                    week_start,
                    refreshed_at,
                )
                for ranking in rankings
            ],
        )
        conn.commit()


def ensure_history_week(week_start: str, week_end: str):
    """Create a completed-week container without replacing an existing snapshot."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO weekly_history_weeks (week_start, week_end, created_at)
            VALUES (?, ?, ?)
            """,
            (week_start, week_end, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_history_weeks(limit: int | None = None, offset: int = 0):
    with get_conn() as conn:
        query = """
            SELECT week_start, week_end, created_at
            FROM weekly_history_weeks
            ORDER BY week_start DESC
        """
        params = []
        if limit is not None:
            query += " LIMIT ? OFFSET ?"
            params.extend((limit, offset))
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_history_week(week_start: str):
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT week_start, week_end, created_at
            FROM weekly_history_weeks
            WHERE week_start = ?
            """,
            (week_start,),
        ).fetchone()
        return dict(row) if row else None


def history_week_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM weekly_history_weeks").fetchone()
        return row["count"]


def history_user_exists(week_start: str, user_key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM weekly_history_rankings
            WHERE week_start = ? AND user_key = ?
            """,
            (week_start, user_key),
        ).fetchone()
        return row is not None


def save_history_ranking(week_start: str, ranking: dict):
    """Insert one immutable user/week snapshot, ignoring an existing row."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO weekly_history_rankings (
                week_start,
                user_key,
                ra_username,
                canonical_username,
                ra_ulid,
                avatar,
                hardcore_points,
                retro_points,
                achievements_earned,
                beaten_count,
                mastery_count,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                week_start,
                ranking["user_key"],
                ranking["ra_username"],
                ranking.get("canonical_username") or ranking["ra_username"],
                ranking.get("ra_ulid"),
                ranking.get("avatar"),
                ranking.get("hardcore_points", 0),
                ranking.get("retro_points", 0),
                ranking.get("achievements_earned", 0),
                ranking.get("beaten_count"),
                ranking.get("mastery_count"),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_history_rankings(week_start: str):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT
                week_start,
                user_key,
                ra_username,
                canonical_username,
                ra_ulid,
                avatar,
                hardcore_points,
                retro_points,
                achievements_earned,
                beaten_count,
                mastery_count,
                created_at
            FROM weekly_history_rankings
            WHERE week_start = ?
            ORDER BY hardcore_points DESC, canonical_username COLLATE NOCASE ASC
            """,
            (week_start,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_weekly_chart_history(limit: int = 8):
    """Return recent completed weeks and their stored rankings, oldest first."""
    limit = max(1, int(limit))
    with get_conn() as conn:
        week_rows = conn.execute(
            """
            SELECT week_start, week_end
            FROM weekly_history_weeks
            ORDER BY week_start DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        weeks = [dict(row) for row in reversed(week_rows)]
        if not weeks:
            return []

        placeholders = ", ".join("?" for _ in weeks)
        ranking_rows = conn.execute(
            f"""
            SELECT
                week_start,
                user_key,
                ra_username,
                canonical_username,
                ra_ulid,
                hardcore_points,
                retro_points
            FROM weekly_history_rankings
            WHERE week_start IN ({placeholders})
            ORDER BY
                week_start ASC,
                hardcore_points DESC,
                canonical_username COLLATE NOCASE ASC
            """,
            [week["week_start"] for week in weeks],
        ).fetchall()

    rankings_by_week = {week["week_start"]: [] for week in weeks}
    for row in ranking_rows:
        ranking = dict(row)
        weekly_rankings = rankings_by_week[ranking["week_start"]]
        ranked_count = sum(item["rank"] is not None for item in weekly_rankings)
        ranking["rank"] = ranked_count + 1 if ranking["hardcore_points"] > 0 else None
        weekly_rankings.append(ranking)

    for week in weeks:
        week["rankings"] = rankings_by_week[week["week_start"]]
    return weeks



def get_user_profiles():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                ra_username,
                canonical_username,
                ra_ulid,
                avatar,
                hardcore_points,
                retro_points,
                refreshed_at
            FROM user_profiles
            """
        )
        return {row["ra_username"].lower(): dict(row) for row in cur.fetchall()}


def save_user_profile(ra_username: str, profile: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_profiles (
                ra_username,
                canonical_username,
                ra_ulid,
                avatar,
                hardcore_points,
                retro_points,
                refreshed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                canonical_username = excluded.canonical_username,
                ra_ulid = excluded.ra_ulid,
                avatar = excluded.avatar,
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                refreshed_at = excluded.refreshed_at
            """,
            (
                ra_username,
                profile.get("username", ra_username),
                profile.get("ulid"),
                profile.get("avatar"),
                profile.get("hardcore_points", 0),
                profile.get("retro_points", 0),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_currently_playing_cache():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ra_username, active, payload_json, refreshed_at
            FROM currently_playing_cache
            """
        )
        rows = {}
        for row in cur.fetchall():
            cached = dict(row)
            payload = cached.get("payload_json")
            cached["payload"] = json.loads(payload) if payload else None
            rows[cached["ra_username"].lower()] = cached
        return rows


def save_currently_playing(ra_username: str, payload: dict | None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO currently_playing_cache (ra_username, active, payload_json, refreshed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                active = excluded.active,
                payload_json = excluded.payload_json,
                refreshed_at = excluded.refreshed_at
            """,
            (
                ra_username,
                1 if payload else 0,
                json.dumps(payload) if payload else None,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()



def achievement_poll_initialized(ra_username: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM achievement_poll_state WHERE ra_username = ?", (ra_username,))
        return cur.fetchone() is not None


def mark_achievement_poll_initialized(ra_username: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO achievement_poll_state (ra_username, initialized_at)
            VALUES (?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                initialized_at = excluded.initialized_at
            """,
            (ra_username, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def achievement_unlock_seen(dedupe_key: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM processed_achievement_unlocks WHERE dedupe_key = ?", (dedupe_key,))
        return cur.fetchone() is not None


def save_processed_achievement_unlock(activity: dict, announced: bool):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_achievement_unlocks (
                dedupe_key,
                ra_username,
                achievement_id,
                unlock_time,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (
                activity["dedupe_key"],
                activity["username"],
                activity["achievement_id"],
                activity["unlock_time_iso"],
                1 if announced else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def save_processed_achievement_unlocks(activities: list[dict], announced: bool):
    if not activities:
        return

    processed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO processed_achievement_unlocks (
                dedupe_key,
                ra_username,
                achievement_id,
                unlock_time,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            [
                (
                    activity["dedupe_key"],
                    activity["username"],
                    activity["achievement_id"],
                    activity["unlock_time_iso"],
                    1 if announced else 0,
                    processed_at,
                )
                for activity in activities
            ],
        )
        conn.commit()



def mastery_poll_initialized(ra_username: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM mastery_poll_state WHERE ra_username = ?", (ra_username,))
        return cur.fetchone() is not None


def mark_mastery_poll_initialized(ra_username: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO mastery_poll_state (ra_username, initialized_at)
            VALUES (?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                initialized_at = excluded.initialized_at
            """,
            (ra_username, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def mastery_event_seen(dedupe_key: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM processed_mastery_events WHERE dedupe_key = ?", (dedupe_key,))
        return cur.fetchone() is not None


def save_processed_mastery_event(mastery: dict, announced: bool):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_mastery_events (
                dedupe_key,
                ra_username,
                game_id,
                awarded_at,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (
                mastery["dedupe_key"],
                mastery["username"],
                mastery["game_id"],
                mastery["awarded_at"],
                1 if announced else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def save_processed_mastery_events(masteries: list[dict], announced: bool):
    if not masteries:
        return

    processed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO processed_mastery_events (
                dedupe_key,
                ra_username,
                game_id,
                awarded_at,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            [
                (
                    mastery["dedupe_key"],
                    mastery["username"],
                    mastery["game_id"],
                    mastery["awarded_at"],
                    1 if announced else 0,
                    processed_at,
                )
                for mastery in masteries
            ],
        )
        conn.commit()


def beaten_game_poll_initialized(ra_username: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM beaten_game_poll_state WHERE ra_username = ?", (ra_username,))
        return cur.fetchone() is not None


def mark_beaten_game_poll_initialized(ra_username: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO beaten_game_poll_state (ra_username, initialized_at)
            VALUES (?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                initialized_at = excluded.initialized_at
            """,
            (ra_username, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def beaten_game_event_seen(ra_username: str, game_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM processed_beaten_game_events WHERE ra_username = ? AND game_id = ?",
            (ra_username, game_id),
        )
        return cur.fetchone() is not None


def save_processed_beaten_game_event(beaten_game: dict, announced: bool):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO processed_beaten_game_events (
                ra_username,
                game_id,
                awarded_at,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ra_username, game_id) DO NOTHING
            """,
            (
                beaten_game["username"],
                beaten_game["game_id"],
                beaten_game["awarded_at"],
                1 if announced else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def save_processed_beaten_game_events(beaten_games: list[dict], announced: bool):
    if not beaten_games:
        return

    processed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO processed_beaten_game_events (
                ra_username,
                game_id,
                awarded_at,
                announced,
                processed_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ra_username, game_id) DO NOTHING
            """,
            [
                (
                    beaten_game["username"],
                    beaten_game["game_id"],
                    beaten_game["awarded_at"],
                    1 if announced else 0,
                    processed_at,
                )
                for beaten_game in beaten_games
            ],
        )
        conn.commit()



def get_setting(key: str, default: str | None = None) -> str | None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def setup_complete() -> bool:
    return get_setting("setup_complete", "0") == "1"


def set_setup_complete(complete: bool):
    set_setting("setup_complete", "1" if complete else "0")


def audio_enabled() -> bool:
    return get_setting("audio_enabled", "1") == "1"


def set_audio_enabled(enabled: bool):
    set_setting("audio_enabled", "1" if enabled else "0")
