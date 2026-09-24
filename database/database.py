import sqlite3
import os
import json
from contextlib import closing
from datetime import datetime, timezone

from runtime import runtime


DB_PATH = str(runtime.database_path.resolve())
DB_DIR = str(runtime.database_path.resolve().parent)


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
            console TEXT,
            points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            unlock_time TEXT NOT NULL,
            unlock_time_display TEXT NOT NULL,
            hardcore INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    if "console" not in {row[1] for row in cur.execute("PRAGMA table_info(recent_activity)")}:
        cur.execute("ALTER TABLE recent_activity ADD COLUMN console TEXT")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_rankings (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            hardcore_points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            refreshed_at TEXT NOT NULL,
            played_games_json TEXT
        )
        """
    )
    if "played_games_json" not in {row[1] for row in cur.execute("PRAGMA table_info(weekly_rankings)")}:
        cur.execute("ALTER TABLE weekly_rankings ADD COLUMN played_games_json TEXT")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS game_metadata_cache (
            game_id INTEGER PRIMARY KEY,
            game_title TEXT NOT NULL,
            console TEXT,
            genre TEXT,
            refreshed_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_game_library_cache (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            games_json TEXT NOT NULL,
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
            played_games_json TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (week_start, user_key),
            FOREIGN KEY (week_start) REFERENCES weekly_history_weeks(week_start)
        )
        """
    )
    if "played_games_json" not in {row[1] for row in cur.execute("PRAGMA table_info(weekly_history_rankings)")}:
        cur.execute("ALTER TABLE weekly_history_rankings ADD COLUMN played_games_json TEXT")
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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profile_details (
            ra_ulid TEXT PRIMARY KEY COLLATE NOCASE,
            awards_json TEXT,
            awards_refreshed_at TEXT,
            recent_json TEXT,
            recent_refreshed_at TEXT,
            achievements_json TEXT,
            achievements_refreshed_at TEXT
        )
    """)
    profile_detail_columns = {row[1] for row in cur.execute("PRAGMA table_info(user_profile_details)")}
    if "achievements_json" not in profile_detail_columns:
        cur.execute("ALTER TABLE user_profile_details ADD COLUMN achievements_json TEXT")
    if "achievements_refreshed_at" not in profile_detail_columns:
        cur.execute("ALTER TABLE user_profile_details ADD COLUMN achievements_refreshed_at TEXT")
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
        CREATE TABLE IF NOT EXISTS native_notification_deliveries (
            dedupe_key TEXT PRIMARY KEY,
            delivered_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_notification_preferences (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            mute_all INTEGER NOT NULL DEFAULT 0,
            mute_sound INTEGER NOT NULL DEFAULT 0,
            mute_achievement INTEGER NOT NULL DEFAULT 0,
            mute_beaten INTEGER NOT NULL DEFAULT 0,
            mute_mastery INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cur.execute("""
        CREATE TABLE IF NOT EXISTS all_time_chart_profiles (
            ra_username TEXT PRIMARY KEY COLLATE NOCASE,
            payload_json TEXT NOT NULL,
            refreshed_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS all_time_chart_months (
            user_key TEXT NOT NULL COLLATE NOCASE,
            month_start TEXT NOT NULL,
            hardcore_points INTEGER NOT NULL,
            retro_points INTEGER NOT NULL,
            covered_through TEXT NOT NULL,
            daily_json TEXT,
            PRIMARY KEY (user_key, month_start)
        )
    """)
    if "daily_json" not in {row[1] for row in cur.execute("PRAGMA table_info(all_time_chart_months)")}:
        cur.execute("ALTER TABLE all_time_chart_months ADD COLUMN daily_json TEXT")
    if "game_title" not in {row[1] for row in cur.execute("PRAGMA table_info(processed_mastery_events)")}:
        cur.execute("ALTER TABLE processed_mastery_events ADD COLUMN game_title TEXT")
    if "game_image" not in {row[1] for row in cur.execute("PRAGMA table_info(processed_mastery_events)")}:
        cur.execute("ALTER TABLE processed_mastery_events ADD COLUMN game_image TEXT")
    for column in ("game_title", "game_image"):
        if column not in {row[1] for row in cur.execute("PRAGMA table_info(processed_beaten_game_events)")}:
            cur.execute(f"ALTER TABLE processed_beaten_game_events ADD COLUMN {column} TEXT")
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
        VALUES ('display_scale', '1', ?)
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


def get_profile_identity(ra_ulid: str) -> dict | None:
    """Resolve a permanent RA id from tracked or retained historical data."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT t.ra_username, t.ra_ulid, p.canonical_username, p.avatar,
                   p.hardcore_points, p.retro_points
            FROM tracked_users t LEFT JOIN user_profiles p ON p.ra_ulid = t.ra_ulid COLLATE NOCASE
            WHERE t.ra_ulid = ? COLLATE NOCASE
            UNION ALL
            SELECT ra_username, ra_ulid, canonical_username, avatar, hardcore_points, retro_points
            FROM user_profiles WHERE ra_ulid = ? COLLATE NOCASE
            UNION ALL
            SELECT ra_username, ra_ulid, canonical_username, avatar, NULL, NULL
            FROM weekly_history_rankings WHERE ra_ulid = ? COLLATE NOCASE
            LIMIT 1
        """, (ra_ulid, ra_ulid, ra_ulid)).fetchone()
        return dict(row) if row else None


def get_profile_details(ra_ulid: str) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_profile_details WHERE ra_ulid = ? COLLATE NOCASE", (ra_ulid,)).fetchone()
        if not row:
            return {}
        result = dict(row)
        for key in ("awards", "recent", "achievements"):
            payload = result.pop(f"{key}_json")
            result[key] = json.loads(payload) if payload else None
        return result


def save_profile_detail(ra_ulid: str, kind: str, payload):
    if kind not in {"awards", "recent", "achievements"}:
        raise ValueError("Unsupported profile detail")
    with get_conn() as conn:
        conn.execute(f"""
            INSERT INTO user_profile_details (ra_ulid, {kind}_json, {kind}_refreshed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ra_ulid) DO UPDATE SET
                {kind}_json = excluded.{kind}_json,
                {kind}_refreshed_at = excluded.{kind}_refreshed_at
        """, (ra_ulid, json.dumps(payload), datetime.now(timezone.utc).isoformat()))


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
            cur.execute("DELETE FROM user_notification_preferences WHERE ra_username = ?", (user["ra_username"],))
        conn.commit()


USER_NOTIFICATION_FIELDS = (
    "mute_all", "mute_sound", "mute_achievement", "mute_beaten", "mute_mastery"
)


def get_user_notification_preferences(ra_username: str) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_notification_preferences WHERE ra_username = ?",
            (ra_username,),
        ).fetchone()
    return {field: bool(row[field]) if row else False for field in USER_NOTIFICATION_FIELDS}


def set_user_notification_preferences(ra_username: str, preferences: dict[str, bool]) -> bool:
    with get_conn() as conn:
        user = conn.execute(
            "SELECT ra_username FROM tracked_users WHERE ra_username = ?", (ra_username,)
        ).fetchone()
        if not user:
            return False
        conn.execute(
            """
            INSERT INTO user_notification_preferences
                (ra_username, mute_all, mute_sound, mute_achievement, mute_beaten, mute_mastery)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                mute_all = excluded.mute_all,
                mute_sound = excluded.mute_sound,
                mute_achievement = excluded.mute_achievement,
                mute_beaten = excluded.mute_beaten,
                mute_mastery = excluded.mute_mastery
            """,
            (user["ra_username"], *(int(bool(preferences.get(field))) for field in USER_NOTIFICATION_FIELDS)),
        )
    return True


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
                console,
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
                console,
                points,
                retro_points,
                unlock_time,
                unlock_time_display,
                hardcore,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
                username = excluded.username,
                avatar = excluded.avatar,
                achievement_title = excluded.achievement_title,
                achievement_description = excluded.achievement_description,
                achievement_badge = excluded.achievement_badge,
                game_title = excluded.game_title,
                game_id = excluded.game_id,
                console = excluded.console,
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
                activity.get("console"),
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
            SELECT ra_username, hardcore_points, retro_points, week_start, refreshed_at, played_games_json
            FROM weekly_rankings
            WHERE week_start = ?
            """,
            (week_start,),
        )
        rankings = {}
        for row in cur.fetchall():
            ranking = dict(row)
            payload = ranking.pop("played_games_json")
            ranking["played_games"] = json.loads(payload) if payload is not None else None
            rankings[row["ra_username"].lower()] = ranking
        return rankings


