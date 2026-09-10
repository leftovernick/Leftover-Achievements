"""Optional native notifications for the packaged macOS application.

The Apple framework imports are deliberately lazy. Importing this module is safe on
Windows, Raspberry Pi, and development systems without PyObjC installed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from typing import Any, Callable

from runtime import RuntimeMode


logger = logging.getLogger(__name__)

NOTIFICATION_CATEGORIES = ("achievement", "beaten", "mastery", "update")
NOTIFICATION_LABELS = {
    "achievement": "Achievement Unlocked",
    "beaten": "Game Beaten",
    "mastery": "Game Mastered",
    "update": "Update Available",
}
AUTHORIZED_STATUSES = {"authorized", "provisional", "ephemeral"}


class UserNotificationsPlatform:
    """Thin async adapter around UserNotifications.framework."""

    def __init__(self, dashboard_url: str):
        from AppKit import NSWorkspace
        from Foundation import NSObject, NSURL
        from UserNotifications import (
            UNAuthorizationOptionAlert,
            UNAuthorizationOptionSound,
            UNAuthorizationStatusAuthorized,
            UNAuthorizationStatusDenied,
            UNAuthorizationStatusEphemeral,
            UNAuthorizationStatusNotDetermined,
            UNAuthorizationStatusProvisional,
            UNMutableNotificationContent,
            UNNotificationPresentationOptionAlert,
            UNNotificationPresentationOptionSound,
            UNNotificationRequest,
            UNNotificationSound,
            UNUserNotificationCenter,
        )

        self._authorization_options = UNAuthorizationOptionAlert | UNAuthorizationOptionSound
        self._dashboard_url = dashboard_url
        self._content_class = UNMutableNotificationContent
        self._request_class = UNNotificationRequest
        self._default_sound = UNNotificationSound.defaultSound()
        self._center = UNUserNotificationCenter.currentNotificationCenter()
        self._status_names = {
            UNAuthorizationStatusNotDetermined: "not_determined",
            UNAuthorizationStatusDenied: "denied",
            UNAuthorizationStatusAuthorized: "authorized",
            UNAuthorizationStatusProvisional: "provisional",
            UNAuthorizationStatusEphemeral: "ephemeral",
        }

        dashboard = dashboard_url
        presentation_options = UNNotificationPresentationOptionAlert | UNNotificationPresentationOptionSound

        class NotificationCenterDelegate(NSObject):
            def userNotificationCenter_willPresentNotification_withCompletionHandler_(
                self, _center, _notification, completion_handler
            ):
                completion_handler(presentation_options)

            def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
                self, _center, _response, completion_handler
            ):
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "openDashboard:", None, False
                )
                completion_handler()

            def openDashboard_(self, _unused):
                NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(dashboard))

        # UNUserNotificationCenter holds its delegate weakly, so retain it here.
        self._delegate = NotificationCenterDelegate.alloc().init()
        self._center.setDelegate_(self._delegate)

    async def authorization_status(self) -> str:
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def completed(settings):
            status = (
                self._status_names.get(settings.authorizationStatus(), "other")
                if settings is not None
                else "unavailable"
            )
            loop.call_soon_threadsafe(self._resolve_future, future, status, None)

        self._center.getNotificationSettingsWithCompletionHandler_(completed)
        return await future

    async def request_authorization(self) -> bool:
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def completed(granted, error):
            if error is not None:
                loop.call_soon_threadsafe(
                    self._resolve_future, future, None, RuntimeError(str(error))
                )
            else:
                loop.call_soon_threadsafe(
                    self._resolve_future, future, bool(granted), None
                )

        self._center.requestAuthorizationWithOptions_completionHandler_(
            self._authorization_options, completed
        )
        return await future

    async def send(
        self,
        identifier: str,
        title: str,
        body: str,
        user_info: dict[str, Any] | None = None,
    ) -> None:
        content = self._content_class.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setSound_(self._default_sound)
        content.setUserInfo_(user_info or {"url": self._dashboard_url})
        request = self._request_class.requestWithIdentifier_content_trigger_(
            identifier, content, None
        )

        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def completed(error):
            if error is not None:
                loop.call_soon_threadsafe(
                    self._resolve_future, future, None, RuntimeError(str(error))
                )
            else:
                loop.call_soon_threadsafe(self._resolve_future, future, None, None)

        self._center.addNotificationRequest_withCompletionHandler_(request, completed)
        await future

    @staticmethod
    def _resolve_future(future, value, error):
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(value)


class MacOSNotificationService:
    """Applies preferences, permission state, formatting, and persistent dedupe."""

    def __init__(
        self,
        runtime_environment,
        settings_store,
        platform_factory: Callable[[str], Any] = UserNotificationsPlatform,
    ):
        self.runtime = runtime_environment
        self.settings = settings_store
        self.platform_factory = platform_factory
        self._platform = None
        self._reservations: set[str] = set()
        self._dedupe_lock = threading.Lock()
        self._logged_failures: set[str] = set()

    @property
    def supported(self) -> bool:
        return self.runtime.mode is RuntimeMode.MACOS_PACKAGED

    def preferences(self) -> dict[str, Any]:
        categories = {
            category: self.settings.get_setting(
                f"macos_notifications_{category}", "1"
            ) == "1"
            for category in NOTIFICATION_CATEGORIES
        }
        return {
            "enabled": self.settings.get_setting("macos_notifications_enabled", "1") == "1",
            "categories": categories,
        }

    def save_preferences(self, enabled: bool, categories: dict[str, bool]) -> None:
        self.settings.set_setting("macos_notifications_enabled", "1" if enabled else "0")
        for category in NOTIFICATION_CATEGORIES:
            self.settings.set_setting(
                f"macos_notifications_{category}",
                "1" if categories.get(category, False) else "0",
            )

    def _native_platform(self):
        if not self.supported:
            return None
        if self._platform is None:
            self._platform = self.platform_factory(
                f"http://127.0.0.1:{self.runtime.port}/"
            )
        return self._platform

    async def status(self) -> dict[str, Any]:
        payload = {"supported": self.supported, **self.preferences()}
        if not self.supported:
            return {**payload, "authorization": "unsupported", "can_deliver": False}
        try:
            authorization = await self._native_platform().authorization_status()
        except Exception as exc:
            self._log_failure("status", "Could not read macOS notification permission", exc)
            authorization = "unavailable"
        return {
            **payload,
            "authorization": authorization,
            "can_deliver": payload["enabled"] and authorization in AUTHORIZED_STATUSES,
        }

    async def request_authorization(self) -> dict[str, Any]:
        if not self.supported or not self.preferences()["enabled"]:
            return await self.status()
        try:
            current = await self._native_platform().authorization_status()
            if current == "not_determined":
                await self._native_platform().request_authorization()
        except Exception as exc:
            self._log_failure("authorization", "Could not request macOS notification permission", exc)
        return await self.status()

    async def notify_event(self, event: dict[str, Any]) -> bool:
        category = event.get("type")
        if category not in {"achievement", "beaten", "mastery"}:
            return False
        dedupe_key = event.get("dedupe_key")
        if not dedupe_key:
            return False

        username = str(event.get("username") or "A tracked player")
        game = str(event.get("game_title") or "a game")
        if category == "achievement":
            title = "Achievement Unlocked"
            achievement = str(event.get("achievement_title") or "an achievement")
            points = int(event.get("points") or 0)
            points_label = "point" if points == 1 else "points"
            details = f"{game} • {points:,} {points_label}"
            retro_points = int(event.get("retro_points") or 0)
            if retro_points:
                details += f" • {retro_points:,} RetroPoints"
            body = f"{username} earned “{achievement}”\n{details}"
        elif category == "beaten":
            title = "Game Beaten"
            body = f"{username} beat {game}"
        else:
            title = "Game Mastered"
            body = f"{username} mastered {game}"

        return await self._deliver(
            f"event:{category}:{dedupe_key}", category, title, body
        )

    async def notify_update(self, state: dict[str, Any]) -> bool:
        if not state.get("update_available"):
            return False
        version = state.get("latest_release_tag") or state.get("latest_version")
        if not version:
            return False
        version = str(version)
        if self.settings.get_setting("macos_notifications_last_update_version") == version:
            return False
        delivered = await self._deliver(
            f"update:{version}",
            "update",
            "LeftoverAchievements Update Available",
            f"Version {version} is ready to download.",
        )
        if delivered or self.settings.native_notification_delivered(f"update:{version}"):
            self.settings.set_setting("macos_notifications_last_update_version", version)
        return delivered

    async def _deliver(
        self, dedupe_key: str, category: str, title: str, body: str
    ) -> bool:
        reserved = False
        try:
            preferences = self.preferences()
            if (
                not self.supported
                or not preferences["enabled"]
                or not preferences["categories"].get(category, False)
            ):
                return False
            if self.settings.native_notification_delivered(dedupe_key):
                return False
            with self._dedupe_lock:
                if dedupe_key in self._reservations:
                    return False
                self._reservations.add(dedupe_key)
                reserved = True
            if await self._native_platform().authorization_status() not in AUTHORIZED_STATUSES:
                return False
            identifier = "leftover-" + hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
            await self._native_platform().send(identifier, title, body)
            self.settings.mark_native_notification_delivered(dedupe_key)
            return True
        except Exception as exc:
            self._log_failure("delivery", "Could not deliver a macOS notification", exc)
            return False
        finally:
            if reserved:
                with self._dedupe_lock:
                    self._reservations.discard(dedupe_key)

    def _log_failure(self, kind: str, message: str, exc: Exception) -> None:
        if kind in self._logged_failures:
            return
        self._logged_failures.add(kind)
        logger.warning("%s: %s", message, exc)
