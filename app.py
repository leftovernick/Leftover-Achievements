import os
import asyncio
import json
import logging
import base64
import io
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv


load_dotenv()

from database import database as db
from services.retroachievements import RetroAchievements
from services.updater import ApplicationUpdater, UpdateError


app = FastAPI(title="LeftoverAchievements Display")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

db.init_db()
ra_client = RetroAchievements(api_key=db.get_setting("ra_api_key") or os.getenv("RA_API_KEY"))
application_updater = ApplicationUpdater(Path(__file__).resolve().parent)
RECENT_ACTIVITY_LIMIT = 5
RECENT_ACTIVITY_FETCH_MINUTES = 43200
WEEKLY_CACHE_TTL = timedelta(minutes=10)
PROFILE_CACHE_TTL = timedelta(minutes=5)
CURRENTLY_PLAYING_CACHE_TTL = timedelta(seconds=75)
weekly_refresh_task = None
history_backfill_task = None
history_refresh_live_requested = False
history_backfill_status = {
    "state": "idle",
    "total_checks": 0,
    "existing": 0,
    "missing": 0,
    "processed": 0,
    "fetched": 0,
    "failed": 0,
    "live_users": 0,
    "live_processed": 0,
    "live_failed": 0,
    "current": None,
    "message": "History data has not been checked in this server session.",
}
user_snapshot_refresh_task = None
recent_activity_refresh_task = None
achievement_poll_task = None
display_event_queues = set()
POLL_CYCLE_SECONDS = 60
MIN_ACHIEVEMENT_POLL_LOOKBACK_MINUTES = 60
DEFAULT_NOTIFICATION_SECONDS = {
    "achievement": 5,
    "beaten": 7,
    "mastery": 9,
}
MIN_NOTIFICATION_SECONDS = 1
MAX_NOTIFICATION_SECONDS = 15
DEFAULT_DISPLAY_SECTION_SECONDS = {
    "overall": 60,
    "weekly": 60,
    "current": 30,
    "recent": 60,
}
MIN_DISPLAY_SECTION_SECONDS = 5
MAX_DISPLAY_SECTION_SECONDS = 180
STATIC_AUDIO_DIR = os.path.join("static", "audio")
CUSTOM_AUDIO_KINDS = ("achievement", "beaten", "mastery")
ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg"}
MAX_CUSTOM_AUDIO_BYTES = 10 * 1024 * 1024
TEST_GAME_ID = 1454
TEST_GAME_TITLE = "The Legend of Zelda"
TEST_GAME_IMAGE = "https://retroachievements.org/Images/012434.png"
TEST_ACHIEVEMENT_ID = 3735
TEST_ACHIEVEMENT_TITLE = "It's Dangerous to Go Alone!"
TEST_ACHIEVEMENT_DESCRIPTION = "Obtain the sword."
TEST_ACHIEVEMENT_BADGE = "https://retroachievements.org/Badge/62752.png"
TEST_USERNAME = "leftovernick"
TEST_USER_AVATAR = "https://retroachievements.org/UserPic/leftovernick.png"
HISTORY_WEEK_COUNT = 4
HISTORY_WEEKS_PAGE_SIZE = 5
HISTORY_PAGE_WAIT_SECONDS = 20
CHART_WEEK_RANGES = (4, 8, 12)
RA_CONNECTION_CHECK_TTL = timedelta(minutes=15)
logger = logging.getLogger(__name__)


def admin_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?{urlencode({'message': message})}", status_code=303)


def users_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/users?{urlencode({'message': message})}", status_code=303)


def onboarding_redirect(step: int, message: str | None = None, status: str | None = None) -> RedirectResponse:
    params = {"step": step}
    if message:
        params["message"] = message
    if status:
        params["status"] = status
    return RedirectResponse(url=f"/onboarding?{urlencode(params)}", status_code=303)


def ra_api_key_source() -> str | None:
    if db.get_setting("ra_api_key"):
        return "settings"
    if os.getenv("RA_API_KEY"):
        return "environment"
    return None


def configured_ra_api_key() -> str | None:
    return db.get_setting("ra_api_key") or os.getenv("RA_API_KEY")


def ra_connection_status() -> str:
    if not configured_ra_api_key():
        return "missing"
    return db.get_setting("ra_api_key_status", "unverified") or "unverified"


async def validate_ra_api_key(api_key: str) -> bool:
    try:
        return await RetroAchievements(api_key=api_key).validate_api_key()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return False


def record_ra_connection(valid: bool):
    db.set_setting("ra_api_key_status", "connected" if valid else "invalid")
    db.set_setting("ra_api_key_checked_at", datetime.now(timezone.utc).isoformat())


async def refresh_ra_connection_if_stale():
    api_key = configured_ra_api_key()
    if not api_key:
        return
    checked_at = parse_iso_datetime(db.get_setting("ra_api_key_checked_at"))
    if checked_at and datetime.now(timezone.utc) - checked_at < RA_CONNECTION_CHECK_TTL:
        return
    record_ra_connection(await validate_ra_api_key(api_key))


def local_device_details(request: Request) -> dict:
    hostname = socket.gethostname().split(".")[0]
    lan_ip = None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
            if candidate and not candidate.startswith("127."):
                lan_ip = candidate
    except OSError:
        pass

    request_host = request.url.hostname
    if request_host and request_host not in {"127.0.0.1", "localhost", "0.0.0.0"}:
        onboarding_host = request_host
    elif lan_ip:
        onboarding_host = lan_ip
    elif hostname and hostname.lower() != "localhost":
        onboarding_host = f"{hostname}.local"
    else:
        onboarding_host = "127.0.0.1"

    port = request.url.port or 8000
    dashboard_url = f"http://{onboarding_host}:{port}/"
    onboarding_url = f"{dashboard_url}onboarding"
    return {
        "hostname": hostname or None,
        "lan_ip": lan_ip,
        "dashboard_url": dashboard_url,
        "dashboard_qr": qr_code_data_url(dashboard_url),
        "onboarding_url": onboarding_url,
        "onboarding_qr": qr_code_data_url(onboarding_url),
    }


def qr_code_data_url(value: str) -> str | None:
    image_bytes = qr_code_png(value)
    if image_bytes is None:
        return None
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def qr_code_png(value: str) -> bytes | None:
    try:
        import qrcode

        image = qrcode.make(value, box_size=10, border=4)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    except (ImportError, OSError, ValueError):
        logger.warning("Could not generate a QR code.", exc_info=True)
        return None


def current_week_range() -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return week_start, now


def previous_completed_week_ranges(count: int = HISTORY_WEEK_COUNT) -> list[tuple[datetime, datetime]]:
    """Return completed local-time Monday-through-Sunday ranges, newest first."""
    current_start, _ = current_week_range()
    ranges = []
    for weeks_ago in range(1, count + 1):
        start = current_start - timedelta(weeks=weeks_ago)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        ranges.append((start, end))
    return ranges


