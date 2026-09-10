import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import uvicorn

import app as application
from launcher import (
    GRACEFUL_SHUTDOWN_SECONDS,
    create_backend_server,
)


PROJECT_ROOT = application.runtime.resource_root


class DisplayEventShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        application.display_shutdown_event = asyncio.Event()
        application.display_event_queues.clear()

    async def asyncTearDown(self):
        application.begin_application_shutdown()
        await asyncio.sleep(0)
        application.display_event_queues.clear()

    async def wait_for_subscriber(self):
        async with asyncio.timeout(1):
            while not application.display_event_queues:
                await asyncio.sleep(0)

    async def test_sse_client_disconnect_cancels_queue_wait(self):
        response = await application.display_events()

        async def receive():
            await self.wait_for_subscriber()
            return {"type": "http.disconnect"}

        async def send(_message):
            return None

        await asyncio.wait_for(
            response(
                {"type": "http", "asgi": {"spec_version": "2.3"}},
                receive,
                send,
            ),
            timeout=0.5,
        )

        self.assertFalse(application.display_event_queues)

    async def test_cancellation_during_queue_wait_is_not_swallowed(self):
        queue = asyncio.Queue()
        stream = application.display_event_stream(queue)
        stream_task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        stream_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await stream_task

    async def test_shutdown_wakes_active_sse_connection(self):
        response = await application.display_events()
        stream_task = asyncio.create_task(anext(response.body_iterator))
        await self.wait_for_subscriber()

        application.begin_application_shutdown()
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(stream_task, timeout=0.5)

        self.assertFalse(application.display_event_queues)

    async def test_event_types_and_payload_delivery_are_preserved(self):
        queue = asyncio.Queue()
        stream = application.display_event_stream(queue)
        for event_type in ("achievement", "beaten", "mastery"):
            await queue.put({"type": event_type, "game_title": "Test Game"})
            payload = await asyncio.wait_for(anext(stream), timeout=0.5)
            self.assertIn(f"event: {event_type}", payload)
            self.assertIn('"game_title": "Test Game"', payload)
        await stream.aclose()

    async def test_settings_refresh_control_event_reaches_connected_display(self):
        queue = asyncio.Queue()
        application.display_event_queues.add(queue)

        application.request_display_refresh()

        event = queue.get_nowait()
        self.assertEqual(event, {"type": "display-refresh", "reason": "settings"})

    async def test_saving_settings_requests_immediate_display_refresh(self):
        with (
            patch.object(application.db, "set_audio_enabled"),
            patch.object(application, "set_notification_seconds"),
            patch.object(application, "set_display_section_seconds"),
            patch.object(application, "request_display_refresh") as refresh,
        ):
            response = await application.update_settings(request=None)

        self.assertEqual(response.status_code, 303)
        refresh.assert_called_once_with()

    async def test_display_javascript_reloads_for_settings_control_event(self):
        display_javascript = (
            PROJECT_ROOT / "static/js/display.js"
        ).read_text(encoding="utf-8")

        self.assertIn("addEventListener('display-refresh'", display_javascript)
        self.assertIn("window.location.reload()", display_javascript)

    async def test_server_signals_streams_before_uvicorn_shutdown_wait(self):
        response = await application.display_events()
        stream_task = asyncio.create_task(anext(response.body_iterator))
        await self.wait_for_subscriber()
        server = create_backend_server()

        with patch.object(uvicorn.Server, "shutdown", new=AsyncMock()) as shutdown:
            await server.shutdown()

        shutdown.assert_awaited_once()
        with self.assertRaises(StopAsyncIteration):
            await asyncio.wait_for(stream_task, timeout=0.5)
        self.assertEqual(server.config.timeout_graceful_shutdown, GRACEFUL_SHUTDOWN_SECONDS)

    async def test_pi_launcher_and_systemd_keep_bounded_shutdown_fallbacks(self):
        backend_script = (PROJECT_ROOT / "scripts/start-backend.sh").read_text(
            encoding="utf-8"
        )
        service = (PROJECT_ROOT / "deploy/leftover-achievements.service").read_text(
            encoding="utf-8"
        )

        self.assertIn('exec "$PYTHON" launcher.py', backend_script)
        self.assertGreaterEqual(GRACEFUL_SHUTDOWN_SECONDS, 5)
        self.assertLessEqual(GRACEFUL_SHUTDOWN_SECONDS, 10)
        self.assertIn("TimeoutStopSec=12s", service)

    async def test_backend_restart_finishes_with_active_sse_connection(self):
        response = await application.display_events()
        connection_task = asyncio.create_task(anext(response.body_iterator))
        await self.wait_for_subscriber()
        server = create_backend_server()
        server.servers = []
        server.lifespan = SimpleNamespace(shutdown=AsyncMock())
        server.server_state.tasks.add(connection_task)
        connection_task.add_done_callback(server.server_state.tasks.discard)

        started = time.monotonic()
        await asyncio.wait_for(server.shutdown(), timeout=0.5)
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        with self.assertRaises(StopAsyncIteration):
            await connection_task
        server.lifespan.shutdown.assert_awaited_once()
        self.assertFalse(application.display_event_queues)


if __name__ == "__main__":
    unittest.main()
