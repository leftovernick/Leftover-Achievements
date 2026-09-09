#!/usr/bin/env python3
"""Validate a packaged release ZIP before it is published."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

from packaging.version import InvalidVersion, Version


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


def expected_artifact_name(platform: str, version: str) -> str:
    architecture = "macOS-arm64" if platform == "macos" else "Windows-x64"
    return f"LeftoverAchievements-{architecture}-{version}"


def validate_archive(platform: str, version: str, archive: Path) -> None:
    stable_version(version)
    artifact_name = expected_artifact_name(platform, version)
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
            executable_suffix = f"Contents/MacOS/{artifact_name}"
        else:
            executable_suffix = f"{artifact_name}.exe"
        if not any(str(name).endswith(executable_suffix) for name in names):
            raise ValueError(f"Archive does not contain expected executable {executable_suffix!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    try:
        validate_archive(args.platform, args.version, args.archive)
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Release package validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
