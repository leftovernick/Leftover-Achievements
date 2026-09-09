import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.validate_release_package import (
    expected_artifact_name,
    stable_version,
    validate_archive,
)


class ReleasePackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_archive(
        self,
        platform: str,
        version: str,
        *,
        architecture: str | None = None,
        embedded_version: str | None = None,
        embedded_architecture: str | None = None,
        extra_file: str | None = None,
    ) -> Path:
        artifact = expected_artifact_name(platform, version, architecture)
        archive = self.root / f"{artifact}.zip"
        package_root = f"{artifact}.app" if platform == "macos" else artifact
        executable = (
            f"{package_root}/Contents/MacOS/{artifact}"
            if platform == "macos"
            else f"{package_root}/{artifact}.exe"
        )
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr(executable, b"executable")
            metadata = (
                f"{package_root}/Contents/Resources/build-version.txt"
                if platform == "macos"
                else f"{package_root}/_internal/build-version.txt"
            )
            package.writestr(metadata, embedded_version or version)
            if platform == "macos":
                package.writestr(
                    f"{package_root}/Contents/Resources/build-architecture.txt",
                    embedded_architecture or architecture or "",
                )
            if extra_file:
                package.writestr(f"{package_root}/{extra_file}", b"private")
        return archive

    def test_accepts_expected_platform_architecture_name_and_version(self):
        for platform, architecture in (
            ("macos", "arm64"),
            ("macos", "x64"),
            ("windows", "x64"),
        ):
            with self.subTest(platform=platform, architecture=architecture):
                validate_archive(
                    platform,
                    "v1.2.0",
                    self.make_archive(platform, "v1.2.0", architecture=architecture),
                    architecture,
                )

    def test_rejects_prerelease_version(self):
        with self.assertRaises(ValueError):
            stable_version("v1.2.0-rc1")

    def test_rejects_mismatched_embedded_version(self):
        archive = self.make_archive(
            "windows", "v1.2.0", architecture="x64", embedded_version="v1.1.0"
        )
        with self.assertRaises(ValueError):
            validate_archive("windows", "v1.2.0", archive, "x64")

    def test_rejects_mismatched_macos_architecture(self):
        archive = self.make_archive(
            "macos",
            "v1.2.0",
            architecture="arm64",
            embedded_architecture="x64",
        )
        with self.assertRaises(ValueError):
            validate_archive("macos", "v1.2.0", archive, "arm64")

    def test_rejects_runtime_or_secret_bearing_files(self):
        for forbidden in (".env", "database/leftover.db", ".git/config", "logs/leftover-achievements.log"):
            with self.subTest(forbidden=forbidden):
                archive = self.make_archive(
                    "macos", "v1.2.0", architecture="arm64", extra_file=forbidden
                )
                with self.assertRaises(ValueError):
                    validate_archive("macos", "v1.2.0", archive, "arm64")


if __name__ == "__main__":
    unittest.main()
