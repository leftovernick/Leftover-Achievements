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


if __name__ == "__main__":
    unittest.main()
