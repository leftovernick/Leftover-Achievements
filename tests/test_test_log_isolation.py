import io
import logging
import tempfile
import unittest
from pathlib import Path

from tests import test_live_activity_refresh as activity_tests
from tests import test_macos_notifications as notification_tests


class TestLogIsolationTests(unittest.TestCase):
    def test_simulated_failures_do_not_reach_application_file_handlers(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "application.log"
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setLevel(logging.WARNING)
            root = logging.getLogger()
            root.addHandler(handler)
            try:
                suite = unittest.TestSuite([
                    activity_tests.LiveActivityRefreshTests("test_current_activity_api_failure_preserves_cached_state"),
                    notification_tests.MacOSNotificationTests("test_settings_failure_is_non_fatal"),
                ])
                output = io.StringIO()
                result = unittest.TextTestRunner(stream=output).run(suite)
                handler.flush()
                self.assertTrue(result.wasSuccessful(), output.getvalue())
                self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            finally:
                root.removeHandler(handler)
                handler.close()