def save_weekly_ranking(ra_username: str, hardcore_points: int, retro_points: int, week_start: str,
                        played_games: list[dict] | None = None):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO weekly_rankings (ra_username, hardcore_points, retro_points, week_start, refreshed_at, played_games_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                week_start = excluded.week_start,
                refreshed_at = excluded.refreshed_at,
                played_games_json = excluded.played_games_json
            """,
            (
                ra_username,
                hardcore_points,
                retro_points,
                week_start,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(played_games) if played_games is not None else None,
            ),
        )
        conn.commit()


def save_weekly_rankings(rankings: list[dict], week_start: str):
    refreshed_at = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO weekly_rankings (ra_username, hardcore_points, retro_points, week_start, refreshed_at, played_games_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                week_start = excluded.week_start,
                refreshed_at = excluded.refreshed_at,
                played_games_json = excluded.played_games_json
            """,
            [
                (
                    ranking["ra_username"],
                    ranking["hardcore_points"],
                    ranking["retro_points"],
                    week_start,
                    refreshed_at,
                    json.dumps(ranking.get("played_games", [])),
                )
                for ranking in rankings
            ],
        )
        conn.commit()


def get_game_metadata(game_ids: list[int] | set[int]) -> dict[int, dict]:
    if not game_ids:
        return {}
    ids = sorted({int(game_id) for game_id in game_ids})
    placeholders = ", ".join("?" for _ in ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT game_id, game_title, console, genre, refreshed_at FROM game_metadata_cache WHERE game_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {row["game_id"]: dict(row) for row in rows}


def save_game_metadata(metadata: dict):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO game_metadata_cache (game_id, game_title, console, genre, refreshed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                game_title = excluded.game_title,
                console = excluded.console,
                genre = excluded.genre,
                refreshed_at = excluded.refreshed_at
            """,
            (metadata["game_id"], metadata["game_title"], metadata.get("console"), metadata.get("genre"),
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def get_user_game_libraries(usernames: list[str]) -> dict[str, dict]:
    if not usernames:
        return {}
    placeholders = ", ".join("?" for _ in usernames)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT ra_username, games_json, refreshed_at FROM user_game_library_cache WHERE ra_username IN ({placeholders})",
            usernames,
        ).fetchall()
        return {
            row["ra_username"].lower(): {
                "ra_username": row["ra_username"],
                "games": json.loads(row["games_json"]),
                "refreshed_at": row["refreshed_at"],
            }
            for row in rows
        }


def save_user_game_library(ra_username: str, games: list[dict]):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO user_game_library_cache (ra_username, games_json, refreshed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                games_json = excluded.games_json,
                refreshed_at = excluded.refreshed_at
            """,
            (ra_username, json.dumps(games), datetime.now(timezone.utc).isoformat()),
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
    """Insert an immutable score snapshot, allowing missing game detail to be filled later."""
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
                played_games_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start, user_key) DO UPDATE SET
                played_games_json = COALESCE(excluded.played_games_json, weekly_history_rankings.played_games_json)
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
                json.dumps(ranking.get("played_games")) if ranking.get("played_games") is not None else None,
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
                played_games_json,
                created_at
            FROM weekly_history_rankings
            WHERE week_start = ?
            ORDER BY hardcore_points DESC, canonical_username COLLATE NOCASE ASC
            """,
            (week_start,),
        ).fetchall()
        rankings = []
        for row in rows:
            ranking = dict(row)
            payload = ranking.pop("played_games_json")
            ranking["played_games"] = json.loads(payload) if payload is not None else None
            rankings.append(ranking)
        return rankings


def get_recorded_history_award_counts(start: datetime, end: datetime, usernames: list[str]) -> dict:
    """Count saved awards by earned time; end is exclusive and totals may be partial."""
    counts = {"beaten": 0, "masteries": 0}
    if not usernames:
        return counts
    placeholders = ",".join("?" for _ in usernames)
    with get_conn() as conn:
        for kind, table in (
            ("beaten", "processed_beaten_game_events"),
            ("masteries", "processed_mastery_events"),
        ):
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count FROM (
                    SELECT DISTINCT ra_username COLLATE NOCASE, game_id
                    FROM {table}
                    WHERE julianday(awarded_at) >= julianday(?)
                      AND julianday(awarded_at) < julianday(?)
                      AND ra_username COLLATE NOCASE IN ({placeholders})
                )
                """,
                [start.isoformat(), end.isoformat(), *usernames],
            ).fetchone()
            counts[kind] = row["count"]
    return counts


