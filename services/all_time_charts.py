"""Resumable, on-demand monthly account-history reconstruction."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone, time
from urllib.parse import urljoin

import aiohttp

from .background_tasks import create_logged_task


logger = logging.getLogger(__name__)
REFRESH_INTERVAL = timedelta(hours=1)
FAILURE_RETRY_INTERVAL = timedelta(minutes=5)
WEEKDAY_LABELS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTH_LABELS = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")
RA_BASE_URL = "https://retroachievements.org"


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
        row = days.setdefault(day, {"hardcore_points": 0, "retro_points": 0,
                                    "achievements_earned": 0, "games": {}})
        row["hardcore_points"] += int(achievement.get("Points") or achievement.get("points") or 0)
        row["retro_points"] += int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0)
        row["achievements_earned"] += 1
        game_id = int(achievement.get("GameID") or achievement.get("gameId") or 0)
        if game_id:
            game_image = achievement.get("GameIcon") or achievement.get("gameIcon")
            game = row["games"].setdefault(game_id, {
                "game_id": game_id,
                "game_title": achievement.get("GameTitle") or achievement.get("gameTitle") or f"Game #{game_id}",
                "game_image": urljoin(RA_BASE_URL, game_image) if game_image else None,
                "console": achievement.get("ConsoleName") or achievement.get("consoleName"),
                "achievements_earned": 0,
                "hardcore_points": 0,
                "retro_points": 0,
            })
            game["achievements_earned"] += 1
            game["hardcore_points"] += int(achievement.get("Points") or achievement.get("points") or 0)
            game["retro_points"] += int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0)
        points = int(achievement.get("Points") or achievement.get("points") or 0)
        if points > 0 and (not row.get("first_achievement_at") or earned < parse_date(row["first_achievement_at"])):
            row.update(first_achievement_at=earned.isoformat(), first_hardcore_points=points,
                       first_retro_points=int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0))
    for row in days.values():
        row["games"] = sorted(row["games"].values(), key=lambda game: game["game_title"].lower())
    return days


def first_score_point(rows, as_of):
    scoring_days = [(day, values) for row in rows.values() for day, values in (row.get("days") or {}).items()
                    if values["hardcore_points"] > 0]
    if not scoring_days:
        return None
    day = min(day for day, _ in scoring_days)
    parts = [values for date, values in scoring_days if date == day]
    if all(values.get("first_achievement_at") for values in parts):
        first = min(parts, key=lambda values: parse_date(values["first_achievement_at"]))
        return {"date": first["first_achievement_at"], "hardcore_points": first["first_hardcore_points"],
                "retro_points": first["first_retro_points"]}
    # Older caches retain daily totals, not exact unlock times. Start at the
    # first scoring day; this is a daily aggregate, not an exact unlock timestamp.
    start_of_day = datetime.combine(datetime.fromisoformat(day).date(), time.min).astimezone().astimezone(timezone.utc)
    return {"date": min(start_of_day, parse_date(as_of)).isoformat(),
            **{field: sum(values[field] for values in parts) for field in ("hardcore_points", "retro_points")}}


def weekly_curve_points(rows, first, now):
    """Turn the cached daily totals underlying History into weekly cumulative anchors."""
    if not first:
        return []
    days = {day: values for row in rows.values() for day, values in (row.get("days") or {}).items()}
    first_date = parse_date(first["date"]).astimezone().date()
    monday = first_date - timedelta(days=first_date.weekday())
    current_monday = now.astimezone().date() - timedelta(days=now.astimezone().date().weekday())
    cumulative = {"hardcore_points": 0, "retro_points": 0}
    points = [first]
    while monday < current_monday:
        following = monday + timedelta(days=7)
        for day, values in days.items():
            if monday.isoformat() <= day < following.isoformat():
                for field in cumulative:
                    cumulative[field] += values[field]
        end = datetime.combine(following, time.min).astimezone() - timedelta(seconds=1)
        if end.astimezone(timezone.utc) > parse_date(first["date"]):
            points.append({"date": end.astimezone(timezone.utc).isoformat(), **cumulative})
        monday = following
    return points


def week_stats(profile, months, start, end):
    """Return cached range stats only when every overlapping month is covered."""
    joined = parse_date(profile["member_since"])
    stats = {"hardcore_points": 0, "retro_points": 0, "achievements_earned": 0}
    games = {}
    if end < joined:
        stats["played_games"] = []
        return stats
    for month, _, required_end in month_ranges(max(start, joined), end):
        row = months.get(month.date().isoformat())
        if not row or row.get("days") is None or parse_date(row["covered_through"]) < required_end:
            return None
        for day, values in row["days"].items():
            if start.astimezone().date().isoformat() <= day <= end.astimezone().date().isoformat():
                for field in stats:
                    stats[field] += values[field]
                if "games" not in values:
                    return None
                for game in values["games"]:
                    combined = games.setdefault(game["game_id"], {
                        **game, "achievements_earned": 0, "hardcore_points": 0, "retro_points": 0,
                    })
                    for field in ("achievements_earned", "hardcore_points", "retro_points"):
                        combined[field] += int(game.get(field) or 0)
                    if not combined.get("game_image") and game.get("game_image"):
                        combined["game_image"] = game["game_image"]
                    if not combined.get("console") and game.get("console"):
                        combined["console"] = game["console"]
    stats["played_games"] = sorted(games.values(), key=lambda game: game["game_title"].lower())
    return stats


def weekday_achievement_activity(completed_users):
    """Average hardcore unlocks for each weekday across eligible player-days."""
    totals = [0] * 7
    eligible_days = [0] * 7
    for joined, as_of, rows in completed_users:
        first_day = joined.astimezone().date()
        last_day = as_of.astimezone().date()
        current = first_day
        while current <= last_day:
            eligible_days[current.weekday()] += 1
            current += timedelta(days=1)
        for row in rows.values():
            for day, values in (row.get("days") or {}).items():
                earned_day = date.fromisoformat(day)
                if first_day <= earned_day <= last_day:
                    totals[earned_day.weekday()] += int(values.get("achievements_earned") or 0)
    return [
        {
            "weekday": label,
            "achievements_earned": totals[index],
            "eligible_days": eligible_days[index],
            "average": totals[index] / eligible_days[index] if eligible_days[index] else 0,
        }
        for index, label in enumerate(WEEKDAY_LABELS)
    ]


def monthly_achievement_activity(completed_users):
    """Average hardcore unlocks for each month across eligible player-months."""
    totals = [0] * 12
    eligible_months = [0] * 12
    for joined, as_of, rows in completed_users:
        first_day = joined.astimezone().date()
        last_day = as_of.astimezone().date()
        current = first_day.replace(day=1)
        final_month = last_day.replace(day=1)
        while current <= final_month:
            eligible_months[current.month - 1] += 1
            current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
        for row in rows.values():
            for day, values in (row.get("days") or {}).items():
                earned_day = date.fromisoformat(day)
                if first_day <= earned_day <= last_day:
                    totals[earned_day.month - 1] += int(values.get("achievements_earned") or 0)
    return [
        {
            "month": label,
            "achievements_earned": totals[index],
            "eligible_months": eligible_months[index],
            "average": totals[index] / eligible_months[index] if eligible_months[index] else 0,
        }
        for index, label in enumerate(MONTH_LABELS)
    ]


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
        if any("games" not in values for values in row["days"].values()):
            return False
        covered = parse_date(row["covered_through"])
        return covered >= end or (end == now and now - covered < REFRESH_INTERVAL)

    def payload(self, users, now=None):
        now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        profiles, months = self.db.get_all_time_chart_cache()
        masteries = self.db.get_recorded_chart_masteries([user["ra_username"] for user in users], now)
        beaten = self.db.get_recorded_chart_beaten_games([user["ra_username"] for user in users], now)
        series = []
        completed_activity_users = []
        needs_refresh = False
        oldest = None
        for user in users:
            username = user["ra_username"]
            cached = profiles.get(username.lower())
            result = {"username": username, "user_key": f"username:{username.lower()}",
                      "points": [], "ready": False, "error": self.errors.get(username.lower()),
                      "masteries": masteries.get(username.lower(), []),
                      "beaten": beaten.get(username.lower(), [])}
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
            key = profile_key(profile)
            result.update(username=profile["username"], user_key=key, joined_at=joined.isoformat(),
                          as_of=cached["refreshed_at"])
            rows = months.get(key, {})
            cumulative = {"hardcore_points": 0, "retro_points": 0}
            points = []
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
                first = first_score_point(rows, cached["refreshed_at"])
                if first:
                    points = weekly_curve_points(rows, first, now)
                else:
                    points = []  # No historical unlock date is invented when only the reported total is known.
                if first or profile["hardcore_points"] > 0:
                    if points and points[-1]["date"] == cached["refreshed_at"]:
                        points.pop()
                    points.append({"date": cached["refreshed_at"],
                                   "hardcore_points": profile["hardcore_points"],
                                   "retro_points": profile["retro_points"]})
                    start = parse_date(points[0]["date"])
                    oldest = min(oldest, start) if oldest else start
                result.update(points=points, ready=True)
                completed_activity_users.append((joined, min(now, parse_date(cached["refreshed_at"])), rows))
            else:
                needs_refresh = True
            if now - parse_date(cached["refreshed_at"]) >= REFRESH_INTERVAL:
                needs_refresh = True
            series.append(result)
        return {"users": series, "start": oldest.isoformat() if oldest else None,
                "end": now.isoformat(), "needs_refresh": needs_refresh,
                "building": bool(self.task and not self.task.done()),
                "progress": dict(self.progress),
                "ready_users": sum(item["ready"] for item in series),
                "weekday_activity": weekday_achievement_activity(completed_activity_users),
                "monthly_activity": monthly_achievement_activity(completed_activity_users)}

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
            existing = self.db.get_history_user_weeks_with_games(key)
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
