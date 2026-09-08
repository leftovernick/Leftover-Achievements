import os
import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlencode

import aiohttp
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
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


def admin_redirect(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/admin?{urlencode({'message': message})}", status_code=303)


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


@app.get("/")
async def dashboard(request: Request):
    users = db.get_tracked_users()
    week_start, week_end = current_week_range()

    async def enrich(u):
        target = u["ra_ulid"] or u["ra_username"]
        weekly_points = {
            "hardcore_points": 0,
            "retro_points": 0,
        }

        try:
            info = await ra_client.lookup_user(target)
        except (aiohttp.ClientError, ValueError):
            info = {}

        try:
            currently_playing = await ra_client.currently_playing(target)
        except (aiohttp.ClientError, ValueError):
            currently_playing = None

        try:
            weekly_points = await ra_client.points_earned_between(target, week_start, week_end)
        except (aiohttp.ClientError, ValueError):
            weekly_points = {
                "hardcore_points": 0,
                "retro_points": 0,
            }

        hardcore_points = info.get("hardcore_points", 0)
        retro_points = info.get("retro_points", 0)
        weekly_hardcore_points = weekly_points.get("hardcore_points", 0)
        weekly_retro_points = weekly_points.get("retro_points", 0)

        if currently_playing:
            currently_playing = {
                **currently_playing,
                "hardcore_points_display": format_points(currently_playing["hardcore_points"]),
                "total_points_display": format_points(currently_playing["total_points"]),
            }

        return {
            "id": u["id"],
            "username": info.get("username", u["ra_username"]),
            "ulid": info.get("ulid", u.get("ra_ulid")),
            "avatar": info.get("avatar"),
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

    async def recent_activity_for_user(u, recent_minutes: int):
        target = u["ra_ulid"] or u["ra_username"]
        try:
            return await ra_client.recent_hardcore_achievements(target, recent_minutes=recent_minutes)
        except (aiohttp.ClientError, ValueError):
            return []

    async def latest_recent_activity():
        recent_activity = db.get_recent_activity(limit=RECENT_ACTIVITY_LIMIT)
        if len(recent_activity) >= RECENT_ACTIVITY_LIMIT:
            return prepare_recent_activity(recent_activity)

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

        return prepare_recent_activity(db.get_recent_activity(limit=RECENT_ACTIVITY_LIMIT))

    def prepare_recent_activity(recent_activity):
        for activity in recent_activity:
            activity["points_display"] = format_points(activity["points"])
            activity["retro_points_display"] = format_points(activity["retro_points"])
            activity["unlock_time_iso"] = activity.get("unlock_time_iso") or activity["unlock_time"]
        return recent_activity

    enriched = await asyncio.gather(*(enrich(u) for u in users))
    recent_activity = await latest_recent_activity()
    enriched.sort(key=lambda x: x.get("hardcore", 0), reverse=True)
    weekly_users = sorted(enriched, key=lambda x: (-x.get("weekly_hardcore", 0), x.get("username", "").lower()))
    currently_playing_users = [u["currently_playing"] for u in enriched if u["currently_playing"]]

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "users": enriched,
            "weekly_users": weekly_users,
            "currently_playing_users": currently_playing_users,
            "recent_activity": recent_activity,
        },
    )


@app.get("/admin")
async def admin(request: Request, message: str = None):
    users = db.get_tracked_users()
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={"users": users, "message": message},
    )


@app.post("/admin/add")
async def add_user(request: Request, username: str = Form(...)):
    username = username.strip()
    if not username:
        return admin_redirect("Enter a RetroAchievements username.")

    try:
        info = await ra_client.lookup_user(username)
    except (aiohttp.ClientError, ValueError):
        return admin_redirect("User not found or RetroAchievements API unavailable.")

    canonical = info.get("username", username)
    ulid = info.get("ulid")

    if db.tracked_user_exists(canonical, ulid):
        return admin_redirect(f"Already tracking {canonical}.")

    db.add_tracked_user(canonical, ulid)
    return admin_redirect(f"Added {canonical}.")


@app.post("/admin/remove")
async def remove_user(request: Request, user_id: int = Form(...)):
    db.remove_tracked_user(user_id)
    return admin_redirect("Removed user.")