def get_all_time_chart_cache() -> tuple[dict, dict]:
    with closing(get_conn()) as conn:
        profiles = {
            row["ra_username"].lower(): {"profile": json.loads(row["payload_json"]), "refreshed_at": row["refreshed_at"]}
            for row in conn.execute("SELECT * FROM all_time_chart_profiles")
        }
        months = {}
        for row in conn.execute("SELECT * FROM all_time_chart_months ORDER BY month_start"):
            month = dict(row)
            month["days"] = json.loads(month["daily_json"]) if month["daily_json"] is not None else None
            months.setdefault(row["user_key"].lower(), {})[row["month_start"]] = month
    return profiles, months


def _get_recorded_chart_awards(usernames: list[str], end: datetime, table: str) -> dict:
    if table not in {"processed_mastery_events", "processed_beaten_game_events"}:
        raise ValueError("Unsupported award table")
    if not usernames:
        return {}
    placeholders = ",".join("?" for _ in usernames)
    result = {}
    with closing(get_conn()) as conn:
        canonical_images = {}
        for library in conn.execute(
            f"SELECT ra_username, games_json FROM user_game_library_cache "
            f"WHERE ra_username COLLATE NOCASE IN ({placeholders})",
            usernames,
        ):
            for game in json.loads(library["games_json"]):
                if game.get("game_image"):
                    canonical_images[(library["ra_username"].lower(), int(game["game_id"]))] = game["game_image"]
        for row in conn.execute(f"""
            SELECT ra_username, game_id, game_title, game_image, awarded_at
            FROM {table}
            WHERE ra_username COLLATE NOCASE IN ({placeholders})
              AND julianday(awarded_at) <= julianday(?)
            ORDER BY julianday(awarded_at)
        """, [*usernames, end.isoformat()]):
            result.setdefault(row["ra_username"].lower(), []).append({
                "game_id": row["game_id"], "game_title": row["game_title"],
                "game_image": canonical_images.get((row["ra_username"].lower(), row["game_id"])) or row["game_image"],
                "date": row["awarded_at"],
            })
    return result


