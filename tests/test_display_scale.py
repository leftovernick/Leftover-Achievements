import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

import app as application


PROJECT_ROOT = application.runtime.resource_root


class DisplayScaleTests(unittest.IsolatedAsyncioTestCase):
    def test_scale_defaults_to_compact_and_rejects_unknown_persisted_values(self):
        for stored_value in (None, "", "0", "4", "large"):
            with self.subTest(stored_value=stored_value), patch.object(
                application.db, "get_setting", return_value=stored_value
            ):
                self.assertEqual(application.display_scale(), 1)

    def test_scale_accepts_all_three_presets(self):
        for scale in application.DISPLAY_SCALE_PRESETS:
            with self.subTest(scale=scale), patch.object(
                application.db, "get_setting", return_value=str(scale)
            ):
                self.assertEqual(application.display_scale(), scale)

    def test_setting_scale_uses_application_settings_store(self):
        with patch.object(application.db, "set_setting") as save:
            self.assertEqual(application.set_display_scale("3"), 3)
            save.assert_called_once_with("display_scale", "3")

    async def test_quick_setting_persists_and_broadcasts_without_reload(self):
        queue = asyncio.Queue()
        application.display_event_queues.add(queue)
        try:
            with patch.object(application, "set_display_scale", return_value=2) as save:
                payload = await application.update_display_scale("2")
            self.assertEqual(payload, {"display_scale": 2})
            save.assert_called_once_with("2")
            self.assertEqual(
                queue.get_nowait(), {"type": "display-scale", "scale": 2}
            )
        finally:
            application.display_event_queues.discard(queue)

    def test_display_only_css_modes_and_controls_are_present(self):
        display_template = (PROJECT_ROOT / "templates/display.html").read_text(
            encoding="utf-8"
        )
        admin_template = (PROJECT_ROOT / "templates/admin.html").read_text(
            encoding="utf-8"
        )
        dashboard_template = (PROJECT_ROOT / "templates/dashboard.html").read_text(
            encoding="utf-8"
        )
        css = (PROJECT_ROOT / "static/css/styles.css").read_text(encoding="utf-8")
        javascript = (PROJECT_ROOT / "static/js/display.js").read_text(
            encoding="utf-8"
        )

        self.assertIn('data-display-scale="{{ display_scale }}"', display_template)
        self.assertEqual(display_template.count("data-scale=\""), 3)
        self.assertEqual(
            display_template.count(
                '<div class="display-utility-backdrop" data-close-panel aria-hidden="true"></div>'
            ),
            2,
        )
        self.assertNotIn('<button class="display-utility-backdrop"', display_template)
        self.assertIn("<small>Player</small>", display_template)
        self.assertIn(
            ".achievement-notification.is-mastery .achievement-notification-badge",
            css,
        )
        self.assertIn("aspect-ratio: auto", css)
        self.assertIn('name="display_scale_value"', admin_template)
        self.assertIn('.pi-display[data-display-scale="2"]', css)
        self.assertIn('.pi-display[data-display-scale="3"]', css)
        self.assertNotIn("data-display-scale", dashboard_template)
        for line in css.splitlines():
            if '[data-display-scale="' in line:
                self.assertIn(".pi-display", line)
                self.assertNotIn("display-utility", line)
                self.assertNotIn("display-setting-button", line)
                self.assertNotIn("display-scale-control", line)
                self.assertNotIn("display-speed-control", line)
                self.assertNotIn("display-connection-details", line)
        self.assertNotIn("zoom:", css)
        self.assertIn(".pi-display .display-utility-backdrop:hover", css)
        self.assertIn("-webkit-tap-highlight-color: transparent", css)
        self.assertIn("/display/settings/scale", javascript)
        self.assertIn("addEventListener('display-scale'", javascript)


if __name__ == "__main__":
    unittest.main()
