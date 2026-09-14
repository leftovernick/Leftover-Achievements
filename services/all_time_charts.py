"""Resumable, on-demand monthly account-history reconstruction."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone, time

import aiohttp

from .background_tasks import create_logged_task


logger = logging.getLogger(__name__)
REFRESH_INTERVAL = timedelta(hours=1)
FAILURE_RETRY_INTERVAL = timedelta(minutes=5)


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("Date is unavailable")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return date.replace(tzinfo=timezone.utc) if date.tzinfo is None else date.astimezone(timezone.utc)


def profile_key(profile):
    return (f"ulid:{profile['ulid']}" if profile.get("ulid") else f"username:{profile['username']}").lower()


def month_ranges(joined, now):
    joined = joined.astimezone(timezone.utc)
    now = now.astimezone(timezone.utc)
    start = joined.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while start <= now:
        following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield start, max(start, joined), min(following - timedelta(seconds=1), now)
        start = following


def daily_points(achievements, start, end):
    """Retain local-calendar daily totals for both lifetime curves and weekly history."""
    days = {}
    seen = set()
    for achievement in achievements:
        if achievement.get("HardcoreMode", achievement.get("hardcoreMode")) not in (1, "1", True):
            continue
        earned = parse_date(achievement.get("Date") or achievement.get("date"))
        if not start <= earned <= end:
            continue
        achievement_id = achievement.get("AchievementID") or achievement.get("achievementId")
        if achievement_id is not None:
            if achievement_id in seen:
                continue
            seen.add(achievement_id)
        day = earned.astimezone().date().isoformat()
        row = days.setdefault(day, {"hardcore_points": 0, "retro_points": 0, "achievements_earned": 0})
        row["hardcore_points"] += int(achievement.get("Points") or achievement.get("points") or 0)
        row["retro_points"] += int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0)
        row["achievements_earned"] += 1
    return days


def week_stats(profile, months, start, end):
    """Return cached range stats only when every overlapping month is covered."""
    joined = parse_date(profile["member_since"])
    stats = {"hardcore_points": 0, "retro_points": 0, "achievements_earned": 0}
    if end < joined:
        return stats
    for month, _, required_end in month_ranges(max(start, joined), end):
        row = months.get(month.date().isoformat())
        if not row or row.get("days") is None or parse_date(row["covered_through"]) < required_end:
            return None
        for day, values in row["days"].items():
            if start.astimezone().date().isoformat() <= day <= end.astimezone().date().isoformat():
                for field in stats:
                    stats[field] += values[field]
    return stats


class AllTimeCharts:
    def __init__(self, client, database):
        self.client = client
        self.db = database
        self.task = None
        self.errors = {}
        self.progress = {"completed": 0, "total": 0, "current": None}
        self.next_attempt = datetime.min.replace(tzinfo=timezone.utc)
        self.history_materialized = False

    @staticmethod
    def month_is_fresh(row, end, now):
        if not row or row.get("days") is None:
            return False
        covered = parse_date(row["covered_through"])
        return covered >= end or (end == now and now - covered < REFRESH_INTERVAL)

    def payload(self, users, now=None):
        now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        profiles, months = self.db.get_all_time_chart_cache()
        series = []
        needs_refresh = False
        oldest = None
        for user in users:
            username = user["ra_username"]
            cached = profiles.get(username.lower())
            result = {"username": username, "user_key": f"username:{username.lower()}",
                      "points": [], "ready": False, "error": self.errors.get(username.lower())}
            if not cached:
                needs_refresh = True
                series.append(result)
                continue
            profile = cached["profile"]
            try:
                joined = parse_date(profile["member_since"])
                if joined > now:
                    raise ValueError("Account creation date is in the future")
            except (ValueError, TypeError, KeyError):
                result["error"] = "Account creation date unavailable"
                needs_refresh = True
                series.append(result)
                continue
            oldest = min(oldest, joined) if oldest else joined
            key = profile_key(profile)
            result.update(username=profile["username"], user_key=key, joined_at=joined.isoformat(),
                          as_of=cached["refreshed_at"])
            rows = months.get(key, {})
            cumulative = {"hardcore_points": 0, "retro_points": 0}
            points = [{"date": joined.isoformat(), **cumulative}]
            complete = True
            for month, _, end in month_ranges(joined, now):
                row = rows.get(month.date().isoformat())
                if not row or row.get("days") is None:
                    complete = False
                    break  # Missing data is never treated as zero or interpolated.
                if end < now and parse_date(row["covered_through"]) < end:
                    complete = False  # A formerly current month must be finished first.
                    break
                for field in cumulative:
                    cumulative[field] += row[field]
                if end < now:
                    points.append({"date": end.isoformat(), **cumulative})
                if not self.month_is_fresh(row, end, now):
                    needs_refresh = True
            if complete:
                points.append({"date": cached["refreshed_at"],
                               "hardcore_points": profile["hardcore_points"],
                               "retro_points": profile["retro_points"]})
                result.update(points=points, ready=True)
            else:
                needs_refresh = True
            if now - parse_date(cached["refreshed_at"]) >= REFRESH_INTERVAL:
                needs_refresh = True
            series.append(result)
        return {"users": series, "start": oldest.isoformat() if oldest else None,
                "end": now.isoformat(), "needs_refresh": needs_refresh,
                "building": bool(self.task and not self.task.done()),
                "progress": dict(self.progress),
                "ready_users": sum(item["ready"] for item in series)}

    def schedule(self, users, force=False):
        if not users or (self.task and not self.task.done()):
            return
        now = datetime.now(timezone.utc)
        if not self.history_materialized:
            self.materialize_history(users, now)
            self.history_materialized = True
        if not force and (now < self.next_attempt or not self.payload(users, now)["needs_refresh"]):
            return
        self.errors = {}
        self.progress = {"completed": 0, "total": 0, "current": "Account profiles"}
        self.task = create_logged_task(self.refresh(users, force), "all-time chart backfill")

    async def refresh(self, users, force=False, now=None):
        now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        self.errors = {}
        self.next_attempt = now + FAILURE_RETRY_INTERVAL
        profiles, months = self.db.get_all_time_chart_cache()
        for user in users:
            username = user["ra_username"]
            cached = profiles.get(username.lower())
            refreshed = parse_date(cached["refreshed_at"]) if cached else None
            if (not force and cached and cached["profile"].get("member_since")
                    and (refreshed.year, refreshed.month) == (now.year, now.month)
                    and now - refreshed < REFRESH_INTERVAL):
                continue
            try:
                profile = await self.client.lookup_user(user.get("ra_ulid") or username)
                joined = parse_date(profile["member_since"])
                if joined > now:
                    raise ValueError("Account creation date is in the future")
                self.db.save_all_time_chart_profile(username, profile, now)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Could not load all-time profile for %s: %s: %s", username, type(exc).__name__, exc)
                self.errors[username.lower()] = "Could not load account profile. Retry when connectivity is restored."
            await asyncio.sleep(0.75)  # Yield to live activity/award polling using the shared API client.

        profiles, months = self.db.get_all_time_chart_cache()
        jobs = []
        for user in users:
            username = user["ra_username"]
            cached = profiles.get(username.lower())
            if not cached or username.lower() in self.errors:
                continue
            profile = cached["profile"]
            joined = parse_date(profile["member_since"])
            key = profile_key(profile)
            for month, start, end in month_ranges(joined, now):
                row = months.get(key, {}).get(month.date().isoformat())
                if not self.month_is_fresh(row, end, now) or (force and end == now):
                    jobs.append((username, profile.get("ulid") or profile["username"], key, month, start, end))
        self.progress.update(total=len(jobs), completed=0)
        for username, target, key, month, start, end in jobs:
            if username.lower() in self.errors:
                continue
            self.progress["current"] = f"{username} · {month:%b %Y}"
            try:
                achievements = await self.client.achievements_earned_between(target, start, end)
                days = daily_points(achievements, start, end)
                points = {field: sum(day[field] for day in days.values()) for field in ("hardcore_points", "retro_points")}
                self.db.save_all_time_chart_month(key, month.date().isoformat(), points, end, days)
                self.progress["completed"] += 1
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError, KeyError) as exc:
                logger.warning("Could not backfill all-time chart for %s during %s: %s: %s", username, month.date(), type(exc).__name__, exc)
                self.errors[username.lower()] = "History incomplete. Saved progress will resume on retry."
            await asyncio.sleep(0.75)
        self.progress["current"] = None
        self.materialize_history(users, now)

    def cached_week_stats(self, username, start, end, cache=None):
        profiles, months = cache if cache is not None else self.db.get_all_time_chart_cache()
        cached = profiles.get(username.lower())
        if not cached:
            return None
        profile = cached["profile"]
        return week_stats(profile, months.get(profile_key(profile), {}), start, end)

    def materialize_history(self, users, now):
        """Fill completed weekly snapshots from the same monthly API responses."""
        profiles, months = self.db.get_all_time_chart_cache()
        today = now.astimezone().date()
        current_monday = today - timedelta(days=today.weekday())
        for user in users:
            username = user["ra_username"]
            cached = profiles.get(username.lower())
            if not cached:
                continue
            profile = cached["profile"]
            try:
                joined = parse_date(profile["member_since"]).astimezone().date()
            except (ValueError, KeyError):
                continue
            monday = joined - timedelta(days=joined.weekday())
            key = profile_key(profile)
            rows = months.get(key, {})
            existing = self.db.get_history_user_weeks(key)
            snapshots = []
            while monday < current_monday:
                following = monday + timedelta(days=7)
                start = datetime.combine(monday, time.min).astimezone()
                end = datetime.combine(following, time.min).astimezone() - timedelta(seconds=1)
                if monday.isoformat() not in existing:
                    stats = week_stats(profile, rows, start, end)
                    if stats is not None:
                        snapshots.append({
                            "week_start": monday.isoformat(), "week_end": (following - timedelta(days=1)).isoformat(),
                            "user_key": key, "ra_username": username, "canonical_username": profile["username"],
                            "ra_ulid": profile.get("ulid"), "avatar": profile.get("avatar"), **stats,
                        })
                monday = following
            self.db.save_completed_history_snapshots(snapshots)

    async def stop(self):
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