def get_recorded_chart_masteries(usernames: list[str], end: datetime) -> dict:
    return _get_recorded_chart_awards(usernames, end, "processed_mastery_events")


def get_recorded_chart_beaten_games(usernames: list[str], end: datetime) -> dict:
    return _get_recorded_chart_awards(usernames, end, "processed_beaten_game_events")


def update_recorded_beaten_metadata(awards: list[dict]):
    with closing(get_conn()) as conn:
        conn.executemany("""
            UPDATE processed_beaten_game_events SET
                game_title = COALESCE(?, game_title), game_image = COALESCE(?, game_image)
            WHERE ra_username = ? AND game_id = ?
        """, [(award.get("game_title"), award.get("game_image"), award["username"], award["game_id"]) for award in awards])
        conn.commit()


def update_recorded_mastery_titles(masteries: list[dict]):
    if not masteries:
        return
    with closing(get_conn()) as conn:
        conn.executemany("""
            UPDATE processed_mastery_events SET
                game_title = COALESCE(?, game_title), game_image = COALESCE(?, game_image)
            WHERE dedupe_key = ?
        """, [(award.get("game_title"), award.get("game_image"), award["dedupe_key"]) for award in masteries])
        conn.executemany("""
            UPDATE processed_beaten_game_events SET
                game_title = COALESCE(?, game_title), game_image = COALESCE(?, game_image)
            WHERE ra_username = ? AND game_id = ?
        """, [(award.get("game_title"), award.get("game_image"), award["username"], award["game_id"])
                for award in masteries])
        conn.commit()


def get_history_user_weeks(user_key: str) -> set[str]:
    with closing(get_conn()) as conn:
        return {row[0] for row in conn.execute(
            "SELECT week_start FROM weekly_history_rankings WHERE user_key = ?", (user_key,)
        )}


def get_history_user_weeks_with_games(user_key: str) -> set[str]:
    with closing(get_conn()) as conn:
        return {row[0] for row in conn.execute(
            "SELECT week_start FROM weekly_history_rankings WHERE user_key = ? AND played_games_json IS NOT NULL",
            (user_key,),
        )}


