"""Lifecycle checks for the Windows tray wrapper without a GUI session."""

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from windows_tray import WindowsTrayApplication


class WindowsTrayTests(unittest.TestCase):
    def setUp(self):
        with patch("windows_tray.backend_urls", return_value=("http://127.0.0.1:8000/", None)):
            self.application = WindowsTrayApplication(Mock(), logging.getLogger(__name__))
        self.application.server = SimpleNamespace(started=True)
        self.application.window = Mock()

    def test_opening_again_focuses_display_without_reloading(self):
        self.application._open_display()
        self.application._open_display()

        self.application.window.load_url.assert_called_once()
        self.assertEqual(self.application.window.show.call_count, 2)
        self.assertEqual(self.application.window.restore.call_count, 2)

    def test_closing_display_keeps_backend_and_allows_reopen(self):
        with patch("windows_tray.threading.Thread") as thread_class:
            self.assertFalse(self.application._close_display())

        self.assertFalse(self.application.shutting_down)
        self.assertFalse(self.application.display_open)
        self.assertTrue(self.application.server.started)
        thread_class.return_value.start.assert_called_once()
        self.application._open_display()
        self.application.window.load_url.assert_called_once()
