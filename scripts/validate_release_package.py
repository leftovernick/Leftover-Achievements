#!/usr/bin/env python3
"""Validate desktop ZIPs and Raspberry Pi TAR.GZ release packages."""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

from packaging.version import InvalidVersion, Version
try:
    from scripts.pi_package import validate_pi_archive
except ModuleNotFoundError:  # Direct execution sets sys.path to scripts/.
    from pi_package import validate_pi_archive


VERSION_PATTERN = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[.+-][0-9A-Za-z.-]+)?$")
FORBIDDEN_NAMES = {
    ".env",
    ".git-credentials",
    ".update.log",
    ".update-status",
    "leftover-achievements.log",
    "leftover.db",
    "server.lock",
}


def stable_version(value: str) -> Version:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"Unsupported release version: {value!r}")
    normalized = value[1:] if value.lower().startswith("v") else value
    try:
        version = Version(normalized)
    except InvalidVersion as exc:
        raise ValueError(f"Unsupported release version: {value!r}") from exc
    if version.is_prerelease or version.is_devrelease:
        raise ValueError(f"Packaged releases must use a stable version: {value!r}")
    return version


def expected_artifact_name(
    platform: str, version: str, architecture: str | None = None
) -> str:
    if platform == "macos":
        if architecture not in {"arm64", "x64"}:
            raise ValueError("macOS release packages require architecture arm64 or x64")
        platform_architecture = f"macOS-{architecture}"
    elif platform == "windows":
        if architecture not in {None, "x64"}:
            raise ValueError("Windows release packages currently require architecture x64")
        platform_architecture = "Windows-x64"
    else:
        if architecture != "arm64":
            raise ValueError("Raspberry Pi release packages require architecture arm64")
        platform_architecture = "Pi-arm64"
    return f"LeftoverAchievements-{platform_architecture}-{version}"


def validate_archive(
    platform: str,
    version: str,
    archive: Path,
    architecture: str | None = None,
) -> None:
    stable_version(version)
    if platform == "pi":
        validate_pi_archive(archive, version)
        return
    artifact_name = expected_artifact_name(platform, version, architecture)
    expected_archive = f"{artifact_name}.zip"
    if archive.name != expected_archive:
        raise ValueError(f"Expected archive name {expected_archive!r}, got {archive.name!r}")
    if not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError(f"Release archive is missing or empty: {archive}")

    expected_root = f"{artifact_name}.app" if platform == "macos" else artifact_name
    with zipfile.ZipFile(archive) as package:
        names = [PurePosixPath(info.filename) for info in package.infolist()]
        allowed_roots = {expected_root, "__MACOSX"} if platform == "macos" else {expected_root}
        if not names or any(not name.parts or name.parts[0] not in allowed_roots for name in names):
            raise ValueError(f"Archive must contain only the expected root {expected_root!r}")

        forbidden = []
        for name in names:
            lowered_parts = [part.lower() for part in name.parts]
            basename = lowered_parts[-1]
            if ".git" in lowered_parts or basename in FORBIDDEN_NAMES:
                forbidden.append(str(name))
            elif basename.endswith((".db", ".sqlite", ".sqlite3")):
                forbidden.append(str(name))
        if forbidden:
            raise ValueError(f"Runtime or secret-bearing files found in archive: {forbidden}")

        metadata = (
            PurePosixPath(expected_root, "Contents", "Resources", "build-version.txt")
            if platform == "macos"
            else PurePosixPath(expected_root, "_internal", "build-version.txt")
        )
        if metadata not in names:
            raise ValueError(f"Archive does not contain embedded metadata at {metadata}")
        embedded_version = package.read(str(metadata)).decode("utf-8").strip()
        if embedded_version != version:
            raise ValueError(
                f"Embedded version mismatch: expected {version!r}, got {embedded_version!r}"
            )

        if platform == "macos":
            architecture_metadata = PurePosixPath(
                expected_root, "Contents", "Resources", "build-architecture.txt"
            )
            if architecture_metadata not in names:
                raise ValueError(
                    f"Archive does not contain architecture metadata at {architecture_metadata}"
                )
            embedded_architecture = (
                package.read(str(architecture_metadata)).decode("utf-8").strip()
            )
            if embedded_architecture != architecture:
                raise ValueError(
                    "Embedded architecture mismatch: "
                    f"expected {architecture!r}, got {embedded_architecture!r}"
                )

        if platform == "macos":
            executable_suffix = f"Contents/MacOS/{artifact_name}"
        else:
            executable_suffix = f"{artifact_name}.exe"
        if not any(str(name).endswith(executable_suffix) for name in names):
            raise ValueError(f"Archive does not contain expected executable {executable_suffix!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("macos", "windows", "pi"), required=True)
    parser.add_argument("--architecture", choices=("arm64", "x64"))
    parser.add_argument("--version", required=True)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        validate_archive(args.platform, args.version, args.archive, args.architecture)
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"Release package validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