def save_completed_history_snapshots(snapshots: list[dict]):
    """Insert reconstructed weeks while only enriching existing rows with game detail."""
    created = datetime.now(timezone.utc).isoformat()
    with closing(get_conn()) as conn:
        conn.executemany("INSERT OR IGNORE INTO weekly_history_weeks VALUES (?, ?, ?)", [
            (row["week_start"], row["week_end"], created) for row in snapshots
        ])
        conn.executemany("""
            INSERT OR IGNORE INTO weekly_history_rankings (
                week_start, user_key, ra_username, canonical_username, ra_ulid, avatar,
                hardcore_points, retro_points, achievements_earned, played_games_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start, user_key) DO UPDATE SET
                played_games_json = COALESCE(excluded.played_games_json, weekly_history_rankings.played_games_json)
        """, [(
            row["week_start"], row["user_key"], row["ra_username"], row["canonical_username"],
            row.get("ra_ulid"), row.get("avatar"), row["hardcore_points"], row["retro_points"],
            row["achievements_earned"], json.dumps(row.get("played_games")) if row.get("played_games") is not None else None,
            created,
        ) for row in snapshots])
        conn.commit()


def save_all_time_chart_profile(username: str, profile: dict, refreshed_at: datetime):
    with closing(get_conn()) as conn:
        conn.execute("""
            INSERT INTO all_time_chart_profiles VALUES (?, ?, ?)
            ON CONFLICT(ra_username) DO UPDATE SET
                payload_json = excluded.payload_json, refreshed_at = excluded.refreshed_at
        """, (username, json.dumps(profile), refreshed_at.isoformat()))
        conn.commit()


def save_all_time_chart_month(user_key: str, month_start: str, points: dict, covered_through: datetime, days: dict):
    with closing(get_conn()) as conn:
        conn.execute("""
            INSERT INTO all_time_chart_months (user_key, month_start, hardcore_points, retro_points, covered_through, daily_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_key, month_start) DO UPDATE SET
                hardcore_points = excluded.hardcore_points,
                retro_points = excluded.retro_points,
                covered_through = excluded.covered_through,
                daily_json = excluded.daily_json
        """, (user_key, month_start, points["hardcore_points"], points["retro_points"], covered_through.isoformat(), json.dumps(days)))
        conn.commit()


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
            FROM weekly_history_rankings AS ranking
            WHERE week_start IN ({placeholders})
              AND EXISTS (
                SELECT 1
                FROM tracked_users AS tracked
                WHERE tracked.ra_username = ranking.ra_username COLLATE NOCASE
                   OR (
                     tracked.ra_ulid IS NOT NULL
                     AND ranking.ra_ulid IS NOT NULL
                     AND tracked.ra_ulid = ranking.ra_ulid COLLATE NOCASE
                   )
              )
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
                processed_at,
                game_title,
                game_image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO NOTHING
            """,
            (
                mastery["dedupe_key"],
                mastery["username"],
                mastery["game_id"],
                mastery["awarded_at"],
                1 if announced else 0,
                datetime.now(timezone.utc).isoformat(),
                mastery.get("game_title"),
                mastery.get("game_image"),
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
                processed_at,
                game_title,
                game_image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    mastery.get("game_title"),
                    mastery.get("game_image"),
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
                processed_at, game_title, game_image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username, game_id) DO NOTHING
            """,
            (
                beaten_game["username"],
                beaten_game["game_id"],
                beaten_game["awarded_at"],
                1 if announced else 0,
                datetime.now(timezone.utc).isoformat(),
                beaten_game.get("game_title"),
                beaten_game.get("game_image"),
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
                processed_at, game_title, game_image
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ra_username, game_id) DO NOTHING
            """,
            [
                (
                    beaten_game["username"],
                    beaten_game["game_id"],
                    beaten_game["awarded_at"],
                    1 if announced else 0,
                    processed_at,
                    beaten_game.get("game_title"),
                    beaten_game.get("game_image"),
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


def native_notification_delivered(dedupe_key: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM native_notification_deliveries WHERE dedupe_key = ?",
            (dedupe_key,),
        )
        return cur.fetchone() is not None


def mark_native_notification_delivered(dedupe_key: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO native_notification_deliveries (dedupe_key, delivered_at)
            VALUES (?, ?)
            """,
            (dedupe_key, datetime.now(timezone.utc).isoformat()),
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
