import asyncio
import os
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import aiohttp
import certifi


RA_BASE_URL = "https://retroachievements.org"
RA_API_URL = f"{RA_BASE_URL}/API/"
CURRENT_ACTIVITY_WINDOW = timedelta(minutes=5)
REQUEST_INTERVAL_SECONDS = 0.75
RATE_LIMIT_RETRY_SECONDS = 3.0


class RetroAchievements:
    """Small RetroAchievements web API client for the dashboard."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("RA_API_KEY")
        self.base_url = base_url or RA_API_URL
        self.timeout = aiohttp.ClientTimeout(total=10)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.request_lock = asyncio.Lock()
        self.last_request_at = 0.0

    async def _get_json(self, endpoint: str, params: dict) -> dict | list:
        url = urljoin(self.base_url, endpoint)
        query_params = {**params, "y": self.api_key}

        for attempt in range(3):
            await self._wait_for_request_slot()
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, params=query_params, ssl=self.ssl_context) as resp:
                    if resp.status == 429 and attempt < 2:
                        retry_after = self._retry_after_seconds(resp)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status == 404:
                        raise ValueError("RetroAchievements resource not found")
                    if resp.status != 200:
                        raise ValueError(f"RetroAchievements API returned HTTP {resp.status}")
                    return await resp.json(content_type=None)

        raise ValueError("RetroAchievements API rate limit exceeded")

    async def _wait_for_request_slot(self):
        async with self.request_lock:
            elapsed = time.monotonic() - self.last_request_at
            wait_time = REQUEST_INTERVAL_SECONDS - elapsed
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            self.last_request_at = time.monotonic()

    def _retry_after_seconds(self, response: aiohttp.ClientResponse) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), REQUEST_INTERVAL_SECONDS)
            except ValueError:
                pass
        return RATE_LIMIT_RETRY_SECONDS

    async def lookup_user(self, username: str) -> dict:
        """Return normalized profile data for a RetroAchievements username or ULID."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        data = await self._get_json("API_GetUserProfile.php", {"u": target})
        if not isinstance(data, dict):
            raise ValueError("Unexpected RetroAchievements API response")

        canonical_username = data.get("User") or data.get("user")
        if not canonical_username:
            raise ValueError("RetroAchievements user not found")

        avatar = data.get("UserPic") or data.get("userPic")
        if avatar:
            avatar = urljoin(RA_BASE_URL, avatar)

        return {
            "username": canonical_username,
            "ulid": data.get("ULID") or data.get("ulid"),
            "avatar": avatar,
            "hardcore_points": int(data.get("TotalPoints") or data.get("totalPoints") or 0),
            "retro_points": int(data.get("TotalTruePoints") or data.get("totalTruePoints") or 0),
        }

    async def validate_api_key(self) -> bool:
        """Verify this key with a small, user-independent official API request."""
        if not self.api_key:
            return False

        data = await self._get_json("API_GetGame.php", {"i": 1})
        if not isinstance(data, dict):
            return False
        return bool(data.get("Title") or data.get("GameTitle") or data.get("title"))

    async def user_summary(self, username: str, recent_games_count: int = 1) -> dict:
        """Return raw user summary data from RetroAchievements."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        data = await self._get_json(
            "API_GetUserSummary.php",
            {
                "u": target,
                "g": recent_games_count,
                "a": 0,
            },
        )

        if not isinstance(data, dict):
            raise ValueError("Unexpected RetroAchievements API response")

        return data

    async def game_info_and_user_progress(self, username: str, game_id: int) -> dict:
        """Return raw game metadata and user progress from RetroAchievements."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        data = await self._get_json(
            "API_GetGameInfoAndUserProgress.php",
            {
                "u": target,
                "g": game_id,
                "a": 1,
            },
        )

        if not isinstance(data, dict):
            raise ValueError("Unexpected RetroAchievements API response")

        return data

    async def currently_playing(self, username: str) -> dict | None:
        """Return current active game details, or None if the user is inactive."""
        summary = await self.user_summary(username, recent_games_count=1)
        rich_presence = summary.get("RichPresenceMsg") or summary.get("richPresenceMsg") or ""
        rich_presence_date = summary.get("RichPresenceMsgDate") or summary.get("richPresenceMsgDate")
        game_id = summary.get("LastGameID") or summary.get("lastGameId")

        if not rich_presence.strip() or not game_id:
            return None

        game_id = int(game_id)
        current_game = self._current_game_from_summary(summary, game_id)
        if not self._has_recent_activity(rich_presence_date, current_game.get("last_played")):
            return None

        try:
            game_progress = await self.game_info_and_user_progress(username, game_id)
        except (aiohttp.ClientError, ValueError):
            game_progress = {}

        achievements = game_progress.get("Achievements") or game_progress.get("achievements") or {}
        if not isinstance(achievements, dict):
            achievements = {}

        total_achievements = int(
            game_progress.get("NumAchievements") or game_progress.get("numAchievements") or len(achievements)
        )
        hardcore_achievements = 0
        hardcore_points = 0
        total_points = 0

        for achievement in achievements.values():
            if not isinstance(achievement, dict):
                continue

            points = int(achievement.get("Points") or achievement.get("points") or 0)
            total_points += points
            if achievement.get("DateEarnedHardcore") or achievement.get("dateEarnedHardcore"):
                hardcore_achievements += 1
                hardcore_points += points

        if not total_points:
            total_points = int(game_progress.get("PossibleScore") or game_progress.get("possibleScore") or 0)

        completion_percentage = 0
        if total_achievements:
            completion_percentage = round((hardcore_achievements / total_achievements) * 100)

        game_title = current_game.get("title") or game_progress.get("Title") or game_progress.get("title") or "Unknown Game"
        game_image = (
            current_game.get("image")
            or game_progress.get("ImageIngame")
            or game_progress.get("imageIngame")
            or game_progress.get("ImageTitle")
            or game_progress.get("imageTitle")
            or game_progress.get("ImageIcon")
            or game_progress.get("imageIcon")
        )
        if game_image:
            game_image = urljoin(RA_BASE_URL, game_image)

        avatar = summary.get("UserPic") or summary.get("userPic")
        if avatar:
            avatar = urljoin(RA_BASE_URL, avatar)

        return {
            "username": summary.get("User") or summary.get("user") or username,
            "avatar": avatar,
            "game_title": game_title,
            "game_id": game_id,
            "game_image": game_image,
            "rich_presence": rich_presence,
            "hardcore_achievements": hardcore_achievements,
            "total_achievements": total_achievements,
            "completion_percentage": completion_percentage,
            "hardcore_points": hardcore_points,
            "total_points": total_points,
        }

    def _current_game_from_summary(self, summary: dict, game_id: int) -> dict:
        recently_played = summary.get("RecentlyPlayed") or summary.get("recentlyPlayed") or []
        if not isinstance(recently_played, list):
            return {}

        for game in recently_played:
            if not isinstance(game, dict):
                continue
            recent_game_id = game.get("GameID") or game.get("gameId")
            if int(recent_game_id or 0) != game_id:
                continue
            image = (
                game.get("ImageIngame")
                or game.get("imageIngame")
                or game.get("ImageTitle")
                or game.get("imageTitle")
                or game.get("ImageIcon")
                or game.get("imageIcon")
            )
            return {
                "title": game.get("Title") or game.get("title"),
                "image": image,
                "last_played": game.get("LastPlayed") or game.get("lastPlayed"),
            }

        return {}

    def _has_recent_activity(self, *timestamps: str | None) -> bool:
        return any(self._is_recent_datetime(timestamp) for timestamp in timestamps)

    def _is_recent_datetime(self, value: str | None) -> bool:
        parsed = self._parse_api_datetime(value)
        if not parsed:
            return False

        now = datetime.now().astimezone()
        age = now - parsed
        return timedelta(minutes=-1) <= age <= CURRENT_ACTIVITY_WINDOW

    def _parse_api_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None

        normalized = value.strip().replace("Z", "+00:00")

        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    parsed = datetime.strptime(normalized, date_format)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone()

    async def user_completion_progress(self, username: str, count: int = 500, offset: int = 0) -> dict:
        """Return a page of completion progress records for a RetroAchievements user."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        data = await self._get_json(
            "API_GetUserCompletionProgress.php",
            {
                "u": target,
                "c": count,
                "o": offset,
            },
        )

        if not isinstance(data, dict):
            raise ValueError("Unexpected RetroAchievements API response")

        return data

    async def hardcore_game_awards(self, username: str, fetch_all: bool = False) -> dict[str, list[dict]]:
        """Return canonical Hardcore beaten and mastery awards from completion progress."""
        awards = {"beaten": [], "masteries": []}
        offset = 0
        count = 500

        while True:
            data = await self.user_completion_progress(username, count=count, offset=offset)
            results = data.get("Results") or data.get("results") or []
            if not isinstance(results, list):
                raise ValueError("Unexpected RetroAchievements completion progress response")

            for game in results:
                if not isinstance(game, dict):
                    continue
                award_kind = game.get("HighestAwardKind") or game.get("highestAwardKind")
                if award_kind not in {"beaten-hardcore", "mastered"}:
                    continue

                game_id = game.get("GameID") or game.get("gameId")
                awarded_at = game.get("HighestAwardDate") or game.get("highestAwardDate")
                if not game_id or not awarded_at:
                    continue

                image = game.get("ImageIcon") or game.get("imageIcon")
                if image:
                    image = urljoin(RA_BASE_URL, image)

                event_type = "beaten" if award_kind == "beaten-hardcore" else "mastery"
                awards["beaten" if event_type == "beaten" else "masteries"].append(
                    {
                        "username": username,
                        "game_id": int(game_id),
                        "game_title": game.get("Title") or game.get("title") or "Unknown Game",
                        "game_image": image,
                        "hardcore_achievements": int(game.get("NumAwardedHardcore") or game.get("numAwardedHardcore") or 0),
                        "total_achievements": int(game.get("MaxPossible") or game.get("maxPossible") or 0),
                        "awarded_at": awarded_at,
                        "dedupe_key": f"{username}:{event_type}:{int(game_id)}:{awarded_at}",
                    }
                )

            total = int(data.get("Total") or data.get("total") or len(results))
            offset += len(results)
            if not fetch_all or not results or offset >= total:
                break

        return awards

    async def hardcore_masteries(self, username: str, fetch_all: bool = False) -> list[dict]:
        """Return normalized Hardcore mastery awards from completion progress data."""
        return (await self.hardcore_game_awards(username, fetch_all))["masteries"]

    async def hardcore_beaten_games(self, username: str, fetch_all: bool = False) -> list[dict]:
        """Return canonical Hardcore beaten-game awards from completion progress data."""
        return (await self.hardcore_game_awards(username, fetch_all))["beaten"]

    async def game_award_event_details(self, username: str, award: dict) -> dict:
        """Enrich a canonical Hardcore game award with art and earned point totals."""
        game_progress = await self.game_info_and_user_progress(username, award["game_id"])
        achievements = game_progress.get("Achievements") or game_progress.get("achievements") or {}
        if not isinstance(achievements, dict):
            achievements = {}

        hardcore_points = 0
        total_points = 0
        for achievement in achievements.values():
            if isinstance(achievement, dict):
                points = int(achievement.get("Points") or achievement.get("points") or 0)
                total_points += points
                if achievement.get("DateEarnedHardcore") or achievement.get("dateEarnedHardcore"):
                    hardcore_points += points

        total_points = total_points or int(game_progress.get("PossibleScore") or game_progress.get("possibleScore") or 0)
        total_achievements = int(
            game_progress.get("NumAchievements")
            or game_progress.get("numAchievements")
            or award.get("total_achievements", 0)
        )
        hardcore_achievements = int(
            game_progress.get("NumAwardedToUserHardcore")
            or game_progress.get("numAwardedToUserHardcore")
            or award.get("hardcore_achievements", 0)
        )

        image = (
            game_progress.get("ImageIngame")
            or game_progress.get("imageIngame")
            or game_progress.get("ImageTitle")
            or game_progress.get("imageTitle")
            or game_progress.get("ImageBoxArt")
            or game_progress.get("imageBoxArt")
            or game_progress.get("ImageIcon")
            or game_progress.get("imageIcon")
            or award.get("game_image")
        )
        if image:
            image = urljoin(RA_BASE_URL, image)

        return {
            **award,
            "game_title": game_progress.get("Title") or game_progress.get("title") or award["game_title"],
            "game_image": image,
            "hardcore_achievements": hardcore_achievements,
            "total_achievements": total_achievements,
            "hardcore_points": hardcore_points,
            "total_points": total_points,
        }

    async def mastery_event_details(self, username: str, mastery: dict) -> dict:
        """Enrich a Hardcore mastery event with game art and point totals."""
        return await self.game_award_event_details(username, mastery)

    async def achievements_earned_between(
        self,
        username: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """Return achievements earned by a user between two datetimes."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        data = await self._get_json(
            "API_GetAchievementsEarnedBetween.php",
            {
                "u": target,
                "f": int(start_time.timestamp()),
                "t": int(end_time.timestamp()),
            },
        )

        if not isinstance(data, list):
            raise ValueError("Unexpected RetroAchievements API response")

        return data

    async def hardcore_points_earned_between(
        self,
        username: str,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Sum official point values for Hardcore achievements earned in a range."""
        weekly_points = await self.points_earned_between(username, start_time, end_time)
        return weekly_points["hardcore_points"]

    async def points_earned_between(
        self,
        username: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict:
        """Sum Hardcore and RetroPoints values for Hardcore achievements in a range."""
        achievements = await self.achievements_earned_between(username, start_time, end_time)
        hardcore_points = 0
        retro_points = 0
        achievements_earned = 0

        for achievement in achievements:
            hardcore_mode = achievement.get("HardcoreMode", achievement.get("hardcoreMode"))
            if hardcore_mode in (1, "1", True):
                hardcore_points += int(achievement.get("Points") or achievement.get("points") or 0)
                retro_points += int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0)
                achievements_earned += 1

        return {
            "hardcore_points": hardcore_points,
            "retro_points": retro_points,
            "achievements_earned": achievements_earned,
        }

    async def recent_hardcore_achievements(
        self,
        username: str,
        recent_minutes: int = 1440,
        profile: dict | None = None,
    ) -> list[dict]:
        """Return normalized recent Hardcore achievement unlocks for a user."""
        if not self.api_key:
            raise ValueError("RA API key not set")

        target = username.strip()
        if not target:
            raise ValueError("RetroAchievements username is required")

        profile = profile or await self.lookup_user(target)
        data = await self._get_json(
            "API_GetUserRecentAchievements.php",
            {
                "u": target,
                "m": recent_minutes,
            },
        )

        if not isinstance(data, list):
            raise ValueError("Unexpected RetroAchievements API response")

        achievements = []
        for achievement in data:
            if not isinstance(achievement, dict):
                continue

            hardcore_mode = achievement.get("HardcoreMode", achievement.get("hardcoreMode"))
            if hardcore_mode not in (1, "1", True):
                continue

            achievement_id = achievement.get("AchievementID") or achievement.get("achievementId")
            unlock_time = self._parse_api_datetime(achievement.get("Date") or achievement.get("date"))
            if not achievement_id or not unlock_time:
                continue

            badge_image = achievement.get("BadgeURL") or achievement.get("badgeUrl")
            if badge_image:
                badge_image = urljoin(RA_BASE_URL, badge_image)

            achievements.append(
                {
                    "username": profile["username"],
                    "avatar": profile.get("avatar"),
                    "achievement_id": int(achievement_id),
                    "achievement_title": achievement.get("Title") or achievement.get("title") or "Unknown Achievement",
                    "achievement_description": achievement.get("Description") or achievement.get("description") or "",
                    "achievement_badge": badge_image,
                    "game_title": achievement.get("GameTitle") or achievement.get("gameTitle") or "Unknown Game",
                    "game_id": int(achievement.get("GameID") or achievement.get("gameId") or 0),
                    "points": int(achievement.get("Points") or achievement.get("points") or 0),
                    "retro_points": int(achievement.get("TrueRatio") or achievement.get("trueRatio") or 0),
                    "unlock_time": unlock_time,
                    "unlock_time_iso": unlock_time.isoformat(),
                    "unlock_time_display": unlock_time.strftime("%b %-d, %-I:%M %p"),
                    "hardcore": True,
                    "dedupe_key": f"{profile['username']}:{achievement_id}:{unlock_time.isoformat()}",
                }
            )

        return achievements
