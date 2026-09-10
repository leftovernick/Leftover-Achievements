import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RaspberryPiBootBrandingTests(unittest.TestCase):
    def test_default_installers_leave_boot_files_alone(self):
        bootstrap = (PROJECT_ROOT / "scripts/bootstrap-pi.sh").read_text(encoding="utf-8")
        installer = (PROJECT_ROOT / "scripts/install-pi.sh").read_text(encoding="utf-8")
        helper = (PROJECT_ROOT / "scripts/pi-privileged-helper.sh").read_text(encoding="utf-8")

        for source in (bootstrap, installer, helper):
            self.assertNotIn("/boot/config.txt", source)
            self.assertNotIn("/boot/firmware/config.txt", source)
            self.assertNotIn("/boot/cmdline.txt", source)
            self.assertNotIn("/boot/firmware/cmdline.txt", source)
            self.assertNotIn('configure-pi-boot-branding.sh" enable', source)
            self.assertNotIn("rpi-splash-screen-support", source)
            self.assertNotIn("configure-splash", source)
            self.assertNotIn("update-initramfs", source)
            self.assertNotIn("fullscreen_logo=1", source)
            self.assertNotIn("loglevel=3", source)
            self.assertNotIn("systemd.show_status=false", source)
            self.assertNotIn("vt.global_cursor_default=0", source)
            self.assertNotIn("disable_splash=1", source)
        self.assertIn("Raspberry Pi boot configuration left unchanged.", bootstrap)
        self.assertIn("Raspberry Pi boot configuration left unchanged.", installer)

    def test_recovery_only_helper_has_no_enable_path(self):
        script = (PROJECT_ROOT / "scripts/configure-pi-boot-branding.sh").read_text(encoding="utf-8")
        self.assertIn("restore-default|disable", script)
        self.assertIn("Early-boot customization is no longer supported", script)
        self.assertNotIn("rpi-splash-screen-support", script)
        self.assertNotIn("configure-splash", script)
        self.assertNotIn("update-initramfs", script)
        self.assertNotIn("SPLASH_IMAGE", script)

    def test_recovery_removes_only_managed_config_and_known_cmdline_changes(self):
        script = PROJECT_ROOT / "scripts/configure-pi-boot-branding.sh"
        with tempfile.TemporaryDirectory() as directory:
            boot = Path(directory)
            config = boot / "config.txt"
            cmdline = boot / "cmdline.txt"
            config.write_text(
                "gpu_mem=128\n"
                "# BEGIN LeftoverAchievements appliance boot\n"
                "[all]\n"
                "disable_splash=1\n"
                "# END LeftoverAchievements appliance boot\n"
                "# BEGIN LeftoverAchievements boot branding\n"
                "[all]\n"
                "disable_splash=1\n"
                "# END LeftoverAchievements boot branding\n"
                "dtoverlay=vc4-kms-v3d\n",
                encoding="utf-8",
            )
            original = "console=serial0,115200 console=tty1 root=PARTUUID=test quiet splash custom.option=yes\n"
            (boot / "cmdline.txt.leftover-achievements.bak").write_text(original, encoding="utf-8")
            cmdline.write_text(
                "console=serial0,115200 root=PARTUUID=test custom.option=yes quiet "
                "loglevel=3 logo.nologo fullscreen_logo=1 fullscreen_logo_name=logo.tga "
                "vt.global_cursor_default=0 systemd.show_status=false rd.systemd.show_status=false\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["LEFTOVER_TEST_BOOT_DIRECTORY"] = directory
            subprocess.run([str(script), "restore-default"], env=env, check=True, capture_output=True, text=True)

            self.assertEqual(config.read_text(encoding="utf-8"), "gpu_mem=128\ndtoverlay=vc4-kms-v3d\n")
            restored = cmdline.read_text(encoding="utf-8").split()
            self.assertIn("custom.option=yes", restored)
            self.assertIn("console=tty1", restored)
            self.assertIn("quiet", restored)
            self.assertIn("splash", restored)
            self.assertNotIn("loglevel=3", restored)
            self.assertNotIn("fullscreen_logo=1", restored)
            self.assertNotIn("vt.global_cursor_default=0", restored)

    def test_shell_launchers_parse(self):
        for relative_path in (
            "scripts/configure-pi-boot-branding.sh",
            "scripts/bootstrap-pi.sh",
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

    def test_installers_keep_kiosk_cursor_and_loading_page(self):
        installer = (PROJECT_ROOT / "scripts/install-pi.sh").read_text(encoding="utf-8")
        bootstrap = (PROJECT_ROOT / "scripts/bootstrap-pi.sh").read_text(encoding="utf-8")
        session = (PROJECT_ROOT / "scripts/configure-pi-appliance-session.sh").read_text(encoding="utf-8")
        self.assertIn('configure-pi-appliance-session.sh" enable', installer)
        self.assertIn('configure-pi-appliance-session.sh" status', installer)
        self.assertIn('configure-pi-appliance-session.sh" enable', bootstrap)
        self.assertIn("XCURSOR_THEME=LeftoverAchievementsInvisible", session)
        self.assertIn("run-kiosk-session.sh", session)
        self.assertNotIn("cmdline.txt", session)


if __name__ == "__main__":
    unittest.main()
