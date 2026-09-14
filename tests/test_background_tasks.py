import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import app as application
from services.background_tasks import create_logged_task, _tasks


class BackgroundTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_is_retrieved_and_logged_with_task_name_and_traceback(self):
        async def fail():
            raise RuntimeError("test failure")

        with patch("services.background_tasks.logger") as logger:
            task = create_logged_task(fail(), "weekly refresh")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertTrue(task.done())
        self.assertNotIn(task, _tasks)
        self.assertFalse(task._log_traceback)
        logger.error.assert_called_once()
        self.assertEqual(logger.error.call_args.args[1], "weekly refresh")
        self.assertIs(logger.error.call_args.kwargs["exc_info"][0], RuntimeError)

    async def test_cancellation_is_not_logged_as_failure(self):
        with patch("services.background_tasks.logger") as logger:
            task = create_logged_task(asyncio.sleep(60), "cancelled refresh")
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertNotIn(task, _tasks)
        logger.error.assert_not_called()

    async def test_achievement_timeout_still_allows_award_polling(self):
        with (
            patch.object(application.db, "next_tracked_user_to_poll", return_value={"ra_username": "Player"}),
            patch.object(application.db, "mark_tracked_user_polled"),
            patch.object(application, "fetch_recent_hardcore_achievements", new=AsyncMock(side_effect=TimeoutError)),
            patch.object(application, "process_game_awards_for_user", new=AsyncMock()) as awards,
            patch.object(application, "logger") as logger,
        ):
            await application.poll_for_new_achievements()
        awards.assert_awaited_once_with("Player")
        self.assertEqual(logger.warning.call_args.args[2], "TimeoutError")

    async def test_current_activity_timeout_preserves_cache(self):
        with (
            patch.object(application.db, "get_currently_playing_cache", return_value={}),
            patch.object(application.db, "save_currently_playing") as save,
            patch.object(application.ra_client, "currently_playing", new=AsyncMock(side_effect=TimeoutError)),
            patch.object(application, "logger"),
        ):
            self.assertFalse(await application.refresh_current_activity_for_user({"ra_username": "Player"}))
        save.assert_not_called()
