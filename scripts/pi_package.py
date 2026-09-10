#!/usr/bin/env python3
"""Validate, stage, activate, and migrate Raspberry Pi release bundles."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

VERSION_PATTERN = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+$")
REQUIRED_PATHS = {
    "app.py",
    "launcher.py",
    "runtime.py",
    "requirements.txt",
    "build-version.txt",
    "build-architecture.txt",
    "database/database.py",
    "services/updater.py",
    "templates/display.html",
    "static/css/styles.css",
    "static/js/display.js",
    "scripts/update-app.sh",
    "scripts/start-backend.sh",
    "scripts/start-kiosk.sh",
    "scripts/configure-pi-appliance-session.sh",
    "scripts/configure-pi-boot-branding.sh",
    "scripts/pi-privileged-helper.sh",
}
FORBIDDEN_PARTS = {
    ".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "__pycache__", "tests", "build", "dist", "node_modules",
}
FORBIDDEN_NAMES = {
    ".env",
    ".update.log",
    ".update-status",
    "leftover-achievements.log",
    "leftover.db",
    "server.lock",
    ".ds_store",
    ".coverage",
}
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def stable_version(value: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"Unsupported release version: {value!r}")
    return value


def artifact_name(version: str) -> str:
    stable_version(version)
    return f"LeftoverAchievements-Pi-arm64-{version}"


def select_release_asset(release: dict) -> tuple[str, str, str]:
    version = stable_version(str(release.get("tag_name", "")))
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("The latest release is not a published stable release")
    expected = f"{artifact_name(version)}.tar.gz"
    matches = [asset for asset in release.get("assets", []) if asset.get("name") == expected]
    if len(matches) != 1:
        raise ValueError(f"Release does not contain exactly one {expected} asset")
    url = matches[0].get("browser_download_url", "")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise ValueError("Raspberry Pi release asset URL is invalid")
    return version, expected, url


def _relative_member(name: str, expected_root: str) -> PurePosixPath | None:
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or path.parts[0] != expected_root:
        raise ValueError(f"Archive member is outside {expected_root}: {name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Archive contains an unsafe path: {name}")
    relative = PurePosixPath(*path.parts[1:])
    return relative if relative.parts else None


def validate_pi_archive(archive: Path, version: str) -> None:
    expected_root = artifact_name(version)
    expected_filename = f"{expected_root}.tar.gz"
    if archive.name != expected_filename:
        raise ValueError(f"Expected archive name {expected_filename!r}, got {archive.name!r}")
    if not archive.is_file() or archive.stat().st_size == 0:
        raise ValueError(f"Release archive is missing or empty: {archive}")

    found: set[str] = set()
    metadata: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as package:
        members = package.getmembers()
        if not members:
            raise ValueError("Raspberry Pi release archive is empty")
        total_size = 0
        for member in members:
            relative = _relative_member(member.name, expected_root)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"Archive contains unsupported member type: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise ValueError(f"Archive contains unsupported member: {member.name}")
            total_size += member.size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("Raspberry Pi package exceeds the extraction size limit")
            if relative is None:
                continue
            lowered = tuple(part.lower() for part in relative.parts)
            basename = lowered[-1]
            if any(part in FORBIDDEN_PARTS for part in lowered):
                raise ValueError(f"Development/runtime path found in archive: {member.name}")
            if basename in FORBIDDEN_NAMES or basename.startswith("custom-") or basename.endswith((".db", ".sqlite", ".sqlite3", ".log", ".pyc")):
                raise ValueError(f"Mutable or secret-bearing file found in archive: {member.name}")
            relative_name = str(relative)
            found.add(relative_name)
            if relative_name in {"build-version.txt", "build-architecture.txt"}:
                source = package.extractfile(member)
                metadata[relative_name] = source.read() if source else b""

    missing = sorted(REQUIRED_PATHS - found)
    if missing:
        raise ValueError(f"Raspberry Pi package is missing required files: {missing}")
    if metadata.get("build-version.txt", b"").decode("utf-8").strip() != version:
        raise ValueError("Embedded Raspberry Pi version does not match the release tag")
    if metadata.get("build-architecture.txt", b"").decode("utf-8").strip() != "arm64":
        raise ValueError("Raspberry Pi package architecture must be arm64")


def _extract_validated(archive: Path, version: str, destination: Path) -> None:
    expected_root = artifact_name(version)
    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            relative = _relative_member(member.name, expected_root)
            if relative is None:
                continue
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = package.extractfile(member)
            if source is None:
                raise ValueError(f"Could not read archive member: {member.name}")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)


def stage_release(
    archive: Path,
    version: str,
    install_root: Path,
    *,
    python_executable: str = sys.executable,
    install_dependencies: bool = True,
) -> Path:
    validate_pi_archive(archive, version)
    releases = install_root / "app" / "releases"
    destination = releases / version
    marker = destination / ".install-complete"
    if marker.is_file():
        return destination
    releases.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=releases))
    try:
        _extract_validated(archive, version, staging)
        if install_dependencies:
            subprocess.run([python_executable, "-m", "venv", str(staging / ".venv")], check=True)
            subprocess.run(
                [str(staging / ".venv" / "bin" / "python"), "-m", "pip", "install", "-r", str(staging / "requirements.txt")],
                check=True,
            )
        marker_in_stage = staging / ".install-complete"
        marker_in_stage.write_text(f"{version}\n", encoding="utf-8")
        if destination.exists():
            raise ValueError(f"Incomplete release directory already exists: {destination}")
        staging.rename(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def activate_release(install_root: Path, version: str) -> Path | None:
    stable_version(version)
    app_root = install_root / "app"
    release = app_root / "releases" / version
    if not (release / ".install-complete").is_file():
        raise ValueError(f"Release is not completely staged: {version}")
    current = app_root / "current"
    previous = current.resolve() if current.is_symlink() else None
    temporary = app_root / f".current-{os.getpid()}"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(Path("releases") / version)
    temporary.replace(current)
    return previous


def migrate_legacy_data(legacy_root: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    env_source = legacy_root / ".env"
    env_target = data_dir / ".env"
    if env_source.is_file() and not env_target.exists():
        shutil.copy2(env_source, env_target)
    database_sources = []
    if env_source.is_file():
        for line in env_source.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.startswith("LEFTOVER_ACHIEVEMENTS_DB_PATH="):
                continue
            configured = line.split("=", 1)[1].strip().strip("\"'")
            if configured:
                configured_path = Path(configured).expanduser()
                database_sources.append(
                    configured_path if configured_path.is_absolute() else legacy_root / configured_path
                )
            break
    database_sources.extend([
        legacy_root / "database" / "leftover.db",
        legacy_root / "leftover.db",
    ])
    database_target = data_dir / "leftover.db"
    database_copied = False
    if not database_target.exists():
        for source in database_sources:
            if source.is_file():
                shutil.copy2(source, database_target)
                database_copied = True
                break
    if database_copied and env_source.is_file():
        api_key = ""
        for line in env_source.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("RA_API_KEY="):
                api_key = line.split("=", 1)[1].strip().strip("\"'")
                break
        if api_key:
            with sqlite3.connect(database_target) as connection:
                table_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'"
                ).fetchone()
                if table_exists:
                    connection.execute(
                        """
                        INSERT INTO app_settings (key, value, updated_at)
                        VALUES ('ra_api_key', ?, datetime('now'))
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                        """,
                        (api_key,),
                    )
    audio_target = data_dir / "audio"
    audio_target.mkdir(exist_ok=True)
    for source in (legacy_root / "static" / "audio").glob("custom-*"):
        target = audio_target / source.name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)
    for source, target in (
        (legacy_root / ".update.log", data_dir / "logs" / "update.log"),
        (legacy_root / ".update-status", data_dir / "update-status"),
    ):
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("archive", type=Path)
    validate.add_argument("version")
    stage = subparsers.add_parser("stage")
    stage.add_argument("archive", type=Path)
    stage.add_argument("version")
    stage.add_argument("install_root", type=Path)
    activate = subparsers.add_parser("activate")
    activate.add_argument("install_root", type=Path)
    activate.add_argument("version")
    migrate = subparsers.add_parser("migrate-data")
    migrate.add_argument("legacy_root", type=Path)
    migrate.add_argument("data_dir", type=Path)
    select = subparsers.add_parser("select")
    select.add_argument("release_json", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        validate_pi_archive(args.archive, args.version)
    elif args.command == "stage":
        stage_release(args.archive, args.version, args.install_root)
    elif args.command == "activate":
        activate_release(args.install_root, args.version)
    elif args.command == "migrate-data":
        migrate_legacy_data(args.legacy_root, args.data_dir)
    else:
        with args.release_json.open(encoding="utf-8") as source:
            selected = select_release_asset(json.load(source))
        print("\n".join(selected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
