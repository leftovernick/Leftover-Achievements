import tempfile
import unittest
from pathlib import Path

from services.updater import ApplicationUpdater, UpdateError
from runtime import RuntimeEnvironment, RuntimeMode


def release(tag: str, *, prerelease: bool = False, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "name": f"Release {tag}",
        "html_url": f"https://github.com/example/project/releases/tag/{tag}",
        "published_at": "2026-09-09T12:00:00Z",
        "body": "Release notes",
        "prerelease": prerelease,
        "draft": draft,
    }


class SimulatedUpdater(ApplicationUpdater):
    def __init__(self, project_root: Path, installed: str | None, payload: dict | None):
        async def fetch_release(_repository: str):
            return payload

        super().__init__(
            project_root,
            repository="example/project",
            release_fetcher=fetch_release,
        )
        self.simulated_installed = installed

    async def _commit_details(self, _ref: str) -> dict[str, str]:
        return {
            "commit": "a" * 40,
            "short_commit": "aaaaaaa",
            "committed_at": "2026-09-09T12:00:00Z",
            "message": "Development on main does not affect releases",
        }

    async def _installed_version(self) -> str | None:
        return self.simulated_installed


class ReleaseUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_same_release_is_up_to_date_even_when_main_commit_is_newer(self):
        state = await SimulatedUpdater(self.root, "v1.1.0", release("v1.1.0")).check()
        self.assertFalse(state["update_available"])

    async def test_newer_release_is_available(self):
        state = await SimulatedUpdater(self.root, "v1.1.0", release("v1.2.0")).check()
        self.assertTrue(state["update_available"])
        self.assertEqual(state["latest_version"], "v1.2.0")

    async def test_semantic_comparison_does_not_use_lexicographic_order(self):
        state = await SimulatedUpdater(self.root, "v1.10.0", release("v1.9.0")).check()
        self.assertFalse(state["update_available"])

    async def test_untagged_build_can_install_latest_stable_release(self):
        state = await SimulatedUpdater(self.root, None, release("v1.2.0")).check()
        self.assertEqual(state["installed_build"], "development")
        self.assertTrue(state["update_available"])

    async def test_prerelease_is_ignored(self):
        state = await SimulatedUpdater(
            self.root,
            "v1.1.0",
            release("v1.2.0-beta.1", prerelease=True),
        ).check()
        self.assertFalse(state["update_available"])
        self.assertIsNone(state["latest_version"])

    async def test_dirty_tracked_tree_blocks_install(self):
        updater = SimulatedUpdater(self.root, "v1.1.0", release("v1.2.0"))

        async def dirty_git(*args: str, **_kwargs) -> str:
            if args[:2] == ("status", "--porcelain"):
                return " M app.py"
            return ""

        updater._run_git = dirty_git
        with self.assertRaisesRegex(UpdateError, "Tracked local changes"):
            await updater.install()

    async def test_packaged_build_uses_embedded_version_and_disables_self_install(self):
        data = self.root / "data"
        environment = RuntimeEnvironment(
            mode=RuntimeMode.MACOS_PACKAGED,
            resource_root=self.root,
            data_dir=data,
            logs_dir=data / "logs",
            mutable_audio_dir=data / "audio",
            installed_version="v1.1.0",
        )

        async def fetch_release(_repository: str):
            payload = release("v1.2.0")
            payload["assets"] = [
                {
                    "name": "LeftoverAchievements-macOS-arm64-v1.2.0.zip",
                    "browser_download_url": "https://github.com/example/project/releases/download/v1.2.0/package.zip",
                }
            ]
            return payload

        updater = ApplicationUpdater(
            self.root,
            repository="example/project",
            release_fetcher=fetch_release,
            runtime_environment=environment,
        )
        state = await updater.check()
        self.assertTrue(state["update_available"])
        self.assertFalse(state["install_supported"])
        self.assertEqual(state["installed_version"], "v1.1.0")
        self.assertEqual(
            state["latest_release_asset_name"],
            "LeftoverAchievements-macOS-arm64-v1.2.0.zip",
        )
        with self.assertRaisesRegex(UpdateError, "not yet supported"):
            await updater.install()


if __name__ == "__main__":
    unittest.main()