def completed_history_ranges() -> list[tuple[datetime, datetime]]:
    """Return every completed week to audit, retaining a four-week floor for a new database."""
    current_start, _ = current_week_range()
    stored_weeks = db.get_history_weeks()
    if not stored_weeks:
        return previous_completed_week_ranges()

    oldest_stored = min(datetime.fromisoformat(week["week_start"]).date() for week in stored_weeks)
    oldest_start = current_start.replace(
        year=oldest_stored.year,
        month=oldest_stored.month,
        day=oldest_stored.day,
    )
    four_week_floor = current_start - timedelta(weeks=HISTORY_WEEK_COUNT)
    audit_start = min(oldest_start, four_week_floor)
    ranges = []
    start = current_start - timedelta(weeks=1)
    while start >= audit_start:
        ranges.append((start, start + timedelta(days=7) - timedelta(microseconds=1)))
        start -= timedelta(weeks=1)
    return ranges


def history_user_key(user: dict) -> str:
    ulid = user.get("ra_ulid")
    if ulid:
        return f"ulid:{ulid.lower()}"
    return f"username:{user['ra_username'].lower()}"


def readable_week_range(week_start: str, week_end: str) -> str:
    start = datetime.fromisoformat(week_start)
    end = datetime.fromisoformat(week_end)
    if start.year != end.year:
        return f"{start.strftime('%b')} {start.day}, {start.year}\u2013{end.strftime('%b')} {end.day}, {end.year}"
    if start.month == end.month:
        return f"{start.strftime('%b')} {start.day}\u2013{end.day}, {end.year}"
    return f"{start.strftime('%b')} {start.day}\u2013{end.strftime('%b')} {end.day}, {end.year}"


async def backfill_history_user(user: dict, ranges: list[tuple[datetime, datetime]], profile_cache: dict):
    """Fill only this tracked user's missing rows; existing snapshots stay immutable."""
    user_key = history_user_key(user)
    if not ranges:
        return

    username = user["ra_username"]
    profile = profile_cache.get(username.lower(), {})
    if not profile:
        try:
            profile = await ra_client.lookup_user(user.get("ra_ulid") or username)
            db.save_user_profile(username, profile)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning("Could not refresh RetroAchievements profile for history user %s: %s", username, exc)
            profile = {}

    for start, end in ranges:
        history_backfill_status["current"] = f"{username} · {readable_week_range(start.date().isoformat(), end.date().isoformat())}"
        try:
            stats = await ra_client.points_earned_between(user.get("ra_ulid") or username, start, end)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            logger.warning(
                "Could not backfill history for %s during %s through %s: %s",
                username,
                start.date(),
                end.date(),
                exc,
            )
            history_backfill_status["failed"] += 1
            history_backfill_status["processed"] += 1
            continue

        db.save_history_ranking(
            start.date().isoformat(),
            {
                "user_key": user_key,
                "ra_username": username,
                "canonical_username": profile.get("username") or username,
                "ra_ulid": profile.get("ulid") or user.get("ra_ulid"),
                "avatar": profile.get("avatar"),
                "hardcore_points": stats.get("hardcore_points", 0),
                "retro_points": stats.get("retro_points", 0),
                "achievements_earned": stats.get("achievements_earned", 0),
                # The official range API exposes unlocks, not historical award transitions.
                "beaten_count": None,
                "mastery_count": None,
            },
        )
        history_backfill_status["fetched"] += 1
        history_backfill_status["processed"] += 1


