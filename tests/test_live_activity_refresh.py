import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp

import app as application


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
        ):
            changed = await application.refresh_current_activity_for_user(
                {"ra_username": "Player"}
            )

        self.assertFalse(changed)
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
        self.assertIn("REFRESH_INTERVAL_MS = 10 * 1000", dashboard_javascript)
        self.assertEqual(
            dashboard_template.count("data-dashboard-refresh-section="), 2
        )


if __name__ == "__main__":
    unittest.main()
