"""Windows notification behavior without requiring a Windows desktop."""

import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
import sys

from runtime import RuntimeMode
from services.windows_notifications import (
    NIIF_NOSOUND,
    WindowsNotificationPlatform,
    WindowsNotificationService,
    send_silent_tray_notification,
    set_notification_icon,
)
from tests.test_macos_notifications import FakePlatform, MemorySettings, environment


class WindowsNotificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_notification_sets_windows_no_sound_flag(self):
        icon = Mock()
        utility = ModuleType("pystray._util")
        utility.win32 = SimpleNamespace(NIM_MODIFY=1, NIF_INFO=16)
        with patch.dict(sys.modules, {"pystray": ModuleType("pystray"), "pystray._util": utility}):
            send_silent_tray_notification(icon, "Body", "Title")
        icon._message.assert_called_once_with(
            1, 16, szInfo="Body", szInfoTitle="Title", dwInfoFlags=NIIF_NOSOUND
        )

    async def test_platform_keeps_muted_notification_visible(self):
        icon = Mock()
        set_notification_icon(icon)
        try:
            with patch("services.windows_notifications.send_silent_tray_notification") as silent:
                await WindowsNotificationPlatform().send(
                    "id", "Title", "Body", {"mute_sound": True}
                )
            silent.assert_called_once_with(icon, "Body", "Title")
            icon.notify.assert_not_called()
            await WindowsNotificationPlatform().send("id2", "Title", "Body")
            icon.notify.assert_called_once_with("Body", "Title")
        finally:
            set_notification_icon(None)

    async def test_delivers_once_and_uses_windows_preferences(self):
        settings = MemorySettings()
        platform = FakePlatform("unused", status="authorized")
        service = WindowsNotificationService(
            environment(RuntimeMode.WINDOWS_PACKAGED),
            settings,
            platform_factory=lambda _url: platform,
        )
        service.save_preferences(True, {
            "achievement": True, "beaten": False, "mastery": True, "update": True,
        })

        event = {"type": "achievement", "dedupe_key": "nick:123", "username": "Nick"}
        self.assertTrue(await service.notify_event(event))
        self.assertFalse(await service.notify_event(event))
        self.assertFalse(await service.notify_event({**event, "type": "beaten", "dedupe_key": "nick:456"}))
        self.assertEqual(len(platform.sent), 1)
        self.assertEqual(settings.get_setting("windows_notifications_beaten"), "0")
        self.assertIsNone(settings.get_setting("macos_notifications_beaten"))

    async def test_update_version_is_recorded_under_windows_settings(self):
        settings = MemorySettings()
        platform = FakePlatform("unused", status="authorized")
        service = WindowsNotificationService(
            environment(RuntimeMode.WINDOWS_PACKAGED), settings,
            platform_factory=lambda _url: platform,
        )
        state = {"update_available": True, "latest_version": "v1.2.3"}

        self.assertTrue(await service.notify_update(state))
        self.assertFalse(await service.notify_update(state))
        self.assertEqual(settings.get_setting("windows_notifications_last_update_version"), "v1.2.3")
