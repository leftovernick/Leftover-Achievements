import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

import app as application
from instance_config import InstanceConfig, normalize_hub_url


def request_for(path: str, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 12345),
            "root_path": "",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "headers": [],
        }
    )


class InstanceConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary_directory.name) / "instance-config.json"
        self.config = InstanceConfig(self.path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_addresses_are_normalized(self):
        self.assertEqual(normalize_hub_url("PI.local:8000/"), "http://pi.local:8000")
        self.assertEqual(normalize_hub_url("https://Example.com"), "https://example.com")

    def test_page_paths_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_hub_url("http://pi.local:8000/admin")

    def test_connect_and_disconnect_preserve_the_local_instance_identity(self):
        local_id = self.config.instance_id()
        self.config.connect("192.168.1.50:8000")
        self.assertEqual(self.config.role, "client")
        self.assertEqual(self.config.hub_url, "http://192.168.1.50:8000")

        self.config.disconnect()
        self.assertEqual(self.config.role, "hub")
        self.assertIsNone(self.config.hub_url)
        self.assertEqual(self.config.instance_id(), local_id)
        self.assertNotIn("hub_url", json.loads(self.path.read_text()))


class HubRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_frontend_pages_redirect_to_hub_with_query_string(self):
        with patch.object(
            application.instance_config,
            "_read",
            return_value={"hub_url": "http://pi.local:8000"},
        ):
            self.assertEqual(
                application.remote_page_url(request_for("/history", "week=2026-01-01")),
                "http://pi.local:8000/history?week=2026-01-01",
            )
            self.assertIsNone(application.remote_page_url(request_for("/api/setup/status")))
            self.assertIsNone(application.remote_page_url(request_for("/connection")))

    async def test_connecting_stops_local_data_polling_and_preserves_database(self):
        with (
            patch.object(
                application,
                "validate_hub_connection",
                new=AsyncMock(return_value=("http://pi.local:8000", None)),
            ),
            patch.object(application.instance_config, "connect") as connect,
            patch.object(application, "stop_data_polling", new=AsyncMock()) as stop,
        ):
            response = await application.connect_to_hub("pi.local:8000")

        connect.assert_called_once_with("http://pi.local:8000")
        stop.assert_awaited_once()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "http://pi.local:8000")

    async def test_disconnecting_resumes_completed_local_instance(self):
        with (
            patch.object(application.instance_config, "disconnect") as disconnect,
            patch.object(application.db, "setup_complete", return_value=True),
            patch.object(application, "start_background_polling", new=AsyncMock()) as start,
        ):
            response = await application.disconnect_from_hub()

        disconnect.assert_called_once()
        start.assert_awaited_once()
        self.assertEqual(response.headers["location"], "/")

    async def test_client_startup_does_not_start_local_data_polling(self):
        with (
            patch.object(
                application.instance_config,
                "_read",
                return_value={"hub_url": "http://pi.local:8000"},
            ),
            patch.object(application.db, "setup_complete", return_value=True),
            patch.object(application.application_updater, "start"),
            patch.object(application, "schedule_history_backfill") as history,
            patch.object(application, "create_logged_task") as create_task,
        ):
            await application.start_background_polling()

        history.assert_not_called()
        create_task.assert_not_called()


if __name__ == "__main__":
    unittest.main()
