import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp

import app as application
from services.retroachievements import RetroAchievements


PROJECT_ROOT = application.runtime.resource_root


class LiveActivityRefreshTests(unittest.IsolatedAsyncioTestCase):
    def test_recent_active_snapshot_remains_visible_during_revalidation(self):
        cached = {
            "active": 1,
            "payload": {"game_title": "Test Game"},
            "refreshed_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        }
        self.assertEqual(
            application.visible_current_activity(cached), cached["payload"]
        )

    def test_very_old_active_snapshot_is_hidden(self):
        cached = {
            "active": 1,
            "payload": {"game_title": "Old Game"},
            "refreshed_at": (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat(),
        }
        self.assertIsNone(application.visible_current_activity(cached))

    async def test_current_activity_change_is_saved_and_broadcast(self):
        current = {"username": "Player", "game_title": "New Game"}
        with (
            patch.object(
                application.db,
                "get_currently_playing_cache",
                return_value={"player": {"active": 0, "payload": None}},
            ),
            patch.object(application.db, "save_currently_playing") as save,
            patch.object(
                application.ra_client,
                "currently_playing",
                new=AsyncMock(return_value=current),
            ),
            patch.object(application, "broadcast_display_event") as broadcast,
        ):
            changed = await application.refresh_current_activity_for_user(
                {"ra_username": "Player"}
            )

        self.assertTrue(changed)
        save.assert_called_once_with("Player", current)
        broadcast.assert_called_once_with(
            {"type": "display-data-refresh", "reason": "current-activity"}
        )

    async def test_current_activity_api_failure_preserves_cached_state(self):
        with (
            patch.object(
                application.db,
                "get_currently_playing_cache",
                return_value={"player": {"active": 1, "payload": {"game_title": "Game"}}},
            ),
            patch.object(application.db, "save_currently_playing") as save,
            patch.object(
                application.ra_client,
                "currently_playing",
                new=AsyncMock(side_effect=aiohttp.ClientError()),
            ),
            patch.object(application, "broadcast_display_event") as broadcast,
            self.assertLogs("app", level="WARNING") as captured,
        ):
            changed = await application.refresh_current_activity_for_user(
                {"ra_username": "Player"}
            )

        self.assertFalse(changed)
        self.assertIn("Could not refresh current activity for Player", captured.output[0])
        save.assert_not_called()
        broadcast.assert_not_called()

    def test_clients_refresh_activity_in_place(self):
        display_javascript = (PROJECT_ROOT / "static/js/display.js").read_text(
            encoding="utf-8"
        )
        dashboard_javascript = (PROJECT_ROOT / "static/js/app.js").read_text(
            encoding="utf-8"
        )
        dashboard_template = (PROJECT_ROOT / "templates/dashboard.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("requestDisplayDataRefresh();", display_javascript)
        self.assertIn("'display-data-refresh'", display_javascript)
        self.assertIn("DISPLAY_DATA_REFRESH_MS = 30 * 1000", display_javascript)
        self.assertIn(
            "DISPLAY_MAINTENANCE_RELOAD_MS = 15 * 60 * 1000",
            display_javascript,
        )
        self.assertIn("REFRESH_INTERVAL_MS = 10 * 1000", dashboard_javascript)
        self.assertEqual(
            dashboard_template.count("data-dashboard-refresh-section="), 4
        )
        self.assertIn("Played This Week", dashboard_template)
        self.assertIn('class="current-console">{{ player.console }}', dashboard_template)
        self.assertIn('class="activity-console">{{ activity.console }}', dashboard_template)
        self.assertIn("Most Played Consoles", dashboard_template)
        self.assertIn("Most Played Genres", dashboard_template)
        self.assertIn("Most Shared Games", dashboard_template)
        self.assertIn("<span>All time</span>", dashboard_template)
        self.assertNotIn("weekly_shared_games", dashboard_template)
        self.assertLess(dashboard_template.index("Recent Activity"), dashboard_template.index("Played This Week"))
        self.assertIn("<span>Since {{ week_start_display }}</span>", dashboard_template)
        self.assertIn("game.game_image", dashboard_template)
        self.assertIn('data-category-scope="all-time"', dashboard_template)
        self.assertIn("applyCategoryScope();", dashboard_javascript)

    async def test_weekly_points_include_every_game_with_a_hardcore_unlock(self):
        client = RetroAchievements("key")
        client.achievements_earned_between = AsyncMock(return_value=[
            {"HardcoreMode": 1, "GameID": 10, "GameTitle": "First Game", "GameIcon": "/Images/first.png", "Points": 5, "TrueRatio": 8},
            {"HardcoreMode": 1, "GameID": 10, "GameTitle": "First Game", "Points": 10, "TrueRatio": 20},
            {"HardcoreMode": 1, "GameID": 20, "GameTitle": "Unfinished Game", "Points": 2, "TrueRatio": 3},
            {"HardcoreMode": 0, "GameID": 30, "GameTitle": "Softcore Game", "Points": 50, "TrueRatio": 90},
        ])
        result = await client.points_earned_between(
            "Player", datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 8, tzinfo=timezone.utc)
        )
        self.assertEqual(result["hardcore_points"], 17)
        self.assertEqual(result["achievements_earned"], 3)
        self.assertEqual(result["played_games"], [
            {"game_id": 10, "game_title": "First Game", "game_image": "https://retroachievements.org/Images/first.png", "console": None, "achievements_earned": 2,
             "hardcore_points": 15, "retro_points": 28},
            {"game_id": 20, "game_title": "Unfinished Game", "game_image": None, "console": None, "achievements_earned": 1,
             "hardcore_points": 2, "retro_points": 3},
        ])

    async def test_dashboard_groups_weekly_games_under_their_player(self):
        weekly_game = {
            "game_id": 20, "game_title": "Unfinished Game", "achievements_earned": 1,
            "hardcore_points": 2, "retro_points": 3,
        }
        with (
            patch.object(application.db, "get_tracked_users", return_value=[
                {"id": 1, "ra_username": "Player", "ra_ulid": "ABC"},
            ]),
            patch.object(application.db, "get_weekly_rankings", return_value={
                "player": {"hardcore_points": 2, "retro_points": 3,
                           "played_games": [weekly_game], "refreshed_at": datetime.now(timezone.utc).isoformat()},
            }),
            patch.object(application.db, "get_user_profiles", return_value={
                "player": {"canonical_username": "Player", "ra_ulid": "ABC", "avatar": None,
                           "hardcore_points": 100, "retro_points": 200},
            }),
            patch.object(application.db, "get_currently_playing_cache", return_value={}),
            patch.object(application.db, "get_recent_activity", return_value=[]),
            patch.object(application.db, "get_user_game_libraries", return_value={}),
            patch.object(application.db, "get_game_metadata", return_value={
                20: {"game_id": 20, "console": "SNES", "genre": "Platformer, Action"},
            }),
            patch.object(application, "schedule_user_snapshot_refresh_if_needed"),
            patch.object(application, "schedule_weekly_refresh_if_needed"),
            patch.object(application, "schedule_game_library_refresh_if_needed"),
            patch.object(application, "schedule_recent_activity_refresh_if_needed"),
        ):
            context = await application.dashboard_context()

        self.assertEqual(context["weekly_game_count"], 1)
        self.assertEqual(context["weekly_played_users"][0]["username"], "Player")
        self.assertEqual(context["weekly_played_users"][0]["weekly_games"][0]["game_title"], "Unfinished Game")
        self.assertEqual(context["weekly_consoles"], [{"name": "SNES", "player_count": 1, "game_count": 1}])
        self.assertEqual([row["name"] for row in context["weekly_genres"]], ["Action", "Platformer"])

    async def test_all_time_game_library_keeps_zero_achievement_games(self):
        client = RetroAchievements("key")
        client.user_completion_progress = AsyncMock(return_value={
            "Total": 2,
            "Results": [
                {"GameID": 1, "Title": "Played Only", "ImageIcon": "/Images/one.png",
                 "ConsoleName": "NES", "MaxPossible": 10, "NumAwardedHardcore": 0},
                {"GameID": 2, "Title": "With Progress", "ConsoleName": "SNES",
                 "MaxPossible": 10, "NumAwardedHardcore": 3},
            ],
        })
        games = await client.user_game_library("Player")
        self.assertEqual([game["game_id"] for game in games], [1, 2])
        self.assertEqual(games[0]["game_image"], "https://retroachievements.org/Images/one.png")
        self.assertEqual(games[1]["completion_percentage"], 30)

    async def test_latest_hardcore_achievements_are_sorted_and_limited(self):
        client = RetroAchievements("key")
        client.user_summary = AsyncMock(return_value={
            "RecentlyPlayed": [
                {"GameID": 10, "Title": "Game One", "ConsoleName": "NES"},
                {"GameID": 20, "Title": "Game Two", "ConsoleName": "SNES"},
            ],
            "RecentAchievements": {
                "10": {
                    "1": {"ID": 1, "GameID": 10, "Title": "Older", "HardcoreAchieved": True,
                          "DateAwarded": "2026-09-20 12:00:00", "Points": 5, "TrueRatio": 9},
                    "2": {"ID": 2, "GameID": 10, "Title": "Softcore", "HardcoreAchieved": False,
                          "DateAwarded": "2026-09-22 13:00:00", "Points": 10},
                },
                "20": {
                    "3": {"ID": 3, "GameID": 20, "Title": "Newest", "HardcoreAchieved": True,
                          "DateAwarded": "2026-09-21 12:00:00", "Points": 10, "TrueRatio": 20,
                          "BadgeName": "12345"},
                },
            },
        })

        achievements = await client.latest_hardcore_achievements("ABC", limit=5)

        self.assertEqual([item["achievement_title"] for item in achievements], ["Newest", "Older"])
        self.assertEqual(achievements[0]["console"], "SNES")
        self.assertEqual(achievements[0]["achievement_badge"], "https://retroachievements.org/Badge/12345.png")
        client.user_summary.assert_awaited_once_with(
            "ABC", recent_games_count=10, recent_achievements_count=5,
        )

    async def test_award_details_prefer_square_game_icon(self):
        client = RetroAchievements("key")
        client.game_info_and_user_progress = AsyncMock(return_value={
            "Title": "Example Game",
            "ImageIcon": "/Images/icon.png",
            "ImageTitle": "/Images/title.png",
            "ImageIngame": "/Images/ingame.png",
            "Achievements": {},
        })

        details = await client.game_award_event_details("Player", {
            "game_id": 10, "game_title": "Example Game", "game_image": None,
        })

        self.assertEqual(details["game_image"], "https://retroachievements.org/Images/icon.png")

    def test_recent_activity_refreshes_when_cached_console_is_missing(self):
        activities = [{"console": "NES"} for _ in range(application.RECENT_ACTIVITY_LIMIT)]
        activities[0]["console"] = None

        with (
            patch.object(application, "recent_activity_refresh_task", None),
            patch.object(application, "create_logged_task") as create_task,
        ):
            application.schedule_recent_activity_refresh_if_needed(
                [{"ra_username": "Player"}], activities,
            )

        create_task.assert_called_once()
        create_task.call_args.args[0].close()

    def test_old_game_library_cache_is_refreshed_for_completion_percentages(self):
        users = [{"ra_username": "Player"}]
        libraries = {
            "player": {
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "games": [{"game_id": 1, "game_title": "Old cached game"}],
            }
        }

        with patch.object(application, "create_logged_task") as create_task:
            application.schedule_game_library_refresh_if_needed(users, libraries)

        create_task.assert_called_once()
        create_task.call_args.args[0].close()

    def test_console_and_genre_rankings_sort_by_games_before_players(self):
        users = [
            {"username": "One", "ulid": "1", "weekly_games": [
                {"game_id": 1, "console": "Many Players"},
                {"game_id": 2, "console": "Many Games"},
                {"game_id": 3, "console": "Many Games"},
            ]},
            {"username": "Two", "ulid": "2", "weekly_games": [
                {"game_id": 1, "console": "Many Players"},
            ]},
        ]
        metadata = {
            1: {"genre": "Popular"},
            2: {"genre": "Varied"},
            3: {"genre": "Varied"},
        }
        consoles, genres = application.weekly_game_category_stats(users, metadata)
        self.assertEqual([row["name"] for row in consoles], ["Many Games", "Many Players"])
        self.assertEqual([row["name"] for row in genres], ["Varied", "Popular"])

    def test_console_and_genre_rankings_are_limited_to_five(self):
        games = [
            {"game_id": game_id, "console": f"Console {game_id}"}
            for game_id in range(1, 8)
        ]
        metadata = {
            game_id: {"genre": f"Genre {game_id}"}
            for game_id in range(1, 8)
        }

        consoles, genres = application.weekly_game_category_stats(
            [{"username": "Player", "weekly_games": games}], metadata,
        )

        self.assertEqual(len(consoles), 5)
        self.assertEqual(len(genres), 5)

    def test_shared_games_rank_by_players_then_average_completion(self):
        users = [
            {"username": "A", "ulid": "a", "weekly_games": [
                {"game_id": 1, "game_title": "Balanced", "completion_percentage": 50},
                {"game_id": 2, "game_title": "Uneven", "completion_percentage": 90},
                {"game_id": 3, "game_title": "Solo", "completion_percentage": 100},
            ]},
            {"username": "B", "ulid": "b", "weekly_games": [
                {"game_id": 1, "game_title": "Balanced", "completion_percentage": 50},
                {"game_id": 2, "game_title": "Uneven", "completion_percentage": 1},
            ]},
        ]
        shared = application.shared_game_stats(users)
        self.assertEqual([game["game_title"] for game in shared], ["Balanced", "Uneven"])
        self.assertEqual(shared[0]["average_completion"], 50)


if __name__ == "__main__":
    unittest.main()
