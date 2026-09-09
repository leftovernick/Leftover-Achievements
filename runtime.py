"""Centralized deployment mode, resource, data, and process helpers."""

from __future__ import annotations

import os
import platform
import socket
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO


APP_NAME = "LeftoverAchievements"
DEFAULT_PORT = 8000
GITHUB_REPOSITORY = "leftovernick/Leftover-Achievements"


class RuntimeMode(str, Enum):
    DEVELOPMENT = "development"
    RASPBERRY_PI = "raspberry_pi"
    MACOS_PACKAGED = "macos_packaged"
    WINDOWS_PACKAGED = "windows_packaged"


class AlreadyRunningError(RuntimeError):
    """Raised when another packaged server process owns the instance lock."""


class SingleInstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a+b")
        try:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                if lock_file.read(1) == b"":
                    lock_file.write(b"0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            lock_file.close()
            raise AlreadyRunningError("LeftoverAchievements is already running.") from exc
        self._file = lock_file

    def release(self) -> None:
        if not self._file:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> "SingleInstanceLock":
        self.acquire()
        return self

    def __exit__(self, *_args) -> None:
        self.release()


@dataclass(frozen=True)
class RuntimeEnvironment:
    mode: RuntimeMode
    resource_root: Path
    data_dir: Path
    logs_dir: Path
    mutable_audio_dir: Path
    installed_version: str | None
    architecture: str
    github_repository: str = GITHUB_REPOSITORY
    port: int = DEFAULT_PORT

    @property
    def is_packaged(self) -> bool:
        return self.mode in {RuntimeMode.MACOS_PACKAGED, RuntimeMode.WINDOWS_PACKAGED}

    @property
    def is_pi_appliance(self) -> bool:
        return self.mode is RuntimeMode.RASPBERRY_PI

    @property
    def should_launch_kiosk(self) -> bool:
        return self.is_pi_appliance

    @property
    def supports_self_update(self) -> bool:
        return self.is_pi_appliance

    @property
    def database_path(self) -> Path:
        if self.is_packaged:
            return self.data_dir / "leftover.db"
        configured = os.getenv("LEFTOVER_ACHIEVEMENTS_DB_PATH")
        if configured:
            candidate = Path(configured).expanduser()
            return candidate if candidate.is_absolute() else self.resource_root / candidate
        return self.resource_root / "database" / "leftover.db"

    @property
    def update_log_path(self) -> Path:
        return self.logs_dir / "update.log" if self.is_packaged else self.resource_root / ".update.log"

    @property
    def update_status_path(self) -> Path:
        return self.data_dir / "update-status" if self.is_packaged else self.resource_root / ".update-status"

    @property
    def instance_lock_path(self) -> Path:
        return self.data_dir / "server.lock"

    def resource_path(self, *parts: str) -> Path:
        return self.resource_root.joinpath(*parts)

    def ensure_runtime_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.is_packaged:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.mutable_audio_dir.mkdir(parents=True, exist_ok=True)

    def instance_lock(self) -> SingleInstanceLock:
        return SingleInstanceLock(self.instance_lock_path)

    def release_asset_name(self, version: str) -> str | None:
        if self.mode is RuntimeMode.MACOS_PACKAGED:
            if self.architecture not in {"arm64", "x64"}:
                return None
            return f"{APP_NAME}-macOS-{self.architecture}-{version}.zip"
        if self.mode is RuntimeMode.WINDOWS_PACKAGED:
            return f"{APP_NAME}-Windows-x64-{version}.zip"
        return None


def _is_raspberry_pi() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        model = Path("/proc/device-tree/model").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "raspberry pi" in model.lower()


def _resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


def _runtime_mode() -> RuntimeMode:
    override = os.getenv("LEFTOVER_RUNTIME_MODE")
    if override:
        try:
            return RuntimeMode(override)
        except ValueError as exc:
            choices = ", ".join(mode.value for mode in RuntimeMode)
            raise RuntimeError(f"Invalid LEFTOVER_RUNTIME_MODE; expected one of: {choices}") from exc
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return RuntimeMode.MACOS_PACKAGED
        if sys.platform == "win32":
            return RuntimeMode.WINDOWS_PACKAGED
    if _is_raspberry_pi():
        return RuntimeMode.RASPBERRY_PI
    return RuntimeMode.DEVELOPMENT


def _data_directory(mode: RuntimeMode, resource_root: Path) -> Path:
    override = os.getenv("LEFTOVER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if mode is RuntimeMode.MACOS_PACKAGED:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if mode is RuntimeMode.WINDOWS_PACKAGED:
        local_app_data = os.getenv("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        return base / APP_NAME
    return resource_root


def _packaged_version(resource_root: Path, mode: RuntimeMode) -> str | None:
    if mode not in {RuntimeMode.MACOS_PACKAGED, RuntimeMode.WINDOWS_PACKAGED}:
        return None
    try:
        value = (resource_root / "build-version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def normalize_architecture(machine: str) -> str:
    normalized = machine.strip().lower()
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    if normalized in {"x64", "x86_64", "amd64"}:
        return "x64"
    return normalized or "unknown"


def _runtime_architecture(resource_root: Path, mode: RuntimeMode) -> str:
    if mode in {RuntimeMode.MACOS_PACKAGED, RuntimeMode.WINDOWS_PACKAGED}:
        try:
            embedded = (resource_root / "build-architecture.txt").read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            embedded = ""
        if embedded:
            return normalize_architecture(embedded)
    return normalize_architecture(platform.machine())


def detect_lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return address if address and not address.startswith("127.") else None


def local_port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def detect_runtime() -> RuntimeEnvironment:
    mode = _runtime_mode()
    resources = _resource_root()
    data = _data_directory(mode, resources)
    mutable_audio = data / "audio" if mode in {
        RuntimeMode.MACOS_PACKAGED,
        RuntimeMode.WINDOWS_PACKAGED,
    } else resources / "static" / "audio"
    try:
        port = int(os.getenv("LEFTOVER_PORT", str(DEFAULT_PORT)))
    except ValueError as exc:
        raise RuntimeError("LEFTOVER_PORT must be an integer.") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("LEFTOVER_PORT must be between 1 and 65535.")
    return RuntimeEnvironment(
        mode=mode,
        resource_root=resources,
        data_dir=data,
        logs_dir=data / "logs",
        mutable_audio_dir=mutable_audio,
        installed_version=_packaged_version(resources, mode),
        architecture=_runtime_architecture(resources, mode),
        port=port,
    )


runtime = detect_runtime()
