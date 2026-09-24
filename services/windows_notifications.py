"""Native Windows tray notifications using the shared event preferences and dedupe."""

from __future__ import annotations

import asyncio
from typing import Any

from runtime import RuntimeMode
from services.macos_notifications import MacOSNotificationService, NOTIFICATION_CATEGORIES


_notification_icon = None
NIIF_NOSOUND = 0x00000010


def set_notification_icon(icon) -> None:
    global _notification_icon
    _notification_icon = icon


class WindowsNotificationPlatform:
    async def authorization_status(self) -> str:
        return "authorized" if _notification_icon is not None else "unavailable"

    async def request_authorization(self) -> bool:
        return _notification_icon is not None

    async def send(self, _identifier: str, title: str, body: str, user_info=None) -> None:
        icon = _notification_icon
        if icon is None:
            raise RuntimeError("The Windows tray icon is unavailable.")
        if (user_info or {}).get("mute_sound"):
            await asyncio.to_thread(send_silent_tray_notification, icon, body, title)
        else:
            await asyncio.to_thread(icon.notify, body, title)


def send_silent_tray_notification(icon, body: str, title: str) -> None:
    """Send pystray's normal balloon with Windows' per-notification no-sound flag."""
    from pystray._util import win32

    icon._message(
        win32.NIM_MODIFY,
        win32.NIF_INFO,
        szInfo=body,
        szInfoTitle=title,
        dwInfoFlags=NIIF_NOSOUND,
    )


class WindowsNotificationService(MacOSNotificationService):
    def __init__(self, runtime_environment, settings_store, platform_factory=None):
        super().__init__(
            runtime_environment,
            settings_store,
            platform_factory or (lambda _dashboard_url: WindowsNotificationPlatform()),
        )

    @property
    def supported(self) -> bool:
        return self.runtime.mode is RuntimeMode.WINDOWS_PACKAGED

    @property
    def settings_prefix(self) -> str:
        return "windows_notifications"

    def preferences(self) -> dict[str, Any]:
        categories = {
            category: self.settings.get_setting(
                f"{self.settings_prefix}_{category}", "1"
            ) == "1"
            for category in NOTIFICATION_CATEGORIES
        }
        return {
            "enabled": self.settings.get_setting(
                f"{self.settings_prefix}_enabled", "1"
            ) == "1",
            "categories": categories,
        }

    def save_preferences(self, enabled: bool, categories: dict[str, bool]) -> None:
        self.settings.set_setting(
            f"{self.settings_prefix}_enabled", "1" if enabled else "0"
        )
        for category in NOTIFICATION_CATEGORIES:
            self.settings.set_setting(
                f"{self.settings_prefix}_{category}",
                "1" if categories.get(category, False) else "0",
            )
