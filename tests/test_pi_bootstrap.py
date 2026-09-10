import os
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = PROJECT_ROOT / "scripts/bootstrap-pi.sh"


def run_bootstrap_functions(
    body: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LEFTOVER_BOOTSTRAP_LIBRARY_ONLY"] = "1"
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", f'source "$1"\n{body}', "bootstrap-test", str(BOOTSTRAP)],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )


class RaspberryPiBootstrapTests(unittest.TestCase):
    def test_successful_install_validates_then_reaches_reboot(self):
        result = run_bootstrap_functions(
            """
            install_leftover_achievements() { echo INSTALL_OK; }
            validate_installation() { echo VALIDATE_OK; }
            cleanup_bootstrap_temp() { echo CLEANUP_OK; }
            sync() { echo SYNC_OK; }
            hostname() { echo leftover-pi; }
            sudo() { echo "SUDO:$*"; }
            REBOOT_DELAY_SECONDS=0
            NO_REBOOT=0
            run_bootstrap
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.stdout.index("INSTALL_OK"), result.stdout.index("VALIDATE_OK"))
        self.assertLess(result.stdout.index("VALIDATE_OK"), result.stdout.index("SYNC_OK"))
        self.assertIn("LeftoverAchievements installation complete.", result.stdout)
        self.assertIn("will reboot in 0 seconds", result.stdout)
        self.assertIn("Press Ctrl+C to cancel", result.stdout)
        self.assertIn("SUDO:reboot", result.stdout)

    def test_failed_install_does_not_validate_or_reboot(self):
        result = run_bootstrap_functions(
            """
            install_leftover_achievements() { echo INSTALL_FAILED; return 9; }
            validate_installation() { echo VALIDATE_SHOULD_NOT_RUN; }
            finish_installation() { echo REBOOT_SHOULD_NOT_RUN; }
            run_bootstrap
            """
        )
        self.assertEqual(result.returncode, 9, result.stderr)
        self.assertNotIn("VALIDATE_SHOULD_NOT_RUN", result.stdout)
        self.assertNotIn("REBOOT_SHOULD_NOT_RUN", result.stdout)

    def test_failed_health_check_does_not_reboot(self):
        result = run_bootstrap_functions(
            """
            install_leftover_achievements() { echo INSTALL_OK; }
            validate_installation() { echo HEALTH_FAILED; return 8; }
            finish_installation() { echo REBOOT_SHOULD_NOT_RUN; }
            run_bootstrap
            """
        )
        self.assertEqual(result.returncode, 8, result.stderr)
        self.assertIn("HEALTH_FAILED", result.stdout)
        self.assertNotIn("REBOOT_SHOULD_NOT_RUN", result.stdout)

    def test_no_reboot_mode_leaves_manual_instruction(self):
        result = run_bootstrap_functions(
            """
            install_leftover_achievements() { :; }
            validate_installation() { :; }
            cleanup_bootstrap_temp() { :; }
            sync() { :; }
            hostname() { echo leftover-pi; }
            sudo() { echo "SUDO:$*"; }
            run_bootstrap --no-reboot
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Automatic reboot disabled.", result.stdout)
        self.assertIn("Reboot later with:\nsudo reboot", result.stdout)
        self.assertNotIn("SUDO:reboot", result.stdout)

    def test_environment_no_reboot_override_is_honored(self):
        result = run_bootstrap_functions(
            """
            sync() { :; }
            hostname() { echo leftover-pi; }
            sudo() { echo "SUDO:$*"; }
            finish_installation
            """,
            {"LEFTOVER_ACHIEVEMENTS_NO_REBOOT": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Automatic reboot disabled.", result.stdout)
        self.assertNotIn("SUDO:reboot", result.stdout)

    def test_ctrl_c_cancels_reboot_but_keeps_install_complete(self):
        result = run_bootstrap_functions(
            """
            sync() { :; }
            hostname() { echo leftover-pi; }
            sudo() { echo "SUDO:$*"; }
            sleep() { cancel_auto_reboot; return 130; }
            REBOOT_DELAY_SECONDS=10
            NO_REBOOT=0
            finish_installation
            """
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LeftoverAchievements installation complete.", result.stdout)
        self.assertIn("Reboot later with:\nsudo reboot", result.stdout)
        self.assertNotIn("SUDO:reboot", result.stdout)

    def test_bootstrap_health_checks_service_session_and_display(self):
        script = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("systemctl is-active --quiet leftover-achievements.service", script)
        self.assertIn('configure-pi-appliance-session.sh\" status', script)
        self.assertIn("http://127.0.0.1:8000/display", script)
        self.assertIn("LEFTOVER_ACHIEVEMENTS_NO_REBOOT", script)
        self.assertIn("--no-reboot", script)


if __name__ == "__main__":
    unittest.main()
