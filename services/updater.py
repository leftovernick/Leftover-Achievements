"""Stable GitHub Release checks and application update handoff.

All network, version, git, and updater-process logic lives here so routes only
expose cached state and trigger explicit user actions.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable
from urllib.parse import urlparse

import aiohttp
import certifi
from packaging.version import InvalidVersion, Version


logger = logging.getLogger(__name__)
ReleaseFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
if TYPE_CHECKING:
    from runtime import RuntimeEnvironment


class UpdateError(RuntimeError):
    """An expected, user-facing update failure."""


class ApplicationUpdater:
    VERSION_TAG_PATTERN = re.compile(
        r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[.+-][0-9A-Za-z.-]+)?$"
    )

    def __init__(
        self,
        project_root: Path,
        check_interval_seconds: int = 300,
        repository: str | None = None,
        release_fetcher: ReleaseFetcher | None = None,
        runtime_environment: "RuntimeEnvironment | None" = None,
    ):
        self.project_root = project_root.resolve()
        self.runtime = runtime_environment
        self.check_interval_seconds = check_interval_seconds
        self.repository = repository
        self.release_fetcher = release_fetcher or self._fetch_latest_release
        self.script_path = self.project_root / "scripts" / "update-app.sh"
        self.log_path = (
            runtime_environment.update_log_path
            if runtime_environment
            else self.project_root / ".update.log"
        )
        self.phase_path = (
            runtime_environment.update_status_path
            if runtime_environment
            else self.project_root / ".update-status"
        )
        self._lock = asyncio.Lock()
        self._install_lock = asyncio.Lock()
        self._background_task: asyncio.Task | None = None
        self._install_process: subprocess.Popen | None = None
        self._last_warning_at: datetime | None = None
        self._state: dict[str, Any] = {
            "installed_version": None,
            "installed_build": "development",
            "latest_version": None,
            "latest_release_tag": None,
            "latest_release_name": None,
            "latest_release_url": None,
            "latest_release_published_at": None,
            "latest_release_notes": None,
            "latest_release_asset_name": None,
            "latest_release_asset_url": None,
            "current_commit": None,
            "current": None,
            "runtime_mode": runtime_environment.mode.value if runtime_environment else "source",
            "install_supported": runtime_environment.supports_self_update if runtime_environment else True,
            "install_unavailable_reason": self._install_unavailable_reason(),
            "update_available": False,
            "last_checked_at": None,
            "checking": False,
            "installing": False,
            "install_phase": "idle",
            "error": None,
        }
        self._restore_install_state()

    @staticmethod
    def parse_stable_version(tag: str | None) -> Version | None:
        if not tag or not isinstance(tag, str):
            return None
        normalized = tag.strip()
        if not ApplicationUpdater.VERSION_TAG_PATTERN.fullmatch(normalized):
            return None
        if normalized.lower().startswith("v"):
            normalized = normalized[1:]
        try:
            version = Version(normalized)
        except InvalidVersion:
            return None
        if version.is_prerelease or version.is_devrelease:
            return None
        return version

    @classmethod
    def release_is_newer(cls, installed: str | None, latest: str | None) -> bool:
        latest_version = cls.parse_stable_version(latest)
        if latest_version is None:
            return False
        installed_version = cls.parse_stable_version(installed)
        return installed_version is None or latest_version > installed_version

    def _restore_install_state(self) -> None:
        try:
            phase = self.phase_path.read_text(encoding="utf-8").strip().splitlines()[0]
        except (OSError, IndexError):
            return
        if phase == "restarting":
            # A new backend process proves that the service restart completed.
            self._state["install_phase"] = "complete"
            try:
                self.phase_path.unlink(missing_ok=True)
            except OSError:
                pass
        elif phase in {"preparing", "installing"}:
            self._state["installing"] = True
            self._state["install_phase"] = phase
        elif phase == "failed":
            self._state["install_phase"] = "failed"
            self._state["error"] = self._install_error()

    async def _run_git(self, *args: str, timeout: int = 30) -> str:
        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", *args],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

        try:
            result = await asyncio.to_thread(run)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"Git command failed: {exc}") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise UpdateError(detail or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    async def _commit_details(self, ref: str) -> dict[str, str]:
        value = await self._run_git(
            "show", "-s", "--format=%H%x00%h%x00%cI%x00%s", ref
        )
        parts = value.split("\0", 3)
        if len(parts) != 4:
            raise UpdateError(f"Could not read commit details for {ref}.")
        commit, short, committed_at, message = parts
        return {
            "commit": commit,
            "short_commit": short,
            "committed_at": committed_at,
            "message": message[:160],
        }

    async def _installed_version(self) -> str | None:
        if self.runtime and self.runtime.is_packaged:
            version = self.runtime.installed_version
            return version if self.parse_stable_version(version) is not None else None
        tags = await self._run_git("tag", "--points-at", "HEAD")
        candidates = []
        for tag in tags.splitlines():
            parsed = self.parse_stable_version(tag)
            if parsed is not None:
                candidates.append((parsed, tag.strip()))
        return max(candidates, default=(None, None), key=lambda item: item[0])[1]

    async def _repository_name(self) -> str:
        if self.repository:
            return self.repository
        if self.runtime and self.runtime.is_packaged:
            self.repository = self.runtime.github_repository
            return self.repository
        remote_url = await self._run_git("remote", "get-url", "origin")
        match = re.match(r"^git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", remote_url)
        if match:
            repository = match.group(1)
        else:
            parsed = urlparse(remote_url)
            if parsed.hostname != "github.com":
                raise UpdateError("The origin remote is not a GitHub repository.")
            repository = parsed.path.strip("/")
            if repository.endswith(".git"):
                repository = repository[:-4]
        if repository.count("/") != 1:
            raise UpdateError("Could not determine the GitHub repository from origin.")
        self.repository = repository
        return repository

    async def _fetch_latest_release(self, repository: str) -> dict[str, Any] | None:
        url = f"https://api.github.com/repos/{repository}/releases/latest"
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LeftoverAchievements-Updater",
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                async with session.get(url, ssl=ssl_context) as response:
                    if response.status == 404:
                        return None
                    if response.status != 200:
                        detail = (await response.text())[:240]
                        raise UpdateError(
                            f"GitHub release check failed ({response.status}): {detail}"
                        )
                    payload = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise UpdateError(f"Could not reach GitHub Releases: {exc}") from exc
        if not isinstance(payload, dict):
            raise UpdateError("GitHub returned an invalid release response.")
        return payload

    @staticmethod
    def _release_notes(body: Any) -> str | None:
        if not isinstance(body, str):
            return None
        summary = " ".join(body.split())
        return summary[:500] or None

    def _install_unavailable_reason(self) -> str | None:
        if not self.runtime or self.runtime.supports_self_update:
            return None
        if self.runtime.is_packaged:
            platform_name = "macOS" if self.runtime.mode.value == "macos_packaged" else "Windows"
            return (
                f"Automatic installation is not yet supported for packaged {platform_name} builds. "
                "Download the matching release asset from GitHub to update manually."
            )
        return "Automatic installation is only supported on Raspberry Pi deployments."

    def _release_asset(self, release: dict[str, Any], version: str) -> tuple[str | None, str | None]:
        if not self.runtime:
            return None, None
        expected_name = self.runtime.release_asset_name(version)
        if not expected_name:
            return None, None
        for asset in release.get("assets") or []:
            if not isinstance(asset, dict) or asset.get("name") != expected_name:
                continue
            url = asset.get("browser_download_url")
            if isinstance(url, str) and url.startswith("https://github.com/"):
                return expected_name, url
        return expected_name, None

    async def status(self) -> dict[str, Any]:
        self._refresh_process_state()
        return dict(self._state)

    async def check(self) -> dict[str, Any]:
        if self._lock.locked():
            return await self.status()
        async with self._lock:
            if self._state["installing"] and self._state["install_phase"] != "restarting":
                return await self.status()
            self._state["checking"] = True
            self._state["error"] = None
            try:
                current = None
                if not (self.runtime and self.runtime.is_packaged):
                    current = await self._commit_details("HEAD")
                installed = await self._installed_version()
                self._state.update(
                    current_commit=current["commit"] if current else None,
                    current=current,
                    installed_version=installed,
                    installed_build=(
                        "release" if installed else
                        "packaged_unversioned" if self.runtime and self.runtime.is_packaged else
                        "development"
                    ),
                )

                repository = await self._repository_name()
                release = await self.release_fetcher(repository)
                if release is None or release.get("draft") or release.get("prerelease"):
                    self._state.update(
                        latest_version=None,
                        latest_release_tag=None,
                        latest_release_name=None,
                        latest_release_url=None,
                        latest_release_published_at=None,
                        latest_release_notes=None,
                        latest_release_asset_name=None,
                        latest_release_asset_url=None,
                        update_available=False,
                        last_checked_at=datetime.now(timezone.utc).isoformat(),
                    )
                else:
                    tag = release.get("tag_name")
                    if self.parse_stable_version(tag) is None:
                        raise UpdateError(
                            "The latest stable GitHub Release does not have a valid version tag."
                        )
                    release_url = release.get("html_url")
                    if not isinstance(release_url, str) or not release_url.startswith(
                        "https://github.com/"
                    ):
                        release_url = None
                    asset_name, asset_url = self._release_asset(release, tag)
                    self._state.update(
                        latest_version=tag,
                        latest_release_tag=tag,
                        latest_release_name=release.get("name") or tag,
                        latest_release_url=release_url,
                        latest_release_published_at=release.get("published_at"),
                        latest_release_notes=self._release_notes(release.get("body")),
                        latest_release_asset_name=asset_name,
                        latest_release_asset_url=asset_url,
                        update_available=self.release_is_newer(installed, tag),
                        last_checked_at=datetime.now(timezone.utc).isoformat(),
                    )
            except UpdateError as exc:
                self._state.update(
                    update_available=False,
                    last_checked_at=datetime.now(timezone.utc).isoformat(),
                    error=str(exc),
                )
                self._warn_check_failure(str(exc))
            finally:
                self._state["checking"] = False
            return dict(self._state)

    def _warn_check_failure(self, message: str) -> None:
        now = datetime.now(timezone.utc)
        if self._last_warning_at and now - self._last_warning_at < timedelta(hours=1):
            return
        logger.warning("Application update check failed: %s", message)
        self._last_warning_at = now

    async def install(self) -> dict[str, Any]:
        async with self._install_lock:
            if self._state["installing"]:
                raise UpdateError("An application update is already running.")

            state = await self.check()
            if state["error"]:
                raise UpdateError(state["error"])
            if not state["update_available"] or not state["latest_release_tag"]:
                raise UpdateError("No newer stable application release is available.")
            if not state["install_supported"]:
                raise UpdateError(
                    state["install_unavailable_reason"]
                    or "Automatic installation is not supported for this deployment."
                )

            dirty = await self._run_git("status", "--porcelain", "--untracked-files=no")
            if dirty:
                raise UpdateError("Tracked local changes are present. Commit or restore them before updating.")
            if not self.script_path.is_file():
                raise UpdateError("The application update script is missing.")

            try:
                log_file = self.log_path.open("a", encoding="utf-8")
                self._install_process = subprocess.Popen(
                    [
                        "bash",
                        str(self.script_path),
                        str(self.project_root),
                        state["latest_release_tag"],
                    ],
                    cwd=self.project_root,
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
                log_file.close()
            except OSError as exc:
                raise UpdateError(f"Could not start the update process: {exc}") from exc

            self._state.update(installing=True, install_phase="preparing", error=None)
            asyncio.create_task(self._watch_install(self._install_process))
            return dict(self._state)

    async def _watch_install(self, process: subprocess.Popen) -> None:
        return_code = await asyncio.to_thread(process.wait)
        if self._install_process is not process:
            return
        self._refresh_process_state()
        if return_code != 0:
            self._state.update(
                installing=False,
                install_phase="failed",
                error=self._install_error(),
            )

    def _refresh_process_state(self) -> None:
        try:
            phase = self.phase_path.read_text(encoding="utf-8").strip().splitlines()[0]
        except (OSError, IndexError):
            phase = self._state["install_phase"]
        if phase in {"preparing", "installing", "restarting", "failed"}:
            self._state["install_phase"] = phase
        if phase == "failed":
            self._state["installing"] = False
            self._state["error"] = self._install_error()
        elif phase in {"preparing", "installing", "restarting"}:
            self._state["installing"] = True

    def _install_error(self) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "Application update failed. Check the service journal for details."
        details = [line.strip() for line in lines if line.strip()][-3:]
        return " ".join(details)[-500:] if details else "Application update failed."

    async def background_loop(self) -> None:
        while True:
            await self.check()
            await asyncio.sleep(self.check_interval_seconds)

    def start(self) -> None:
        if not self._background_task or self._background_task.done():
            self._background_task = asyncio.create_task(self.background_loop())

    async def stop(self) -> None:
        if not self._background_task:
            return
        self._background_task.cancel()
        try:
            await self._background_task
        except asyncio.CancelledError:
            pass
        self._background_task = None
