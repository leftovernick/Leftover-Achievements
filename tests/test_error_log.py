import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as application


PROJECT_ROOT = application.runtime.resource_root


class ErrorLogTests(unittest.TestCase):
    def test_recent_errors_are_filtered_newest_first_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "leftover-achievements.log"
            log_path.write_text(
                "2026-09-10 12:00:00,000 INFO app: Started\n"
                "2026-09-10 12:01:00,000 WARNING app: API call failed y=secret-value\n"
                "2026-09-10 12:02:00,000 ERROR services.updater: token=other-secret failed\n",
                encoding="utf-8",
            )
            with patch.object(
                application.db, "get_setting", return_value="secret-value"
            ):
                entries = application.recent_application_errors(log_path=log_path)

        self.assertEqual([entry["level"] for entry in entries], ["ERROR", "WARNING"])
        self.assertNotIn("secret-value", str(entries))
        self.assertNotIn("other-secret", str(entries))
        self.assertIn("[REDACTED]", str(entries))

    def test_error_panel_is_present_in_settings(self):
        template = (PROJECT_ROOT / "templates/admin.html").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "static/css/styles.css").read_text(encoding="utf-8")

        self.assertIn('id="recent-errors"', template)
        self.assertIn("recent_errors", template)
        self.assertIn(".application-error-list", css)
        self.assertIn("Show error details", template)
        self.assertIn("{{ entry.details }}", template)

    def test_tracebacks_are_preserved_redacted_and_not_mixed_with_info(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "leftover-achievements.log"
            log_path.write_text(
                "2026-09-14 12:00:00,000 ERROR asyncio: Task exception was never retrieved\n"
                "future: <Task name='weekly refresh'>\n"
                "Traceback (most recent call last):\n"
                "  request https://example.test/?y=url-secret&token=token-secret\n"
                "  Authorization: Bearer bearer-secret\n"
                "  payload: {'password': 'password-secret'}\n"
                "TimeoutError: saved-secret env-secret\n"
                "2026-09-14 12:01:00,000 INFO app: Started\n"
                "not part of the traceback\n"
                "2026-09-14 12:02:00,000 WARNING app: DNS failed\n",
                encoding="utf-8",
            )
            with (
                patch.object(application.db, "get_setting", return_value="saved-secret"),
                patch.object(application, "legacy_environment_api_key", "env-secret"),
            ):
                entries = application.recent_application_errors(log_path=log_path)
        self.assertEqual(entries[0]["details"], "")
        details = entries[1]["details"]
        self.assertIn("Traceback (most recent call last)", details)
        self.assertIn("TimeoutError", details)
        self.assertNotIn("not part of the traceback", details)
        for secret in ("url-secret", "token-secret", "bearer-secret", "password-secret", "saved-secret", "env-secret"):
            self.assertNotIn(secret, details)


if __name__ == "__main__":
    unittest.main()
