"""Application update checks and installation handoff.

All git and updater-process execution lives here so web routes only deal in state.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


class UpdateError(RuntimeError):
    """An expected, user-facing update failure."""


class ApplicationUpdater:
    def __init__(self, project_root: Path, check_interval_seconds: int = 300):
        self.project_root = project_root.resolve()
        self.check_interval_seconds = check_interval_seconds
        self.script_path = self.project_root / "scripts" / "update-app.sh"
        self.log_path = self.project_root / ".update.log"
        self.phase_path = self.project_root / ".update-status"
        self._lock = asyncio.Lock()
        self._install_lock = asyncio.Lock()
        self._background_task: asyncio.Task | None = None
        self._install_process: subprocess.Popen | None = None
        self._last_warning_at: datetime | None = None
        self._state: dict[str, Any] = {
            "current_commit": None,
            "latest_commit": None,
            "current": None,
            "latest": None,
            "update_available": False,
            "last_checked_at": None,
            "checking": False,
            "installing": False,
            "install_phase": "idle",
            "error": None,
        }
        self._restore_install_state()

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

    async def _run_git(self, *args: str, timeout: int = 30, check: bool = True) -> str:
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
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise UpdateError(detail or f"git {' '.join(args)} failed")
        return result.stdout.strip()

    async def _commit_details(self, ref: str) -> dict[str, str]:
        value = await self._run_git(
            "show",
            "-s",
            "--format=%H%x00%h%x00%cI%x00%s",
            ref,
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
                current = await self._commit_details("HEAD")
                self._state.update(current_commit=current["commit"], current=current)
                await self._run_git("fetch", "--quiet", "origin", "main", timeout=90)
                latest = await self._commit_details("origin/main")
                ancestor = await self._is_ancestor("HEAD", "origin/main")
                update_available = current["commit"] != latest["commit"] and ancestor
                error = None
                if current["commit"] != latest["commit"] and not ancestor:
                    error = "Local main has diverged from origin/main; automatic update is disabled."
                self._state.update(
                    current_commit=current["commit"],
                    latest_commit=latest["commit"],
                    current=current,
                    latest=latest,
                    update_available=update_available,
                    last_checked_at=datetime.now(timezone.utc).isoformat(),
                    error=error,
                )
                if self._state["install_phase"] == "restarting" and not update_available:
                    self._clear_completed_install()
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

    async def _is_ancestor(self, older: str, newer: str) -> bool:
        def run() -> int:
            return subprocess.run(
                ["git", "merge-base", "--is-ancestor", older, newer],
                cwd=self.project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            ).returncode

        try:
            return await asyncio.to_thread(run) == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"Could not compare local and remote commits: {exc}") from exc

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
            if not state["update_available"]:
                raise UpdateError("No application update is available.")

            branch = await self._run_git("branch", "--show-current")
            if branch != "main":
                raise UpdateError(f"Updates require the main branch; currently on {branch or 'detached HEAD'}.")
            dirty = await self._run_git("status", "--porcelain", "--untracked-files=no")
            if dirty:
                raise UpdateError("Tracked local changes are present. Commit or restore them before updating.")
            if not self.script_path.is_file():
                raise UpdateError("The application update script is missing.")

            try:
                log_file = self.log_path.open("a", encoding="utf-8")
                self._install_process = subprocess.Popen(
                    ["bash", str(self.script_path), str(self.project_root)],
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

            self._state.update(
                installing=True,
                install_phase="preparing",
                error=None,
            )
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

    def _clear_completed_install(self) -> None:
        self._state.update(installing=False, install_phase="complete", error=None)
        try:
            self.phase_path.unlink(missing_ok=True)
        except OSError:
            pass

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
