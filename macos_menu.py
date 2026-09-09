"""Native macOS menu bar lifecycle for packaged LeftoverAchievements builds."""

from __future__ import annotations

import json
import logging
import sys
import threading
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSStatusBar,
    NSTerminateLater,
    NSTerminateNow,
    NSVariableStatusItemLength,
    NSWorkspace,
)
from Foundation import NSObject, NSTimer, NSURL

from launcher import backend_urls, configure_logging, create_backend_server
from runtime import AlreadyRunningError, local_port_in_use, runtime


class MenuBarDelegate(NSObject):
    def configureWithLock_logger_(self, instance_lock, logger):
        self.instance_lock = instance_lock
        self.logger: logging.Logger = logger
        self.local_url, self.lan_url = backend_urls()
        self.server = None
        self.backend_thread: threading.Thread | None = None
        self.backend_error: str | None = None
        self.backend_ready_logged = False
        self.update_request_running = False
        self.shutting_down = False
        self.shutdown_complete = False
        self.status_item = None
        self.server_status_item = None
        self.update_status_item = None
        self.view_update_item = None
        self.update_url: str | None = None

    def applicationDidFinishLaunching_(self, _notification):
        application = NSApplication.sharedApplication()
        application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self._create_status_menu()
        self.logger.info("macOS menu bar application launched.")
        self.logger.info("Dashboard: %s", self.local_url)
        if self.lan_url:
            self.logger.info("LAN dashboard: %s", self.lan_url)
        self.logger.info("Persistent data: %s", runtime.data_dir)

        if local_port_in_use(runtime.port):
            self.backend_error = f"Port {runtime.port} is already in use."
            self.logger.error("Backend startup failed: %s", self.backend_error)
            self._set_server_status("Server: Failed")
        else:
            self._start_backend()

        self.status_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "refreshServerStatus:", None, True
        )
        self.update_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            15.0, self, "refreshCachedUpdateStatus:", None, True
        )

    def _create_status_menu(self):
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        button = self.status_item.button()
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "trophy.fill", "LeftoverAchievements"
        )
        if image is not None:
            image.setTemplate_(True)
            button.setImage_(image)
        else:
            button.setTitle_("LA")
        button.setToolTip_("LeftoverAchievements")

        menu = NSMenu.alloc().init()
        title = self._menu_item("LeftoverAchievements", None)
        title.setEnabled_(False)
        menu.addItem_(title)
        menu.addItem_(NSMenuItem.separatorItem())

        self.server_status_item = self._menu_item("Server: Starting…", None)
        self.server_status_item.setEnabled_(False)
        menu.addItem_(self.server_status_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self._menu_item("Open Dashboard", "openDashboard:"))
        menu.addItem_(self._menu_item("Open Display", "openDisplay:"))
        menu.addItem_(self._menu_item("Copy Dashboard Address", "copyDashboardAddress:"))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self._menu_item("Check for Updates", "checkForUpdates:"))

        self.update_status_item = self._menu_item("Update status: Checking…", None)
        self.update_status_item.setEnabled_(False)
        menu.addItem_(self.update_status_item)
        self.view_update_item = self._menu_item("View Update…", "viewUpdate:")
        self.view_update_item.setHidden_(True)
        menu.addItem_(self.view_update_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self._menu_item("Quit LeftoverAchievements", "quitApplication:"))
        self.status_item.setMenu_(menu)

    def _menu_item(self, title: str, action: str | None):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        if action:
            item.setTarget_(self)
        return item

    def _start_backend(self):
        self.logger.info("Starting packaged backend.")
        try:
            self.server = create_backend_server()
        except Exception as exc:
            self.backend_error = str(exc)
            self.logger.exception("Backend initialization failed.")
            self._set_server_status("Server: Failed")
            return
        self.backend_thread = threading.Thread(
            target=self._run_backend,
            name="leftover-backend",
            daemon=True,
        )
        self.backend_thread.start()

    def _run_backend(self):
        try:
            self.server.run()
        except Exception as exc:
            self.backend_error = str(exc)
            self.logger.exception("Packaged backend failed.")

    def refreshServerStatus_(self, _timer):
        if self.shutting_down:
            return
        if self.backend_error:
            self._set_server_status("Server: Failed")
            return
        if self.backend_thread is not None and not self.backend_thread.is_alive():
            self.backend_error = "The backend stopped unexpectedly."
            self.logger.error("Backend failure: %s", self.backend_error)
            self._set_server_status("Server: Failed")
            return
        if self.server is not None and self.server.started:
            self._set_server_status("Server: Running")
            if not self.backend_ready_logged:
                self.backend_ready_logged = True
                self.logger.info("Packaged backend is ready.")
                self._request_update_state(check_now=False)
            return
        self._set_server_status("Server: Starting…")

    def _set_server_status(self, title: str):
        if self.server_status_item is not None and self.server_status_item.title() != title:
            self.server_status_item.setTitle_(title)

    def refreshCachedUpdateStatus_(self, _timer):
        if self.server is not None and self.server.started:
            self._request_update_state(check_now=False)

    def _request_update_state(self, check_now: bool):
        if self.update_request_running:
            return
        self.update_request_running = True
        if check_now:
            self.update_status_item.setTitle_("Checking for updates…")
            self.logger.info("User requested an application update check.")
        threading.Thread(
            target=self._fetch_update_state,
            args=(check_now,),
            name="leftover-update-menu",
            daemon=True,
        ).start()

    def _fetch_update_state(self, check_now: bool):
        endpoint = "check" if check_now else "status"
        request = Request(
            f"http://127.0.0.1:{runtime.port}/api/update/{endpoint}",
            method="POST" if check_now else "GET",
            data=b"" if check_now else None,
        )
        try:
            with urlopen(request, timeout=35 if check_now else 5) as response:
                payload = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            payload = {"error": str(exc)}
            self.logger.warning("Menu update status request failed: %s", exc)
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyUpdateState:", payload, False
        )

    def applyUpdateState_(self, payload: dict[str, Any]):
        self.update_request_running = False
        installed = payload.get("installed_version") or "development"
        latest = payload.get("latest_version")
        error = payload.get("error")
        if error:
            title = "Unable to check for updates"
            self.update_url = None
        elif payload.get("update_available") and latest:
            title = f"Update available • {latest}"
            self.update_url = payload.get("latest_release_asset_url") or payload.get(
                "latest_release_url"
            )
        else:
            title = f"Up to date • {installed}"
            self.update_url = None
        self.update_status_item.setTitle_(title)
        self.view_update_item.setHidden_(not bool(self.update_url))

    def _open_url(self, url: str):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def openDashboard_(self, _sender):
        self._open_url(self.local_url)

    def openDisplay_(self, _sender):
        self._open_url(f"http://127.0.0.1:{runtime.port}/display")

    def copyDashboardAddress_(self, _sender):
        address = self.lan_url or self.local_url
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(address, NSPasteboardTypeString)
        self.logger.info("Dashboard address copied to the clipboard.")

    def checkForUpdates_(self, _sender):
        if self.server is not None and self.server.started:
            self._request_update_state(check_now=True)
        else:
            self.update_status_item.setTitle_("Unable to check for updates")

    def viewUpdate_(self, _sender):
        if self.update_url:
            self._open_url(self.update_url)

    def quitApplication_(self, sender):
        self.logger.info("Quit requested from the menu bar.")
        NSApplication.sharedApplication().terminate_(sender)

    def applicationShouldTerminate_(self, _application):
        if self.shutdown_complete:
            return NSTerminateNow
        if self.shutting_down:
            return NSTerminateLater
        self.shutting_down = True
        self._set_server_status("Server: Stopping…")
        threading.Thread(
            target=self._stop_backend,
            name="leftover-shutdown",
            daemon=False,
        ).start()
        return NSTerminateLater

    def _stop_backend(self):
        self.logger.info("Stopping packaged backend.")
        if self.server is not None:
            self.server.should_exit = True
        if self.backend_thread is not None:
            self.backend_thread.join(timeout=20)
            if self.backend_thread.is_alive() and self.server is not None:
                self.logger.warning("Backend shutdown timed out; forcing exit.")
                self.server.force_exit = True
                self.backend_thread.join(timeout=5)
        self.shutdown_complete = True
        self.instance_lock.release()
        self.logger.info("macOS menu bar application stopped.")
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "finishTermination:", None, False
        )

    def finishTermination_(self, _unused):
        NSApplication.sharedApplication().replyToApplicationShouldTerminate_(True)

    def applicationWillTerminate_(self, _notification):
        if self.server is not None:
            self.server.should_exit = True
        self.instance_lock.release()


def main() -> int:
    if sys.platform != "darwin":
        print("The macOS menu bar application can only run on macOS.", file=sys.stderr)
        return 1

    logger = configure_logging()
    logger.info("Starting macOS menu bar application.")
    instance_lock = runtime.instance_lock()
    try:
        instance_lock.acquire()
    except AlreadyRunningError:
        logger.info("LeftoverAchievements is already running; exiting duplicate launch.")
        return 0

    application = NSApplication.sharedApplication()
    application.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = MenuBarDelegate.alloc().init()
    delegate.configureWithLock_logger_(instance_lock, logger)
    application.setDelegate_(delegate)
    try:
        application.run()
    finally:
        instance_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
