"""Named background tasks with explicit exception reporting."""

import asyncio
import logging


logger = logging.getLogger(__name__)
_tasks = set()


def create_logged_task(coroutine, name: str) -> asyncio.Task:
    task = asyncio.create_task(coroutine, name=name)
    _tasks.add(task)

    def completed(done):
        _tasks.discard(done)
        if done.cancelled():
            return
        error = done.exception()
        if error is not None:
            logger.error(
                "Background task '%s' failed: %s: %s", name, type(error).__name__, error,
                exc_info=(type(error), error, error.__traceback__),
            )

    task.add_done_callback(completed)
    return task
