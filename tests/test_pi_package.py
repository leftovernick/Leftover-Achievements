import io
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.pi_package import (
    REQUIRED_PATHS,
    activate_release,
    artifact_name,
    migrate_legacy_data,
    select_release_asset,
    stage_release,
    validate_pi_archive,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_archive(directory: Path, version: str, extra: dict[str, bytes] | None = None) -> Path:
    root = artifact_name(version)
    archive = directory / f"{root}.tar.gz"
    files = {name: b"runtime\n" for name in REQUIRED_PATHS}
    files["build-version.txt"] = f"{version}\n".encode()
    files["build-architecture.txt"] = b"arm64\n"
    files.update(extra or {})
    with tarfile.open(archive, "w:gz") as package:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(payload)
            info.mode = 0o755 if name.startswith("scripts/") else 0o644
            package.addfile(info, io.BytesIO(payload))
    return archive


class RaspberryPiPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_asset_selection_is_pi_arm64_only(self):
        version = "v1.2.0"
        expected = "LeftoverAchievements-Pi-arm64-v1.2.0.tar.gz"
        selected = select_release_asset({
            "tag_name": version,
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": "LeftoverAchievements-macOS-arm64-v1.2.0.zip", "browser_download_url": "https://github.com/example/mac"},
                {"name": expected, "browser_download_url": "https://github.com/example/pi"},
            ],
        })
        self.assertEqual(selected, (version, expected, "https://github.com/example/pi"))

    def test_archive_version_and_exclusions(self):
        archive = make_archive(self.root, "v1.2.0")
        validate_pi_archive(archive, "v1.2.0")
        mismatched = make_archive(
            self.root, "v1.2.2", {"build-version.txt": b"v1.2.1\n"}
        )
        with self.assertRaisesRegex(ValueError, "Embedded Raspberry Pi version"):
            validate_pi_archive(mismatched, "v1.2.2")
        forbidden = make_archive(self.root, "v1.2.1", {".env": b"secret"})
        with self.assertRaisesRegex(ValueError, "secret-bearing"):
            validate_pi_archive(forbidden, "v1.2.1")

    def test_staged_install_and_atomic_activation(self):
        archive = make_archive(self.root, "v1.2.0")
        install_root = self.root / "install"
        release = stage_release(archive, "v1.2.0", install_root, install_dependencies=False)
        self.assertFalse((install_root / "app/current").exists())
        activate_release(install_root, "v1.2.0")
        self.assertEqual((install_root / "app/current").resolve(), release.resolve())

    def test_failed_install_leaves_current_release_active(self):
        install_root = self.root / "install"
        first = make_archive(self.root, "v1.2.0")
        stage_release(first, "v1.2.0", install_root, install_dependencies=False)
        activate_release(install_root, "v1.2.0")
        current_before = (install_root / "app/current").resolve()
        broken = make_archive(self.root, "v1.2.1", {".git/config": b"bad"})
        with self.assertRaises(ValueError):
            stage_release(broken, "v1.2.1", install_root, install_dependencies=False)
        self.assertEqual((install_root / "app/current").resolve(), current_before)

    def test_git_layout_migration_preserves_data_and_custom_audio(self):
        legacy = self.root / "Leftover-Achievements"
        data = self.root / "data"
        (legacy / "database").mkdir(parents=True)
        (legacy / "static/audio").mkdir(parents=True)
        (legacy / ".env").write_text("RA_API_KEY=secret\n", encoding="utf-8")
        with sqlite3.connect(legacy / "database/leftover.db") as connection:
            connection.execute(
                "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
        (legacy / "static/audio/custom-mastery.mp3").write_bytes(b"audio")
        migrate_legacy_data(legacy, data)
        self.assertEqual((data / ".env").read_text(), "RA_API_KEY=secret\n")
        with sqlite3.connect(data / "leftover.db") as connection:
            key = connection.execute(
                "SELECT value FROM app_settings WHERE key='ra_api_key'"
            ).fetchone()[0]
        self.assertEqual(key, "secret")
        self.assertEqual((data / "audio/custom-mastery.mp3").read_bytes(), b"audio")

        with sqlite3.connect(data / "leftover.db") as connection:
            connection.execute(
                "UPDATE app_settings SET value='new-key' WHERE key='ra_api_key'"
            )
        migrate_legacy_data(legacy, data)
        with sqlite3.connect(data / "leftover.db") as connection:
            preserved = connection.execute(
                "SELECT value FROM app_settings WHERE key='ra_api_key'"
            ).fetchone()[0]
        self.assertEqual(preserved, "new-key")

    def test_privileged_helper_and_updater_are_narrow_and_git_free(self):
        helper = (PROJECT_ROOT / "scripts/pi-privileged-helper.sh").read_text()
        updater = (PROJECT_ROOT / "scripts/update-app.sh").read_text()
        self.assertIn("Allowed actions: install USER, apply", helper)
        self.assertIn("current release resolves outside", helper)
        self.assertIn("WorkingDirectory=$CURRENT", helper)
        self.assertIn("$CURRENT/scripts/run-kiosk-session.sh", helper)
        self.assertIn("user-session=leftover-achievements", helper)
        self.assertIn("LEFTOVER_DATA_DIR=$DATA_DIR", helper)
        self.assertNotIn("eval ", helper)
        self.assertNotIn("git fetch", updater)
        self.assertNotIn("git checkout", updater)
        self.assertNotIn("git pull", updater)


if __name__ == "__main__":
    unittest.main()
