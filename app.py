import os
import asyncio
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import aiohttp
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from database import database as db
from services.retroachievements import RetroAchievements


load_dotenv()

app = FastAPI(title="LeftoverAchievements Display")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

db.init_db()
ra_client = RetroAchievements(api_key=os.getenv("RA_API_KEY"))
RECENT_ACTIVITY_LIMIT = 5
RECENT_ACTIVITY_FETCH_MINUTES = 43200
WEEKLY_CACHE_TTL = timedelta(minutes=10)
PROFILE_CACHE_TTL = timedelta(minutes=5)
CURRENTLY_PLAYING_CACHE_TTL = timedelta(seconds=75)
weekly_refresh_task = None
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


def admin_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?{urlencode({'message': message})}", status_code=303)


def users_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/users?{urlencode({'message': message})}", status_code=303)


def current_week_range() -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    week_start = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    return week_start, now


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


def serialize_achievement_event(activity: dict) -> dict:
    return {
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
    for activity in new_activities:
        db.save_processed_achievement_unlock(activity, announced=True)
        db.save_recent_activity(activity, keep_limit=RECENT_ACTIVITY_LIMIT)
        await publish_display_event(serialize_achievement_event(activity))


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
    context = await dashboard_context()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
    )


@app.get("/display")
async def display(request: Request):
    context = await dashboard_context()
    return templates.TemplateResponse(
        request=request,
        name="display.html",
        context=context,
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


@app.on_event("startup")
async def start_background_polling():
    global achievement_poll_task
    if achievement_poll_task and not achievement_poll_task.done():
        return
    achievement_poll_task = asyncio.create_task(achievement_poll_loop())


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
    }


@app.get("/admin")
async def admin(request: Request, message: str = None):
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "message": message,
            "audio_enabled": db.audio_enabled(),
            "audio_sources": configured_audio_sources(),
            "notification_durations": notification_durations(),
            "display_section_durations": display_section_durations(),
        },
    )


@app.get("/users")
async def users(request: Request, message: str = None):
    return templates.TemplateResponse(
        request=request,
        name="users.html",
        context={"users": db.get_tracked_users(), "message": message},
    )


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
