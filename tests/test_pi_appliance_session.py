import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_SCRIPT = PROJECT_ROOT / "scripts/configure-pi-appliance-session.sh"


def run_session_functions(directory: str, body: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LEFTOVER_APPLIANCE_SESSION_LIBRARY_ONLY"] = "1"
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"\n'
            'STATE_DIR="$2/state"\n'
            'LIGHTDM_MAIN="$2/lightdm.conf"\n'
            'LIGHTDM_CONFIG="$2/90-leftover-achievements.conf"\n'
            'LIGHTDM_SESSION_STATE="$STATE_DIR/lightdm-main-session.state"\n'
            'SESSION_FILE="$2/leftover-achievements.desktop"\n'
            + body,
            "session-test",
            str(SESSION_SCRIPT),
            directory,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


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

    def test_active_rpd_sessions_are_replaced_without_touching_other_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "lightdm.conf"
            config.write_text(
                "# Raspberry Pi desktop defaults\n"
                "[Seat:*]\n"
                "# user-session=commented-example\n"
                "autologin-user=leftovernick\n"
                "user-session=rpd-labwc # keep this explanation\n"
                "greeter-hide-users=false\n"
                "autologin-session = rpd-labwc\n",
                encoding="utf-8",
            )
            result = run_session_functions(directory, "patch_lightdm_main_sessions\n")
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = config.read_text(encoding="utf-8")
            self.assertIn("# Raspberry Pi desktop defaults", updated)
            self.assertIn("# user-session=commented-example", updated)
            self.assertIn("autologin-user=leftovernick", updated)
            self.assertIn("greeter-hide-users=false", updated)
            self.assertIn("user-session=leftover-achievements # keep this explanation", updated)
            self.assertIn("autologin-session = leftover-achievements", updated)

    def test_lightdm_patch_is_idempotent_and_disable_restores_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "lightdm.conf"
            original = (
                "[Seat:*]\n"
                "autologin-user=leftovernick\n"
                "user-session=rpd-labwc\n"
                "autologin-session=rpd-labwc\n"
                "xserver-command=X -nocursor\n"
            )
            config.write_text(original, encoding="utf-8")
            result = run_session_functions(
                directory,
                "patch_lightdm_main_sessions\n"
                "first=$(cat \"$LIGHTDM_MAIN\")\n"
                "patch_lightdm_main_sessions\n"
                "second=$(cat \"$LIGHTDM_MAIN\")\n"
                "[[ \"$first\" == \"$second\" ]]\n"
                "restore_lightdm_main_sessions\n",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertFalse((Path(directory) / "state/lightdm-main-session.state").exists())

    def test_verification_fails_when_main_config_still_selects_rpd_labwc(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "lightdm.conf").write_text(
                "[Seat:*]\nuser-session=rpd-labwc\nautologin-session=rpd-labwc\n",
                encoding="utf-8",
            )
            (root / "90-leftover-achievements.conf").write_text(
                "[Seat:*]\nuser-session=leftover-achievements\nautologin-session=leftover-achievements\n",
                encoding="utf-8",
            )
            (root / "leftover-achievements.desktop").write_text(
                "[Desktop Entry]\nName=LeftoverAchievements\n", encoding="utf-8"
            )
            result = run_session_functions(directory, "verify_lightdm_session_selection\n")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("normal rpd-labwc desktop", result.stdout)
            self.assertIn("autologin still selects", result.stdout)


if __name__ == "__main__":
    unittest.main()