async def ensure_history_backfill():
    """Ensure four completed week containers and all currently tracked user rows exist."""
    global history_refresh_live_requested
    started_at = datetime.now(timezone.utc).isoformat()
    history_backfill_status.update(
        {
            "state": "scanning",
            "total_checks": 0,
            "existing": 0,
            "missing": 0,
            "processed": 0,
            "fetched": 0,
            "failed": 0,
            "live_users": 0,
            "live_processed": 0,
            "live_failed": 0,
            "current": None,
            "message": "Checking stored history for missing user/week rows…",
            "started_at": started_at,
            "finished_at": None,
        }
    )
    ranges = completed_history_ranges()
    for start, end in ranges:
        db.ensure_history_week(start.date().isoformat(), end.date().isoformat())

    users = db.get_tracked_users()
    history_backfill_status["total_checks"] = len(users) * len(ranges)
    history_backfill_status["live_users"] = len(users) if history_refresh_live_requested else 0
    if not users:
        history_backfill_status.update(
            {
                "state": "complete",
                "message": "No tracked users to check.",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        history_refresh_live_requested = False
        return

    profile_cache = db.get_user_profiles()
    missing_by_user = []
    for user in users:
        user_key = history_user_key(user)
        missing_ranges = [
            (start, end)
            for start, end in ranges
            if not db.history_user_exists(start.date().isoformat(), user_key)
        ]
        missing_by_user.append((user, missing_ranges))

    missing_count = sum(len(missing_ranges) for _, missing_ranges in missing_by_user)
    history_backfill_status["missing"] = missing_count
    history_backfill_status["existing"] = history_backfill_status["total_checks"] - missing_count
    if not missing_count and not history_refresh_live_requested:
        history_backfill_status.update(
            {
                "state": "complete",
                "message": f"History is complete. Checked {history_backfill_status['total_checks']} user/week rows; no API requests were needed.",
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return

    if missing_count:
        history_backfill_status.update(
            {
                "state": "running",
                "message": f"Found {missing_count} missing completed user/week rows. Fetching from RetroAchievements…",
            }
        )
        # Two workers keeps bulk history reasonably quick while the RA client rate-limits starts.
        semaphore = asyncio.Semaphore(2)

        async def limited_backfill(user, missing_ranges):
            async with semaphore:
                await backfill_history_user(user, missing_ranges, profile_cache)

        await asyncio.gather(
            *(limited_backfill(user, missing_ranges) for user, missing_ranges in missing_by_user if missing_ranges)
        )

    if history_refresh_live_requested:
        week_start, week_end = current_week_range()
        history_backfill_status.update(
            {
                "state": "running",
                "message": "Completed-week gaps checked. Refreshing the current live week…",
            }
        )
        for user in users:
            username = user["ra_username"]
            history_backfill_status["current"] = f"{username} · Current week (LIVE)"
            try:
                stats = await ra_client.points_earned_between(user.get("ra_ulid") or username, week_start, week_end)
                db.save_weekly_ranking(
                    username,
                    stats.get("hardcore_points", 0),
                    stats.get("retro_points", 0),
                    week_start.isoformat(),
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                history_backfill_status["live_failed"] += 1
                logger.warning("Could not refresh current weekly data for %s: %s", username, exc)
            finally:
                history_backfill_status["live_processed"] += 1

    failed = history_backfill_status["failed"] + history_backfill_status["live_failed"]
    added = history_backfill_status["fetched"]
    live_refreshed = history_backfill_status["live_processed"] - history_backfill_status["live_failed"]
    if failed:
        completion_message = f"Finished with {failed} failed request{'s' if failed != 1 else ''}. Run the check again to retry."
    elif history_backfill_status["live_users"]:
        completion_message = f"History is complete. Added {added} completed rows and refreshed {live_refreshed} live user{'s' if live_refreshed != 1 else ''}."
    else:
        completion_message = f"History is complete. Added {added} missing completed user/week rows."
    history_backfill_status.update(
        {
            "state": "complete_with_errors" if failed else "complete",
            "current": None,
            "message": completion_message,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    history_refresh_live_requested = False


def schedule_history_backfill(refresh_live: bool = False) -> asyncio.Task:
    global history_backfill_task, history_refresh_live_requested
    if refresh_live:
        history_refresh_live_requested = True
    if history_backfill_task is None or history_backfill_task.done():
        history_backfill_status.update(
            {
                "state": "queued",
                "current": None,
                "message": "History check queued…",
            }
        )
        history_backfill_task = asyncio.create_task(ensure_history_backfill())
    return history_backfill_task


def history_backfill_status_payload() -> dict:
    payload = dict(history_backfill_status)
    payload["live_refreshed"] = payload.get("live_processed", 0) - payload.get("live_failed", 0)
    total_work = payload.get("missing", 0) + payload.get("live_users", 0)
    processed = payload.get("processed", 0) + payload.get("live_processed", 0)
    if payload.get("state") == "scanning":
        payload["percent"] = 0
    elif total_work:
        payload["percent"] = min(100, round((processed / total_work) * 100))
    elif payload.get("state") in {"complete", "complete_with_errors"}:
        payload["percent"] = 100
    else:
        payload["percent"] = 0
    return payload


def format_points(value: int) -> str:
    return f"{value:,}"


def static_asset_version(path: str) -> int:
    try:
        return int(os.path.getmtime(path))
    except OSError:
        return 0


def notification_seconds(kind: str) -> int:
    default = DEFAULT_NOTIFICATION_SECONDS[kind]
    try:
        value = int(db.get_setting(f"{kind}_notification_seconds", str(default)))
    except (TypeError, ValueError):
        return default
    return max(MIN_NOTIFICATION_SECONDS, min(MAX_NOTIFICATION_SECONDS, value))


def notification_durations() -> dict[str, int]:
    return {kind: notification_seconds(kind) for kind in DEFAULT_NOTIFICATION_SECONDS}


def set_notification_seconds(kind: str, value: str | None):
    try:
        seconds = int(value) if value is not None else DEFAULT_NOTIFICATION_SECONDS[kind]
    except (TypeError, ValueError):
        seconds = DEFAULT_NOTIFICATION_SECONDS[kind]
    db.set_setting(
        f"{kind}_notification_seconds",
        str(max(MIN_NOTIFICATION_SECONDS, min(MAX_NOTIFICATION_SECONDS, seconds))),
    )


def display_section_seconds(section: str) -> int:
    default = DEFAULT_DISPLAY_SECTION_SECONDS[section]
    try:
        value = int(db.get_setting(f"display_{section}_seconds", str(default)))
    except (TypeError, ValueError):
        return default
    return max(MIN_DISPLAY_SECTION_SECONDS, min(MAX_DISPLAY_SECTION_SECONDS, value))


def display_section_durations() -> dict[str, int]:
    return {section: display_section_seconds(section) for section in DEFAULT_DISPLAY_SECTION_SECONDS}


def set_display_section_seconds(section: str, value: str | None):
    try:
        seconds = int(value) if value is not None else DEFAULT_DISPLAY_SECTION_SECONDS[section]
    except (TypeError, ValueError):
        seconds = DEFAULT_DISPLAY_SECTION_SECONDS[section]
    db.set_setting(
        f"display_{section}_seconds",
        str(max(MIN_DISPLAY_SECTION_SECONDS, min(MAX_DISPLAY_SECTION_SECONDS, seconds))),
    )


def configured_audio_sources() -> dict[str, str]:
    """Return verified custom audio URLs, keyed by display event type."""
    sources = {}
    for kind in CUSTOM_AUDIO_KINDS:
        filename = db.get_setting(f"audio_{kind}_file")
        if not filename:
            continue
        extension = os.path.splitext(filename)[1].lower()
        expected_prefix = f"custom-{kind}"
        path = os.path.join(STATIC_AUDIO_DIR, filename)
        if (
            not filename.startswith(expected_prefix)
            or extension not in ALLOWED_AUDIO_EXTENSIONS
            or os.path.basename(filename) != filename
            or not os.path.isfile(path)
        ):
            continue
        sources[kind] = f"/static/audio/{filename}?v={int(os.path.getmtime(path))}"
    return sources


async def save_custom_audio(kind: str, upload: UploadFile | None) -> str | None:
    """Persist an optional custom alert sound and return an admin status message."""
    if upload is None or not getattr(upload, "filename", None):
        return None

    extension = os.path.splitext(upload.filename)[1].lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        return f"{kind.title()} audio was not saved: use MP3, WAV, or OGG."

    content = await upload.read(MAX_CUSTOM_AUDIO_BYTES + 1)
    if len(content) > MAX_CUSTOM_AUDIO_BYTES:
        return f"{kind.title()} audio was not saved: files must be 10 MB or smaller."

    os.makedirs(STATIC_AUDIO_DIR, exist_ok=True)
    filename = f"custom-{kind}{extension}"
    for candidate_extension in ALLOWED_AUDIO_EXTENSIONS:
        candidate = os.path.join(STATIC_AUDIO_DIR, f"custom-{kind}{candidate_extension}")
        if candidate != os.path.join(STATIC_AUDIO_DIR, filename) and os.path.exists(candidate):
            os.remove(candidate)
    with open(os.path.join(STATIC_AUDIO_DIR, filename), "wb") as audio_file:
        audio_file.write(content)
    db.set_setting(f"audio_{kind}_file", filename)
    return f"Saved custom {kind} audio."


def cache_is_stale(refreshed_at: str | None, ttl: timedelta) -> bool:
    refreshed = parse_iso_datetime(refreshed_at)
    if not refreshed:
        return True
    return datetime.now(timezone.utc) - refreshed > ttl


def schedule_weekly_refresh_if_needed(users: list[dict], weekly_cache: dict, week_start: datetime, week_end: datetime):
    global weekly_refresh_task

    if not users or not weekly_cache_needs_refresh(users, weekly_cache):
        return

    if weekly_refresh_task and not weekly_refresh_task.done():
        return

    weekly_refresh_task = asyncio.create_task(refresh_weekly_rankings(users, week_start, week_end))


def weekly_cache_needs_refresh(users: list[dict], weekly_cache: dict) -> bool:
    if len(weekly_cache) < len(users):
        return True

    for user in users:
        cached = weekly_cache.get(user["ra_username"].lower())
        if not cached or cache_is_stale(cached.get("refreshed_at"), WEEKLY_CACHE_TTL):
            return True

    return False


async def refresh_weekly_rankings(users: list[dict], week_start: datetime, week_end: datetime):
    rankings = []
    for user in users:
        username = user["ra_username"]
        try:
            points = await ra_client.points_earned_between(username, week_start, week_end)
        except (aiohttp.ClientError, ValueError):
            continue
        rankings.append(
            {
                "ra_username": username,
                "hardcore_points": points.get("hardcore_points", 0),
                "retro_points": points.get("retro_points", 0),
            }
        )

    if rankings:
        db.save_weekly_rankings(rankings, week_start.isoformat())


def schedule_user_snapshot_refresh_if_needed(users: list[dict], profile_cache: dict, currently_playing_cache: dict):
    global user_snapshot_refresh_task

    if not user_snapshot_cache_needs_refresh(users, profile_cache, currently_playing_cache):
        return

    if user_snapshot_refresh_task and not user_snapshot_refresh_task.done():
        return

    user_snapshot_refresh_task = asyncio.create_task(refresh_user_snapshots(users))


def user_snapshot_cache_needs_refresh(users: list[dict], profile_cache: dict, currently_playing_cache: dict) -> bool:
    for user in users:
        key = user["ra_username"].lower()
        profile = profile_cache.get(key)
        current = currently_playing_cache.get(key)
        if not profile or cache_is_stale(profile.get("refreshed_at"), PROFILE_CACHE_TTL):
            return True
        if not current or cache_is_stale(current.get("refreshed_at"), CURRENTLY_PLAYING_CACHE_TTL):
            return True
    return False


async def refresh_user_snapshots(users: list[dict]):
    for user in users:
        username = user["ra_username"]
        profile_target = user.get("ra_ulid") or username
        try:
            profile = await ra_client.lookup_user(profile_target)
            db.save_user_profile(username, profile)
            current_target = profile.get("username", username)
        except (aiohttp.ClientError, ValueError):
            current_target = username

        try:
            currently_playing = await ra_client.currently_playing(current_target)
        except (aiohttp.ClientError, ValueError):
            currently_playing = None

        db.save_currently_playing(username, currently_playing)


def schedule_recent_activity_refresh_if_needed(users: list[dict], recent_activity: list[dict]):
    global recent_activity_refresh_task

    if not users or len(recent_activity) >= RECENT_ACTIVITY_LIMIT:
        return

    if recent_activity_refresh_task and not recent_activity_refresh_task.done():
        return

    recent_activity_refresh_task = asyncio.create_task(refresh_recent_activity(users))


async def refresh_recent_activity(users: list[dict]):
    activity_groups = await asyncio.gather(
        *(recent_activity_for_user(u, RECENT_ACTIVITY_FETCH_MINUTES) for u in users)
    )
    recent_activity_by_key = {}
    for activity_group in activity_groups:
        for activity in activity_group:
            recent_activity_by_key.setdefault(activity["dedupe_key"], activity)

    fetched_activity = sorted(
        recent_activity_by_key.values(),
        key=lambda activity: activity["unlock_time"],
        reverse=True,
    )[:RECENT_ACTIVITY_LIMIT]
    db.save_recent_activities(fetched_activity, keep_limit=RECENT_ACTIVITY_LIMIT)


async def recent_activity_for_user(u, recent_minutes: int):
    target = u["ra_username"] if isinstance(u, dict) else str(u)
    try:
        return await ra_client.recent_hardcore_achievements(target, recent_minutes=recent_minutes)
    except (aiohttp.ClientError, ValueError):
        return []


async def fetch_recent_hardcore_achievements(u, recent_minutes: int):
    target = u["ra_username"] if isinstance(u, dict) else str(u)
    cached_profile = db.get_user_profiles().get(target.lower())
    profile = None
    if cached_profile:
        profile = {
            "username": cached_profile.get("canonical_username") or target,
            "avatar": cached_profile.get("avatar"),
        }
    return await ra_client.recent_hardcore_achievements(
        target,
        recent_minutes=recent_minutes,
        profile=profile,
    )


def prepare_recent_activity(recent_activity):
    for activity in recent_activity:
        activity["points_display"] = format_points(activity["points"])
        activity["retro_points_display"] = format_points(activity["retro_points"])
        activity["unlock_time_iso"] = activity.get("unlock_time_iso") or activity["unlock_time"]
    return recent_activity


def serialize_achievement_event(activity: dict, progress: dict | None = None) -> dict:
    event = {
        "type": "achievement",
        "dedupe_key": activity["dedupe_key"],
        "username": activity["username"],
        "avatar": activity.get("avatar"),
        "achievement_id": activity["achievement_id"],
        "achievement_title": activity["achievement_title"],
        "achievement_description": activity.get("achievement_description", ""),
        "achievement_badge": activity.get("achievement_badge"),
        "game_title": activity["game_title"],
        "game_id": activity["game_id"],
        "points": activity["points"],
        "points_display": format_points(activity["points"]),
        "retro_points": activity["retro_points"],
        "retro_points_display": format_points(activity["retro_points"]),
        "unlock_time_iso": activity["unlock_time_iso"],
        "unlock_time_display": activity["unlock_time_display"],
        "hardcore": True,
        "duration_ms": notification_seconds("achievement") * 1000,
    }
    if progress:
        event.update(progress)
    return event


async def achievement_completion_ranges(username: str, activities: list[dict]) -> dict[str, dict]:
    """Return exact before/after Hardcore completion percentages for new unlocks."""
    activities_by_game = {}
    for activity in activities:
        activities_by_game.setdefault(activity["game_id"], []).append(activity)

    ranges = {}
    for game_id, game_activities in activities_by_game.items():
        try:
            game_progress = await ra_client.game_info_and_user_progress(username, game_id)
        except (aiohttp.ClientError, ValueError):
            continue

        achievements = game_progress.get("Achievements") or game_progress.get("achievements") or {}
        total = int(
            game_progress.get("NumAchievements")
            or game_progress.get("numAchievements")
            or len(achievements)
        )
        if not total:
            continue

        final_count = game_progress.get("NumAwardedToUserHardcore")
        if final_count is None:
            final_count = game_progress.get("numAwardedToUserHardcore")
        if final_count is None:
            final_count = sum(
                1
                for achievement in achievements.values()
                if isinstance(achievement, dict)
                and (achievement.get("DateEarnedHardcore") or achievement.get("dateEarnedHardcore"))
            )
        final_count = int(final_count)

        ordered = sorted(game_activities, key=lambda activity: activity["unlock_time"])
        first_new_count = max(0, final_count - len(ordered))
        for index, activity in enumerate(ordered):
            before_count = min(total, first_new_count + index)
            after_count = min(total, before_count + 1)
            ranges[activity["dedupe_key"]] = {
                "completion_before_percentage": (before_count / total) * 100,
                "completion_after_percentage": (after_count / total) * 100,
            }

    return ranges


def serialize_mastery_event(mastery: dict, profile: dict | None = None) -> dict:
    profile = profile or {}
    hardcore_points = mastery.get("hardcore_points", mastery.get("total_points", 0))
    total_points = mastery.get("total_points", hardcore_points)
    return {
        "type": "mastery",
        "dedupe_key": mastery["dedupe_key"],
        "username": profile.get("username") or mastery["username"],
        "avatar": profile.get("avatar"),
        "game_id": mastery["game_id"],
        "game_title": mastery["game_title"],
        "game_image": mastery.get("game_image"),
        "hardcore_achievements": mastery.get("hardcore_achievements", 0),
        "total_achievements": mastery.get("total_achievements", 0),
        "hardcore_points": hardcore_points,
        "total_points": total_points,
        "hardcore_points_display": format_points(hardcore_points),
        "total_points_display": format_points(total_points),
        "awarded_at": mastery["awarded_at"],
        "duration_ms": notification_seconds("mastery") * 1000,
    }


def serialize_beaten_game_event(beaten_game: dict, profile: dict | None = None) -> dict:
    profile = profile or {}
    hardcore_points = beaten_game.get("hardcore_points", 0)
    total_points = beaten_game.get("total_points", 0)
    return {
        "type": "beaten",
        "dedupe_key": beaten_game["dedupe_key"],
        "username": profile.get("username") or beaten_game["username"],
        "avatar": profile.get("avatar"),
        "game_id": beaten_game["game_id"],
        "game_title": beaten_game["game_title"],
        "game_image": beaten_game.get("game_image"),
        "hardcore_achievements": beaten_game.get("hardcore_achievements", 0),
        "total_achievements": beaten_game.get("total_achievements", 0),
        "hardcore_points": hardcore_points,
        "total_points": total_points,
        "hardcore_points_display": format_points(hardcore_points),
        "total_points_display": format_points(total_points),
        "awarded_at": beaten_game["awarded_at"],
        "duration_ms": notification_seconds("beaten") * 1000,
    }


async def achievement_poll_loop():
    while True:
        started_at = asyncio.get_running_loop().time()
        try:
            await poll_for_new_achievements()
        except Exception as exc:
            print(f"Achievement poll failed: {exc}")
        user_count = db.tracked_user_count()
        if not user_count:
            await asyncio.sleep(POLL_CYCLE_SECONDS)
            continue
        slot_seconds = POLL_CYCLE_SECONDS / user_count
        elapsed_seconds = asyncio.get_running_loop().time() - started_at
        await asyncio.sleep(max(0, slot_seconds - elapsed_seconds))


async def poll_for_new_achievements():
    user = db.next_tracked_user_to_poll()
    if not user:
        return

    username = user["ra_username"]
    last_polled_at = parse_iso_datetime(user.get("last_polled_at"))
    lookback_minutes = MIN_ACHIEVEMENT_POLL_LOOKBACK_MINUTES
    if last_polled_at:
        elapsed_minutes = (datetime.now(timezone.utc) - last_polled_at).total_seconds() / 60
        lookback_minutes = max(lookback_minutes, int(elapsed_minutes) + 2)

    try:
        await process_achievement_unlocks_for_user(username, lookback_minutes)
        await process_game_awards_for_user(username)
    finally:
        # A temporary lookup failure must not let one user block the round robin.
        db.mark_tracked_user_polled(username)


async def process_achievement_unlocks_for_user(username: str, recent_minutes: int = MIN_ACHIEVEMENT_POLL_LOOKBACK_MINUTES):
    try:
        activities = await fetch_recent_hardcore_achievements(username, recent_minutes)
    except (aiohttp.ClientError, ValueError):
        return

    activities = sorted(activities, key=lambda activity: activity["unlock_time"])
    if not db.achievement_poll_initialized(username):
        db.save_processed_achievement_unlocks(activities, announced=False)
        db.mark_achievement_poll_initialized(username)
        return

    new_activities = [activity for activity in activities if not db.achievement_unlock_seen(activity["dedupe_key"])]
    completion_ranges = await achievement_completion_ranges(username, new_activities)
    for activity in new_activities:
        db.save_processed_achievement_unlock(activity, announced=True)
        db.save_recent_activity(activity, keep_limit=RECENT_ACTIVITY_LIMIT)
        await publish_display_event(
            serialize_achievement_event(activity, completion_ranges.get(activity["dedupe_key"]))
        )


async def process_game_awards_for_user(username: str):
    beaten_initialized = db.beaten_game_poll_initialized(username)
    mastery_initialized = db.mastery_poll_initialized(username)
    try:
        awards = await ra_client.hardcore_game_awards(
            username,
            fetch_all=not beaten_initialized or not mastery_initialized,
        )
    except (aiohttp.ClientError, ValueError):
        return

    beaten_games = sorted(awards["beaten"], key=lambda beaten_game: beaten_game["awarded_at"])
    masteries = sorted(awards["masteries"], key=lambda mastery: mastery["awarded_at"])

    if not beaten_initialized:
        db.save_processed_beaten_game_events(beaten_games, announced=False)
        db.mark_beaten_game_poll_initialized(username)

    if not mastery_initialized:
        db.save_processed_mastery_events(masteries, announced=False)
        db.mark_mastery_poll_initialized(username)

    if not beaten_initialized or not mastery_initialized:
        return

    profile_cache = db.get_user_profiles()
    profile = profile_cache.get(username.lower())
    new_beaten_games = [
        beaten_game
        for beaten_game in beaten_games
        if not db.beaten_game_event_seen(username, beaten_game["game_id"])
    ]
    new_masteries = [mastery for mastery in masteries if not db.mastery_event_seen(mastery["dedupe_key"])]

    # Preserve the poll's natural progression: achievement unlock, then Game Beaten,
    # then the larger Mastery presentation when both awards are new together.
    for beaten_game in new_beaten_games:
        try:
            beaten_game = await ra_client.game_award_event_details(username, beaten_game)
        except (aiohttp.ClientError, ValueError):
            pass
        db.save_processed_beaten_game_event(beaten_game, announced=True)
        await publish_display_event(serialize_beaten_game_event(beaten_game, profile))

    for mastery in new_masteries:
        try:
            mastery = await ra_client.mastery_event_details(username, mastery)
        except (aiohttp.ClientError, ValueError):
            pass
        db.save_processed_mastery_event(mastery, announced=True)
        await publish_display_event(serialize_mastery_event(mastery, profile))


async def publish_display_event(event: dict):
    if not display_event_queues:
        return

    event = {**event, "audio_sources": configured_audio_sources()}
    for queue in display_event_queues:
        queue.put_nowait(event)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@app.get("/")
async def dashboard(request: Request):
    if not db.setup_complete():
        return RedirectResponse(url="/onboarding", status_code=307)
    await refresh_ra_connection_if_stale()
    context = await dashboard_context()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
    )


@app.get("/onboarding")
async def onboarding(
    request: Request,
    step: int = 1,
    message: str | None = None,
    status: str | None = None,
):
    step = max(1, min(5, step))
    if step >= 3 and ra_connection_status() != "connected":
        step = 2
        message = message or "Connect RetroAchievements to continue."
        status = status or "error"
    elif step >= 4 and db.tracked_user_count() < 1:
        step = 3
        message = message or "Add at least one player to continue."
        status = status or "error"
    tracked_users = db.get_tracked_users()
    profiles = db.get_user_profiles()
    players = []
    for user in tracked_users:
        profile = profiles.get(user["ra_username"].lower(), {})
        players.append(
            {
                **user,
                "username": profile.get("canonical_username") or user["ra_username"],
                "avatar": profile.get("avatar"),
                "hardcore_points": profile.get("hardcore_points"),
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="onboarding.html",
        context={
            "step": step,
            "message": message,
            "message_status": status,
            "api_key_configured": bool(configured_ra_api_key()),
            "api_connection_status": ra_connection_status(),
            "players": players,
            "setup_complete": db.setup_complete(),
        },
    )


@app.post("/onboarding/welcome")
async def onboarding_welcome():
    return onboarding_redirect(2)


@app.post("/onboarding/api-key")
async def onboarding_api_key(api_key: str = Form("")):
    submitted_key = api_key.strip()
    candidate = submitted_key or configured_ra_api_key()
    if not candidate:
        return onboarding_redirect(2, "Enter your RetroAchievements Web API key to continue.", "error")
    if not await validate_ra_api_key(candidate):
        if not submitted_key:
            record_ra_connection(False)
        return onboarding_redirect(
            2,
            "We couldn't connect with that key. Check it in your RetroAchievements control panel and try again.",
            "error",
        )

    if submitted_key:
        db.set_setting("ra_api_key", submitted_key)
        ra_client.api_key = submitted_key
    record_ra_connection(True)
    return onboarding_redirect(3, "RetroAchievements is connected.", "success")


@app.post("/onboarding/players/add")
async def onboarding_add_player(username: str = Form(...)):
    username = username.strip()
    if not username:
        return onboarding_redirect(3, "Enter a RetroAchievements username.", "error")
    if ra_connection_status() != "connected" or not configured_ra_api_key():
        return onboarding_redirect(2, "Connect RetroAchievements before adding players.", "error")

    try:
        info = await ra_client.lookup_user(username)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        return onboarding_redirect(3, "We couldn't find that player. Check the username and try again.", "error")

    canonical = info.get("username", username)
    ulid = info.get("ulid")
    if db.tracked_user_exists(canonical, ulid):
        return onboarding_redirect(3, f"{canonical} is already being tracked.", "error")

    db.add_tracked_user(canonical, ulid)
    db.save_user_profile(canonical, info)
    return onboarding_redirect(3, f"Added {canonical}.", "success")


@app.post("/onboarding/players/remove")
async def onboarding_remove_player(user_id: int = Form(...)):
    db.remove_tracked_user(user_id)
    return onboarding_redirect(3, "Player removed.", "success")


@app.post("/onboarding/players/continue")
async def onboarding_players_continue():
    if ra_connection_status() != "connected" or not configured_ra_api_key():
        return onboarding_redirect(2, "Connect RetroAchievements before continuing.", "error")
    if db.tracked_user_count() < 1:
        return onboarding_redirect(3, "Add at least one player to continue.", "error")
    return onboarding_redirect(4)


@app.post("/onboarding/display-ready")
async def onboarding_display_ready():
    if ra_connection_status() != "connected" or not configured_ra_api_key():
        return onboarding_redirect(2, "Connect RetroAchievements before finishing setup.", "error")
    if db.tracked_user_count() < 1:
        return onboarding_redirect(3, "Add at least one player before finishing setup.", "error")
    return onboarding_redirect(5)


@app.post("/onboarding/finish")
async def onboarding_finish(destination: str = Form("dashboard")):
    api_key = configured_ra_api_key()
    if not api_key or not await validate_ra_api_key(api_key):
        if api_key:
            record_ra_connection(False)
        return onboarding_redirect(2, "Reconnect RetroAchievements before finishing setup.", "error")
    record_ra_connection(True)
    if db.tracked_user_count() < 1:
        return onboarding_redirect(3, "Add at least one player before finishing setup.", "error")

    db.set_setup_complete(True)
    await start_background_polling()
    return RedirectResponse(url="/display" if destination == "display" else "/", status_code=303)


@app.get("/history")
async def history(request: Request, week: str | None = None):
    backfill_pending = False
    try:
        await asyncio.wait_for(
            asyncio.shield(schedule_history_backfill()),
            timeout=HISTORY_PAGE_WAIT_SECONDS,
        )
    except asyncio.TimeoutError:
        backfill_pending = True
    except Exception as exc:
        logger.exception("Historical backfill failed: %s", exc)

    weeks = db.get_history_weeks(limit=HISTORY_WEEKS_PAGE_SIZE)
    selected_week = db.get_history_week(week) if week else (weeks[0] if weeks else None)
    if not selected_week and weeks:
        selected_week = weeks[0]
    selected_start = selected_week["week_start"] if selected_week else None
    all_rankings = db.get_history_rankings(selected_start) if selected_start else []
    rankings = [ranking for ranking in all_rankings if ranking["hardcore_points"] > 0]

    for ranking in rankings:
        ranking["hardcore_points_display"] = format_points(ranking["hardcore_points"])
        ranking["retro_points_display"] = format_points(ranking["retro_points"])

    week_options = [
        {**item, "label": readable_week_range(item["week_start"], item["week_end"])}
        for item in weeks
    ]
    summary = {
        "achievements": sum(item["achievements_earned"] for item in all_rankings),
        "hardcore_points": sum(item["hardcore_points"] for item in all_rankings),
        "retro_points": sum(item["retro_points"] for item in all_rankings),
        "beaten": None,
        "masteries": None,
    }
    summary["achievements_display"] = format_points(summary["achievements"])
    summary["hardcore_points_display"] = format_points(summary["hardcore_points"])
    summary["retro_points_display"] = format_points(summary["retro_points"])

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "weeks": week_options,
            "weeks_page_size": HISTORY_WEEKS_PAGE_SIZE,
            "has_more_weeks": db.history_week_count() > len(weeks),
            "selected_week_start": selected_start,
            "selected_week_label": (
                readable_week_range(selected_week["week_start"], selected_week["week_end"])
                if selected_week
                else "No completed weeks"
            ),
            "rankings": rankings,
            "summary": summary,
            "backfill_pending": backfill_pending,
        },
    )


@app.get("/history/weeks")
async def history_weeks(offset: int = 0):
    offset = max(offset, 0)
    weeks = db.get_history_weeks(limit=HISTORY_WEEKS_PAGE_SIZE, offset=offset)
    total = db.history_week_count()
    return {
        "items": [
            {
                "week_start": item["week_start"],
                "label": readable_week_range(item["week_start"], item["week_end"]),
            }
            for item in weeks
        ],
        "has_more": offset + len(weeks) < total,
    }


@app.get("/charts")
async def charts(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="charts.html",
        context={
            "chart_js_version": static_asset_version(os.path.join("static", "js", "charts.js")),
        },
    )


@app.get("/api/charts/weekly")
async def weekly_chart_data(weeks: int = 8):
    selected_range = weeks if weeks in CHART_WEEK_RANGES else 8
    history = db.get_weekly_chart_history(selected_range)
    return {
        "range_weeks": selected_range,
        "available_weeks": db.history_week_count(),
        "weeks": [
            {
                "week_start": week["week_start"],
                "week_end": week["week_end"],
                "label": readable_week_range(week["week_start"], week["week_end"]),
                "users": [
                    {
                        "user_key": ranking["user_key"],
                        "canonical_username": ranking["canonical_username"],
                        "ra_username": ranking["ra_username"],
                        "ra_ulid": ranking["ra_ulid"],
                        "hardcore_points": ranking["hardcore_points"],
                        "retro_points": ranking["retro_points"],
                        "rank": ranking["rank"],
                    }
                    for ranking in week["rankings"]
                ],
            }
            for week in history
        ],
    }


@app.get("/display")
async def display(request: Request):
    if not db.setup_complete():
        return templates.TemplateResponse(
            request=request,
            name="display_setup_required.html",
            context=local_device_details(request),
        )
    context = await dashboard_context()
    context.update(local_device_details(request))
    return templates.TemplateResponse(
        request=request,
        name="display.html",
        context=context,
    )


@app.get("/display/dashboard-qr.png", include_in_schema=False)
async def display_dashboard_qr(request: Request):
    dashboard_url = local_device_details(request)["dashboard_url"]
    image_bytes = qr_code_png(dashboard_url)
    if image_bytes is None:
        return Response(status_code=503)
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/display/events")
async def display_events(request: Request):
    queue = asyncio.Queue()
    display_event_queues.add(queue)

    async def event_stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                event_type = event.get("type", "achievement")
                yield f"event: {event_type}\ndata: {json.dumps(event)}\n\n"
        finally:
            display_event_queues.discard(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/update/status")
async def application_update_status():
    return await application_updater.status()


@app.post("/api/update/check")
async def check_for_application_update():
    return await application_updater.check()


@app.post("/api/update/install", status_code=202)
async def install_application_update(request: Request):
    origin = request.headers.get("origin")
    expected_origin = str(request.base_url).rstrip("/")
    if origin and origin.rstrip("/") != expected_origin:
        raise HTTPException(status_code=403, detail="Cross-origin update requests are not allowed.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(status_code=403, detail="Cross-site update requests are not allowed.")
    try:
        return await application_updater.install()
    except UpdateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.on_event("startup")
async def start_background_polling():
    global achievement_poll_task
    application_updater.start()
    if not db.setup_complete():
        return
    schedule_history_backfill()
    if achievement_poll_task and not achievement_poll_task.done():
        return
    achievement_poll_task = asyncio.create_task(achievement_poll_loop())


@app.on_event("shutdown")
async def stop_update_polling():
    await application_updater.stop()


async def dashboard_context():
    users = db.get_tracked_users()
    week_start, week_end = current_week_range()
    week_start_key = week_start.isoformat()
    weekly_cache = db.get_weekly_rankings(week_start_key)
    profile_cache = db.get_user_profiles()
    currently_playing_cache = db.get_currently_playing_cache()

    def enrich(u):
        username_key = u["ra_username"].lower()
        cached_profile = profile_cache.get(username_key, {})
        cached_weekly = weekly_cache.get(username_key, {})
        cached_current = currently_playing_cache.get(username_key, {})

        hardcore_points = cached_profile.get("hardcore_points", 0)
        retro_points = cached_profile.get("retro_points", 0)
        weekly_hardcore_points = cached_weekly.get("hardcore_points", 0)
        weekly_retro_points = cached_weekly.get("retro_points", 0)
        currently_playing = None

        if (
            cached_current.get("active")
            and cached_current.get("payload")
            and not cache_is_stale(cached_current.get("refreshed_at"), CURRENTLY_PLAYING_CACHE_TTL)
        ):
            currently_playing = {
                **cached_current["payload"],
                "hardcore_points_display": format_points(cached_current["payload"].get("hardcore_points", 0)),
                "total_points_display": format_points(cached_current["payload"].get("total_points", 0)),
            }

        return {
            "id": u["id"],
            "username": cached_profile.get("canonical_username") or u["ra_username"],
            "ulid": cached_profile.get("ra_ulid") or u.get("ra_ulid"),
            "avatar": cached_profile.get("avatar"),
            "hardcore": hardcore_points,
            "retro_points": retro_points,
            "weekly_hardcore": weekly_hardcore_points,
            "weekly_retro_points": weekly_retro_points,
            "hardcore_display": format_points(hardcore_points),
            "retro_points_display": format_points(retro_points),
            "weekly_hardcore_display": format_points(weekly_hardcore_points),
            "weekly_retro_points_display": format_points(weekly_retro_points),
            "currently_playing": currently_playing,
        }

    recent_activity = prepare_recent_activity(db.get_recent_activity(limit=RECENT_ACTIVITY_LIMIT))
    enriched = [enrich(u) for u in users]

    schedule_user_snapshot_refresh_if_needed(users, profile_cache, currently_playing_cache)
    schedule_weekly_refresh_if_needed(users, weekly_cache, week_start, week_end)
    schedule_recent_activity_refresh_if_needed(users, recent_activity)

    enriched.sort(key=lambda x: x.get("hardcore", 0), reverse=True)
    weekly_users = sorted(
        (user for user in enriched if user.get("weekly_hardcore", 0) > 0),
        key=lambda x: (-x.get("weekly_hardcore", 0), x.get("username", "").lower()),
    )
    currently_playing_users = [u["currently_playing"] for u in enriched if u["currently_playing"]]

    return {
        "users": enriched,
        "weekly_users": weekly_users,
        "week_start_display": f"{week_start.strftime('%b')} {week_start.day}, {week_start.year}",
        "currently_playing_users": currently_playing_users,
        "recent_activity": recent_activity,
        "audio_enabled": db.audio_enabled(),
        "audio_sources": configured_audio_sources(),
        "display_js_version": static_asset_version(os.path.join("static", "js", "display.js")),
        "display_section_durations": display_section_durations(),
        "ra_connection_status": ra_connection_status(),
    }


@app.get("/admin")
async def admin(request: Request, message: str = None):
    await refresh_ra_connection_if_stale()
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "message": message,
            "audio_enabled": db.audio_enabled(),
            "audio_sources": configured_audio_sources(),
            "notification_durations": notification_durations(),
            "display_section_durations": display_section_durations(),
            "ra_api_key_source": ra_api_key_source(),
            "ra_connection_status": ra_connection_status(),
            "setup_complete": db.setup_complete(),
            "update_status": await application_updater.status(),
            "update_js_version": static_asset_version(os.path.join("static", "js", "update.js")),
        },
    )


@app.get("/users")
async def users(request: Request, message: str = None):
    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={"users": db.get_tracked_users(), "message": message},
    )


@app.post("/admin/history-backfill")
async def start_history_backfill():
    schedule_history_backfill(refresh_live=True)
    return history_backfill_status_payload()


@app.get("/admin/history-backfill/status")
async def get_history_backfill_status():
    return history_backfill_status_payload()


@app.post("/admin/add")
async def add_user(request: Request, username: str = Form(...)):
    username = username.strip()
    if not username:
        return users_redirect("Enter a RetroAchievements username.")

    try:
        info = await ra_client.lookup_user(username)
    except (aiohttp.ClientError, ValueError):
        return users_redirect("User not found or RetroAchievements API unavailable.")

    canonical = info.get("username", username)
    ulid = info.get("ulid")

    if db.tracked_user_exists(canonical, ulid):
        return users_redirect(f"Already tracking {canonical}.")

    db.add_tracked_user(canonical, ulid)
    return users_redirect(f"Added {canonical}.")


@app.post("/admin/api-key")
async def update_ra_api_key(api_key: str = Form(...)):
    api_key = api_key.strip()
    if not api_key:
        return admin_redirect("RetroAchievements API key was not changed: enter a key first.")

    if not await validate_ra_api_key(api_key):
        return admin_redirect("That API key could not connect. Your current key was not changed.")

    db.set_setting("ra_api_key", api_key)
    record_ra_connection(True)
    ra_client.api_key = api_key
    return admin_redirect("RetroAchievements API key verified and saved. The new key is active immediately.")


@app.post("/admin/reset-onboarding")
async def reset_onboarding():
    db.set_setup_complete(False)
    return onboarding_redirect(1, "Setup is ready to run again. Your players and history are still here.", "success")


@app.post("/admin/settings")
async def update_settings(
    request: Request,
    audio_enabled: str | None = Form(None),
    achievement_duration: str | None = Form(None),
    beaten_duration: str | None = Form(None),
    mastery_duration: str | None = Form(None),
    overall_section_duration: str | None = Form(None),
    weekly_section_duration: str | None = Form(None),
    current_section_duration: str | None = Form(None),
    recent_section_duration: str | None = Form(None),
    achievement_audio: UploadFile | None = File(None),
    beaten_audio: UploadFile | None = File(None),
    mastery_audio: UploadFile | None = File(None),
):
    db.set_audio_enabled(audio_enabled == "1")
    set_notification_seconds("achievement", achievement_duration)
    set_notification_seconds("beaten", beaten_duration)
    set_notification_seconds("mastery", mastery_duration)
    set_display_section_seconds("overall", overall_section_duration)
    set_display_section_seconds("weekly", weekly_section_duration)
    set_display_section_seconds("current", current_section_duration)
    set_display_section_seconds("recent", recent_section_duration)
    messages = ["Settings saved."]
    for kind, upload in (
        ("achievement", achievement_audio),
        ("beaten", beaten_audio),
        ("mastery", mastery_audio),
    ):
        message = await save_custom_audio(kind, upload)
        if message:
            messages.append(message)
    return admin_redirect(" ".join(messages))


@app.post("/admin/test-alert/{alert_type}")
async def test_display_alert(alert_type: str):
    test_events = {
        "achievement": {
            "type": "achievement",
            "dedupe_key": "test:achievement",
            "username": TEST_USERNAME,
            "avatar": TEST_USER_AVATAR,
            "achievement_id": TEST_ACHIEVEMENT_ID,
            "achievement_title": TEST_ACHIEVEMENT_TITLE,
            "achievement_description": TEST_ACHIEVEMENT_DESCRIPTION,
            "achievement_badge": TEST_ACHIEVEMENT_BADGE,
            "game_title": TEST_GAME_TITLE,
            "game_id": TEST_GAME_ID,
            "points": 1,
            "points_display": "1",
            "retro_points": 1,
            "retro_points_display": "1",
            "unlock_time_iso": datetime.now(timezone.utc).isoformat(),
            "unlock_time_display": "Now",
            "hardcore": True,
            "completion_before_percentage": 42,
            "completion_after_percentage": 43,
            "duration_ms": notification_seconds("achievement") * 1000,
        },
        "beaten": {
            "type": "beaten",
            "dedupe_key": "test:beaten",
            "username": TEST_USERNAME,
            "avatar": TEST_USER_AVATAR,
            "game_id": TEST_GAME_ID,
            "game_title": TEST_GAME_TITLE,
            "game_image": TEST_GAME_IMAGE,
            "hardcore_achievements": 54,
            "total_achievements": 69,
            "hardcore_points": 650,
            "total_points": 800,
            "hardcore_points_display": "650",
            "total_points_display": "800",
            "awarded_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": notification_seconds("beaten") * 1000,
        },
        "mastery": {
            "type": "mastery",
            "dedupe_key": "test:mastery",
            "username": TEST_USERNAME,
            "avatar": TEST_USER_AVATAR,
            "game_id": TEST_GAME_ID,
            "game_title": TEST_GAME_TITLE,
            "game_image": TEST_GAME_IMAGE,
            "hardcore_achievements": 69,
            "total_achievements": 69,
            "hardcore_points": 800,
            "total_points": 800,
            "hardcore_points_display": "800",
            "total_points_display": "800",
            "awarded_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": notification_seconds("mastery") * 1000,
        },
    }
    event = test_events.get(alert_type)
    if event is None:
        return admin_redirect("Unknown display alert type.")
    await publish_display_event(event)
    return admin_redirect(f"Sent {alert_type} test alert to connected displays.")


@app.post("/admin/remove")
async def remove_user(request: Request, user_id: int = Form(...)):
    db.remove_tracked_user(user_id)
    return users_redirect("Removed user.")
