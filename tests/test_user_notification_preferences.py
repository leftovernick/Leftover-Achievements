import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import app as application
from database import database as db


class UserNotificationPreferenceDatabaseTests(unittest.TestCase):
    def test_preferences_are_case_insensitive_and_removed_with_user(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.db"
            with patch.object(db, "DB_PATH", str(path)), patch.object(db, "DB_DIR", directory):
                db.init_db()
                db.add_tracked_user("PlayerOne", None)
                self.assertTrue(db.set_user_notification_preferences(
                    "playerone", {"mute_sound": True, "mute_mastery": True}
                ))
                db.init_db()
                preferences = db.get_user_notification_preferences("PLAYERONE")
                self.assertTrue(preferences["mute_sound"])
                self.assertTrue(preferences["mute_mastery"])
                self.assertFalse(preferences["mute_all"])
                self.assertFalse(db.set_user_notification_preferences("unknown", {"mute_all": True}))
                db.remove_tracked_user(db.get_tracked_users()[0]["id"])
                self.assertFalse(any(db.get_user_notification_preferences("PlayerOne").values()))


class UserNotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def test_old_running_backend_still_shows_tracked_players(self):
        request = Request({"type": "http", "method": "GET", "path": "/users", "headers": []})
        response = application.templates.TemplateResponse(
            request=request,
            name="users.html",
            context={"users": [{"ra_username": "Player", "display_name": "Player"}], "message": None},
        )
        html = response.body.decode()
        self.assertIn("1 users", html)
        self.assertIn("Restart LeftoverAchievements", html)
        self.assertIn("Player</strong>", html)
        self.assertNotIn("No tracked players yet.", html)

    async def test_saving_returns_to_selected_player_on_users_page(self):
        with patch.object(application.db, "set_user_notification_preferences", return_value=True) as save:
            response = await application.update_user_notification_settings(
                ra_username="Second", mute_sound="1", mute_achievement=None,
                mute_all=None, mute_beaten=None, mute_mastery=None,
            )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/users?", response.headers["location"])
        self.assertIn("notification_user=Second", response.headers["location"])
        self.assertEqual(save.call_args.args[1]["mute_sound"], True)

    async def test_settings_selects_requested_player(self):
        request = Request({"type": "http", "method": "GET", "path": "/users", "headers": []})
        with (
            patch.object(application.db, "get_tracked_users", return_value=[
                {"id": 1, "ra_username": "First", "ra_ulid": "FIRSTULID"},
                {"id": 2, "ra_username": "Second", "ra_ulid": "SECONDULID"},
            ]),
            patch.object(application.db, "get_user_profiles", return_value={}),
            patch.object(application.db, "get_user_notification_preferences", return_value={
                "mute_all": False, "mute_sound": True, "mute_achievement": False,
                "mute_beaten": False, "mute_mastery": False,
            }) as preferences,
        ):
            response = await application.users(request, notification_user="Second")
        html = response.body.decode()
        self.assertIn('value="Second" selected', html)
        self.assertIn('onchange="this.form.requestSubmit()"', html)
        self.assertNotIn(">Select Player</button>", html)
        self.assertIn('href="/users/SECONDULID">View Profile</a>', html)
        self.assertNotIn('href="/users/FIRSTULID">View Profile</a>', html)
        self.assertIn('name="mute_sound" value="1" checked', html)
        self.assertIn("<legend>Alert audio</legend>", html)
        self.assertIn("<legend>Interrupts</legend>", html)
        self.assertIn('action="/users/notifications"', html)
        self.assertNotIn("<th>ULID</th>", html)
        preferences.assert_called_once_with("Second")

    async def test_category_mute_suppresses_both_destinations_but_refreshes_data(self):
        with (
            patch.object(application.db, "get_user_notification_preferences", return_value={"mute_achievement": True}),
            patch.object(application.macos_notification_service, "notify_event", new=AsyncMock()) as native,
            patch.object(application.windows_notification_service, "notify_event", new=AsyncMock()) as windows_native,
            patch.object(application, "broadcast_display_event") as display,
        ):
            await application.publish_display_event(
                {"type": "achievement", "username": "ShownName", "dedupe_key": "one"},
                ra_username="TrackedName",
            )
        native.assert_not_awaited()
        windows_native.assert_not_awaited()
        display.assert_called_once_with({"type": "display-data-refresh", "reason": "muted-event"})

    async def test_sound_mute_keeps_visual_and_native_alert(self):
        with (
            patch.object(application.db, "get_user_notification_preferences", return_value={"mute_sound": True}) as lookup,
            patch.object(application.macos_notification_service, "notify_event", new=AsyncMock()) as native,
            patch.object(application.windows_notification_service, "notify_event", new=AsyncMock()),
            patch.object(application, "broadcast_display_event") as display,
        ):
            await application.publish_display_event(
                {"type": "beaten", "username": "ShownName", "dedupe_key": "two"},
                ra_username="TrackedName",
            )
        lookup.assert_called_once_with("TrackedName")
        self.assertTrue(native.await_args.args[0]["mute_sound"])
        self.assertTrue(display.call_args.args[0]["mute_sound"])

    async def test_mute_all_suppresses_catchup_summary(self):
        with (
            patch.object(application.db, "get_user_notification_preferences", return_value={"mute_all": True}),
            patch.object(application, "broadcast_display_event") as display,
        ):
            await application.publish_display_event({"type": "catchup", "username": "Player"})
        display.assert_called_once_with({"type": "display-data-refresh", "reason": "muted-event"})

    async def test_macos_native_notification_receives_sound_preference(self):
        from services.macos_notifications import MacOSNotificationService
        from tests.test_macos_notifications import FakePlatform, MemorySettings, environment

        platform = FakePlatform("unused")
        service = MacOSNotificationService(
            environment(), MemorySettings(), platform_factory=lambda _url: platform
        )
        delivered = await service.notify_event({
            "type": "mastery", "dedupe_key": "sound:1", "username": "Player",
            "game_title": "Game", "mute_sound": True,
        })
        self.assertTrue(delivered)
        self.assertEqual(platform.sent[0][3], {"mute_sound": True})
