"""Windows system tray lifecycle and optional native display window."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import webbrowser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from launcher import backend_urls, configure_logging, create_backend_server
from runtime import AlreadyRunningError, local_port_in_use, runtime


class WindowsTrayApplication:
    def __init__(self, instance_lock, logger: logging.Logger):
        self.instance_lock = instance_lock
        self.logger = logger
        self.local_url, self.lan_url = backend_urls()
        self.server = None
        self.backend_thread = None
        self.backend_error = None
        self.shutting_down = False
        self.icon = None
        self.window = None
        self.display_open = False
        self.update_state = {}
        self.notification_state = {}
        self._checking_update = False

    @property
    def server_ready(self):
        return bool(self.server and self.server.started and not self.backend_error)

    def _request_json(self, path: str, method: str = "GET", timeout: int = 5):
        request = Request(
            f"http://127.0.0.1:{runtime.port}{path}",
            method=method,
            data=b"" if method == "POST" else None,
        )
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def _run_backend(self):
        try:
            self.server.run()
        except Exception as exc:
            self.backend_error = str(exc)
            self.logger.exception("Packaged backend failed.")

    def _start_backend(self):
        if local_port_in_use(runtime.port):
            self.backend_error = f"Port {runtime.port} is already in use."
            self.logger.error("Backend startup failed: %s", self.backend_error)
            return
        try:
            self.server = create_backend_server()
        except Exception as exc:
            self.backend_error = str(exc)
            self.logger.exception("Backend initialization failed.")
            return
        self.backend_thread = threading.Thread(target=self._run_backend, name="leftover-backend", daemon=True)
        self.backend_thread.start()

    def _server_title(self):
        if self.backend_error or (self.backend_thread and not self.backend_thread.is_alive()):
            return "Server: Failed"
        return "Server: Running" if self.server_ready else "Server: Starting…"

    def _update_title(self):
        if self._checking_update:
            return "Checking for updates…"
        state = self.update_state
        if state.get("error"):
            return "Unable to check for updates"
        if state.get("update_available") and state.get("latest_version"):
            return f"Update available • {state['latest_version']}"
        return f"Up to date • {state.get('installed_version') or 'development'}"

    def _update_url(self):
        return self.update_state.get("latest_release_asset_url") or self.update_state.get("latest_release_url") if self.update_state.get("update_available") else None

    def _notification_title(self):
        state = self.notification_state
        if not state.get("enabled"):
            return "Notifications: Off"
        return "Notifications: Enabled" if state.get("can_deliver") else "Notifications: Unavailable"

    def _poll_status(self):
        was_ready = False
        next_update = 0.0
        while not self.shutting_down:
            ready = self.server_ready
            if ready and not was_ready:
                self.logger.info("Packaged backend is ready.")
            if ready and (not was_ready or time.monotonic() >= next_update):
                try:
                    self.update_state = self._request_json("/api/update/status")
                    self.notification_state = self._request_json("/api/windows-notifications/status")
                except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                    self.logger.warning("Tray status request failed: %s", exc)
                next_update = time.monotonic() + 15
            if self.backend_thread and not self.backend_thread.is_alive() and not self.backend_error:
                self.backend_error = "The backend stopped unexpectedly."
                self.logger.error("Backend failure: %s", self.backend_error)
            was_ready = ready
            if self.icon:
                self.icon.update_menu()
            time.sleep(0.5 if not ready else 2)

    def _check_for_updates(self, _icon=None, _item=None):
        if not self.server_ready or self._checking_update:
            return
        self._checking_update = True

        def check():
            try:
                self.update_state = self._request_json("/api/update/check", "POST", 35)
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                self.update_state = {"error": str(exc)}
                self.logger.warning("Tray update check failed: %s", exc)
            finally:
                self._checking_update = False
                self.icon.update_menu()

        threading.Thread(target=check, name="leftover-update-tray", daemon=True).start()

    def _open_dashboard(self, _icon=None, _item=None):
        webbrowser.open(self.local_url)

    def _open_display(self, _icon=None, _item=None):
        if not self.server_ready or self.shutting_down or self.window is None:
            return
        if not self.display_open:
            self.window.load_url(f"http://127.0.0.1:{runtime.port}/display")
            self.display_open = True
        self.window.show()
        self.window.restore()

    def _close_display(self):
        if self.shutting_down:
            return True
        self.display_open = False
        # Hide on a separate thread because pywebview's closing event is synchronous.
        threading.Thread(target=self._hide_display, daemon=True).start()
        return False

    def _hide_display(self):
        self.window.hide()
        self.window.load_url("about:blank")

    def _copy_address(self, _icon=None, _item=None):
        address = self.lan_url or self.local_url
        # Tk uses the native Windows clipboard and is available with Python.
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(address)
        root.update()
        root.destroy()
        self.logger.info("Dashboard address copied to the clipboard.")

    def _view_update(self, _icon=None, _item=None):
        url = self._update_url()
        if url:
            webbrowser.open(url)

    def _quit(self, _icon=None, _item=None):
        if self.shutting_down:
            return
        self.shutting_down = True
        self.logger.info("Quit requested from the system tray.")
        if self.server:
            self.server.should_exit = True
        if self.window:
            self.window.destroy()
        elif self.icon:
            self.icon.stop()

    def _stop_backend(self):
        if self.server:
            self.server.should_exit = True
        if self.backend_thread:
            self.backend_thread.join(timeout=20)
            if self.backend_thread.is_alive() and self.server:
                self.logger.warning("Backend shutdown timed out; forcing exit.")
                self.server.force_exit = True
                self.backend_thread.join(timeout=5)
        if self.icon:
            self.icon.stop()
        from services.windows_notifications import set_notification_icon

        set_notification_icon(None)
        self.instance_lock.release()
        self.logger.info("Windows system tray application stopped.")

    def run(self):
        import pystray
        import webview
        from PIL import Image

        self.logger.info("Starting Windows system tray application.")
        self.logger.info("Dashboard: %s", self.local_url)
        if self.lan_url:
            self.logger.info("LAN dashboard: %s", self.lan_url)
        self.logger.info("Persistent data: %s", runtime.data_dir)

        self._start_backend()
        self.window = webview.create_window(
            "LeftoverAchievements Display", "about:blank",
            width=1280, height=720, hidden=True, background_color="#101014",
        )
        self.window.events.closing += self._close_display

        item = pystray.MenuItem
        menu = pystray.Menu(
            item(lambda _: self._server_title(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Open Dashboard", self._open_dashboard, default=True),
            item("Open Display Window", self._open_display, enabled=lambda _: self.server_ready and self.window is not None),
            item("Copy Dashboard Address", self._copy_address),
            pystray.Menu.SEPARATOR,
            item(lambda _: self._notification_title(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item("Check for Updates", self._check_for_updates, enabled=lambda _: self.server_ready),
            item(lambda _: self._update_title(), None, enabled=False),
            item("View Update…", self._view_update, visible=lambda _: bool(self._update_url())),
            pystray.Menu.SEPARATOR,
            item("Quit LeftoverAchievements", self._quit),
        )
        image = Image.open(runtime.resource_path("static", "images", "favicon.png")).convert("RGBA")
        self.icon = pystray.Icon("LeftoverAchievements", image, "LeftoverAchievements", menu)
        from services.windows_notifications import set_notification_icon

        set_notification_icon(self.icon)
        tray_thread = threading.Thread(target=self.icon.run, name="leftover-system-tray", daemon=True)
        tray_thread.start()
        threading.Thread(target=self._poll_status, name="leftover-tray-status", daemon=True).start()
        try:
            try:
                webview.start(gui="edgechromium")
            except Exception:
                self.logger.exception("Native Windows Display could not start.")
            if not self.shutting_down:
                self.window = None
                self.display_open = False
                self.icon.update_menu()
                tray_thread.join()
        finally:
            self.shutting_down = True
            self._stop_backend()


def main() -> int:
    if sys.platform != "win32":
        print("The Windows system tray application can only run on Windows.", file=sys.stderr)
        return 1
    if os.getenv("LEFTOVER_HEADLESS") == "1":
        from launcher import main as run_headless

        return run_headless()
    logger = configure_logging()
    instance_lock = runtime.instance_lock()
    try:
        instance_lock.acquire()
    except AlreadyRunningError:
        logger.info("LeftoverAchievements is already running; exiting duplicate launch.")
        return 0
    try:
        WindowsTrayApplication(instance_lock, logger).run()
    except Exception:
        logger.exception("Windows system tray application failed.")
        return 1
    finally:
        instance_lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
