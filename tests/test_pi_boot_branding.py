import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RaspberryPiBootBrandingTests(unittest.TestCase):
    def test_default_boot_configuration_avoids_early_splash_stack(self):
        script = (
            PROJECT_ROOT / "scripts/configure-pi-boot-branding.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn("rpi-splash-screen-support", script)
        self.assertNotIn("configure-splash", script)
        self.assertNotIn("update-initramfs", script)
        self.assertNotIn("SPLASH_IMAGE", script)
        self.assertIn("/boot/firmware/cmdline.txt", script)
        self.assertIn("/boot/cmdline.txt", script)
        self.assertIn("console=tty1|quiet|splash", script)
        self.assertIn('output+=" quiet loglevel=3 logo.nologo', script)
        self.assertIn('echo "[all]"', script)
        self.assertIn('echo "disable_splash=1"', script)
        self.assertIn("fullscreen_logo=*|fullscreen_logo_name=*", script)
        self.assertIn("enable|disable|status", script)
        self.assertNotIn("YOUR_USER", script)

    def test_shell_launchers_parse(self):
        for relative_path in (
            "scripts/configure-pi-boot-branding.sh",
            "scripts/start-kiosk.sh",
            "scripts/run-kiosk-session.sh",
            "scripts/configure-pi-appliance-session.sh",
            "scripts/install-pi.sh",
        ):
            with self.subTest(script=relative_path):
                subprocess.run(
                    ["bash", "-n", str(PROJECT_ROOT / relative_path)],
                    check=True,
                )

    def test_kiosk_stays_branded_until_display_is_ready(self):
        launcher = (PROJECT_ROOT / "scripts/start-kiosk.sh").read_text(encoding="utf-8")
        loading_page = (PROJECT_ROOT / "deploy/kiosk-loading.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("--password-store=basic", launcher)
        self.assertIn("--ozone-platform=wayland", launcher)
        self.assertIn("--user-data-dir=", launcher)
        self.assertIn("kiosk-loading.html", launcher)
        self.assertIn("disable-kiosk", launcher)
        self.assertIn("leftover-achievements-logo.png", loading_page)
        self.assertIn('window.location.replace(displayUrl)', loading_page)
        self.assertIn('new URL("/static/images/favicon.png", displayUrl)', loading_page)

    def test_installer_enables_and_verifies_appliance_mode(self):
        installer = (PROJECT_ROOT / "scripts/install-pi.sh").read_text(encoding="utf-8")
        self.assertIn('configure-pi-boot-branding.sh" enable', installer)
        self.assertIn('configure-pi-appliance-session.sh" enable', installer)
        self.assertIn('configure-pi-boot-branding.sh" status', installer)
        self.assertIn('configure-pi-appliance-session.sh" status', installer)


if __name__ == "__main__":
    unittest.main()
