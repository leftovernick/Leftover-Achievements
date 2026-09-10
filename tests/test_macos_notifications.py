import unittest
from pathlib import Path

from runtime import RuntimeEnvironment, RuntimeMode
from services.macos_notifications import MacOSNotificationService


class MemorySettings:
    def __init__(self):
        self.values = {"audio_enabled": "0"}
        self.deliveries = set()

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value

    def native_notification_delivered(self, dedupe_key):
        return dedupe_key in self.deliveries

    def mark_native_notification_delivered(self, dedupe_key):
        self.deliveries.add(dedupe_key)


class FakePlatform:
    def __init__(self, dashboard_url, status="authorized"):
        self.dashboard_url = dashboard_url
        self.status = status
        self.authorization_requests = 0
        self.sent = []

    async def authorization_status(self):
        return self.status

    async def request_authorization(self):
        self.authorization_requests += 1
        self.status = "authorized"
        return True

    async def send(self, identifier, title, body, user_info=None):
        self.sent.append((identifier, title, body, user_info))


def environment(mode=RuntimeMode.MACOS_PACKAGED):
    root = Path("/tmp/leftover-notification-test")
    return RuntimeEnvironment(
        mode=mode,
        resource_root=root,
        data_dir=root,
        logs_dir=root / "logs",
        mutable_audio_dir=root / "audio",
        installed_version="v0.1.0",
        architecture="arm64",
        port=8123,
    )


class MacOSNotificationTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, status="authorized", settings=None):
        settings = settings or MemorySettings()
        platform = FakePlatform("unused", status=status)
        service = MacOSNotificationService(
            environment(), settings, platform_factory=lambda url: self._configure(platform, url)
        )
        return service, settings, platform

    @staticmethod
    def _configure(platform, url):
        platform.dashboard_url = url
        return platform

    async def test_requests_permission_only_while_not_determined(self):
        service, _settings, platform = self.make_service("not_determined")

        status = await service.request_authorization()
        await service.request_authorization()

        self.assertEqual(platform.authorization_requests, 1)
        self.assertTrue(status["can_deliver"])

    async def test_denied_permission_is_non_fatal_and_does_not_send(self):
        service, _settings, platform = self.make_service("denied")

        delivered = await service.notify_event(
            {"type": "beaten", "dedupe_key": "nick:1", "username": "Nick", "game_title": "Pokémon Rumble"}
        )

        self.assertFalse(delivered)
        self.assertEqual(platform.sent, [])

    async def test_settings_failure_is_non_fatal(self):
        service, settings, platform = self.make_service()

        def fail_setting(_key, _default=None):
            raise RuntimeError("database unavailable")

        settings.get_setting = fail_setting
        delivered = await service.notify_event(
            {"type": "beaten", "dedupe_key": "nick:1"}
        )

        self.assertFalse(delivered)
        self.assertEqual(platform.sent, [])

    async def test_achievement_uses_existing_identity_and_sends_once(self):
        service, settings, platform = self.make_service()
        event = {
            "type": "achievement",
            "dedupe_key": "Nick:123:2026-09-09T12:00:00Z",
            "username": "Nick",
            "achievement_title": "Achievement Name",
            "game_title": "Pokémon Rumble",
            "points": 25,
            "retro_points": 9,
        }

        self.assertTrue(await service.notify_event(event))
        self.assertFalse(await service.notify_event(event))

        self.assertEqual(len(platform.sent), 1)
        self.assertEqual(platform.sent[0][1], "Achievement Unlocked")
        self.assertEqual(
            platform.sent[0][2],
            "Nick earned “Achievement Name”\nPokémon Rumble • 25 points • 9 RetroPoints",
        )
        self.assertIn("event:achievement:", next(iter(settings.deliveries)))

    async def test_beaten_and_mastery_categories_can_be_disabled_independently(self):
        service, settings, platform = self.make_service()
        service.save_preferences(
            True,
            {"achievement": True, "beaten": False, "mastery": True, "update": True},
        )

        beaten = await service.notify_event(
            {"type": "beaten", "dedupe_key": "beat:1", "username": "Nick", "game_title": "Game"}
        )
        mastery = await service.notify_event(
            {"type": "mastery", "dedupe_key": "master:1", "username": "Nick", "game_title": "Game"}
        )

        self.assertFalse(beaten)
        self.assertTrue(mastery)
        self.assertEqual(platform.sent[0][1:], ("Game Mastered", "Nick mastered Game", None))
        self.assertEqual(settings.get_setting("audio_enabled"), "0")

    async def test_update_notification_is_persisted_once_per_version(self):
        service, settings, platform = self.make_service()
        state = {
            "update_available": True,
            "latest_version": "v0.1.3",
            "latest_release_tag": "v0.1.3",
        }

        self.assertTrue(await service.notify_update(state))
        self.assertFalse(await service.notify_update(state))
        replacement = MacOSNotificationService(
            environment(), settings, platform_factory=lambda _url: platform
        )
        self.assertFalse(await replacement.notify_update(state))
        next_state = {
            **state,
            "latest_version": "v0.1.4",
            "latest_release_tag": "v0.1.4",
        }
        self.assertTrue(await replacement.notify_update(next_state))

        self.assertEqual(len(platform.sent), 2)
        self.assertEqual(settings.get_setting("macos_notifications_last_update_version"), "v0.1.4")

    async def test_non_macos_runtimes_never_load_native_framework_adapter(self):
        for mode in (
            RuntimeMode.WINDOWS_PACKAGED,
            RuntimeMode.RASPBERRY_PI,
            RuntimeMode.DEVELOPMENT,
        ):
            with self.subTest(mode=mode):
                loaded = False

                def factory(_url):
                    nonlocal loaded
                    loaded = True
                    return FakePlatform("unused")

                service = MacOSNotificationService(
                    environment(mode), MemorySettings(), factory
                )
                status = await service.status()
                delivered = await service.notify_event(
                    {"type": "mastery", "dedupe_key": "master:1"}
                )

                self.assertFalse(loaded)
                self.assertFalse(delivered)
                self.assertEqual(status["authorization"], "unsupported")


if __name__ == "__main__":
    unittest.main()
