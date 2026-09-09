import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from runtime import AlreadyRunningError, RuntimeEnvironment, RuntimeMode, local_port_in_use


class RuntimeEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def environment(self, mode: RuntimeMode, version: str | None = None) -> RuntimeEnvironment:
        data = self.root / "data"
        return RuntimeEnvironment(
            mode=mode,
            resource_root=self.root / "bundle",
            data_dir=data,
            logs_dir=data / "logs",
            mutable_audio_dir=data / "audio",
            installed_version=version,
        )

    def test_packaged_data_and_resources_are_separate(self):
        environment = self.environment(RuntimeMode.MACOS_PACKAGED, "v1.2.0")
        self.assertEqual(environment.database_path, self.root / "data" / "leftover.db")
        self.assertEqual(environment.resource_path("templates"), self.root / "bundle" / "templates")
        self.assertNotEqual(environment.mutable_audio_dir, environment.resource_root / "static" / "audio")

    def test_release_asset_names_are_platform_specific(self):
        mac = self.environment(RuntimeMode.MACOS_PACKAGED)
        windows = self.environment(RuntimeMode.WINDOWS_PACKAGED)
        self.assertEqual(
            mac.release_asset_name("v1.2.0"),
            "LeftoverAchievements-macOS-arm64-v1.2.0.zip",
        )
        self.assertEqual(
            windows.release_asset_name("v1.2.0"),
            "LeftoverAchievements-Windows-x64-v1.2.0.zip",
        )

    def test_only_pi_mode_supports_self_update_and_kiosk(self):
        pi = self.environment(RuntimeMode.RASPBERRY_PI)
        mac = self.environment(RuntimeMode.MACOS_PACKAGED)
        self.assertTrue(pi.supports_self_update)
        self.assertTrue(pi.should_launch_kiosk)
        self.assertFalse(mac.supports_self_update)
        self.assertFalse(mac.should_launch_kiosk)

    def test_single_instance_lock_rejects_second_owner(self):
        environment = self.environment(RuntimeMode.MACOS_PACKAGED)
        environment.ensure_runtime_directories()
        first = environment.instance_lock()
        second = environment.instance_lock()
        first.acquire()
        try:
            with self.assertRaises(AlreadyRunningError):
                second.acquire()
        finally:
            first.release()

    def test_owned_local_port_is_detected(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        with patch("runtime.socket.create_connection", return_value=connection):
            self.assertTrue(local_port_in_use(8000))


if __name__ == "__main__":
    unittest.main()
