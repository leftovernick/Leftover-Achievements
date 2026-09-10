import struct
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RaspberryPiBootBrandingTests(unittest.TestCase):
    def test_early_splash_meets_raspberry_pi_format_limits(self):
        splash = PROJECT_ROOT / "deploy/boot/leftover-achievements-splash.tga"
        payload = splash.read_bytes()
        (
            id_length,
            color_map_type,
            image_type,
            _color_map_first,
            _color_map_length,
            _color_map_depth,
            _x_origin,
            _y_origin,
            width,
            height,
            depth,
            _descriptor,
        ) = struct.unpack("<BBBHHBHHHHBB", payload[:18])

        self.assertEqual(color_map_type, 0)
        self.assertEqual(image_type, 2, "splash must be an uncompressed true-color TGA")
        self.assertLessEqual(width, 1920)
        self.assertLessEqual(height, 1080)
        self.assertEqual(depth, 24)

        pixel_bytes = width * height * 3
        pixels = payload[18 + id_length : 18 + id_length + pixel_bytes]
        self.assertEqual(len(pixels), width * height * 3)
        colors = {pixels[index : index + 3] for index in range(0, len(pixels), 3)}
        self.assertLessEqual(len(colors), 224)

    def test_boot_configuration_uses_supported_raspberry_pi_helper(self):
        script = (
            PROJECT_ROOT / "scripts/configure-pi-boot-branding.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("rpi-splash-screen-support", script)
        self.assertIn('configure-splash "$SPLASH_IMAGE" --no-cmdline', script)
        self.assertIn("/boot/firmware/cmdline.txt", script)
        self.assertIn("/boot/cmdline.txt", script)
        self.assertIn("console=tty1|quiet|splash", script)
        self.assertIn('output+=" loglevel=3', script)
        self.assertIn("! has_cmdline_token 'quiet'", script)
        self.assertIn('echo "[all]"', script)
        self.assertIn('echo "disable_splash=1"', script)
        self.assertIn("update-initramfs -k all -u", script)
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
