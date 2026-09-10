import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RaspberryPiApplianceSessionTests(unittest.TestCase):
    def test_session_is_dedicated_labwc_not_desktop_overlay(self):
        script = (PROJECT_ROOT / "scripts/configure-pi-appliance-session.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("/usr/share/wayland-sessions", script)
        self.assertIn("labwc) -C $CONFIG_DIR", script)
        self.assertIn("user-session=$SESSION_NAME", script)
        self.assertIn("autologin-session=$SESSION_NAME", script)
        self.assertIn("run-kiosk-session.sh", script)
        self.assertNotIn("startlxde", script.lower())
        self.assertNotIn("lxpanel &", script.lower())
        self.assertNotIn("pcmanfm &", script.lower())

    def test_cursor_hiding_is_scoped_to_appliance_session(self):
        script = (PROJECT_ROOT / "scripts/configure-pi-appliance-session.sh").read_text(
            encoding="utf-8"
        )
        css = (PROJECT_ROOT / "static/css/styles.css").read_text(encoding="utf-8")
        self.assertIn("XCURSOR_THEME=LeftoverAchievementsInvisible", script)
        self.assertIn("XCURSOR_SIZE=1", script)
        self.assertIn("<touch mouseEmulation=\"no\" />", script)
        self.assertIn("0x72756358", script)
        self.assertIn(".pi-display * { cursor: none !important; }", css)
        self.assertNotIn("/etc/environment", script)

    def test_recovery_removes_only_session_selection(self):
        script = (PROJECT_ROOT / "scripts/configure-pi-appliance-session.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('rm -f "$LIGHTDM_CONFIG"', script)
        self.assertIn("normal OS desktop/session", script)
        self.assertNotIn("systemctl disable ssh", script)


if __name__ == "__main__":
    unittest.main()
