import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

import app as application


ULID = "01TESTPROFILEULID0000000000"


def request():
    return Request({"type": "http", "method": "GET", "path": f"/users/{ULID}", "headers": []})


class UserProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        now = datetime.now(timezone.utc).isoformat()
        self.profile = {"ra_ulid": ULID, "canonical_username": "NewName", "avatar": None,
                        "hardcore_points": 1234, "retro_points": 2345}
        self.details = {"awards": {"masteries": [], "beaten": []}, "awards_refreshed_at": now,
                        "recent": {"game_title": "Last Game", "console": "SNES"}, "recent_refreshed_at": now}
        self.patches = [
            patch.object(application.db, "get_profile_identity", return_value={"ra_username": "OldName", "ra_ulid": ULID}),
            patch.object(application.db, "get_user_profiles", return_value={"oldname": self.profile}),
            patch.object(application.db, "get_profile_details", return_value=self.details),
            patch.object(application.db, "get_currently_playing_cache", return_value={}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_stable_url_survives_username_change_and_shows_recent_game(self):
        response = await application.user_profile(request(), ULID)
        html = response.body.decode()
        self.assertIn("NewName", html)
        self.assertIn("Recently Played", html)
        self.assertIn("Last Game", html)
        self.assertNotIn("Currently Playing", html)
        self.assertIn("No mastered games yet", html)
        self.assertIn("No beaten games yet", html)

    async def test_current_game_replaces_recent_game(self):
        cache = {"oldname": {"active": 1, "payload": {"game_title": "Live Game", "console": "NES",
                  "hardcore_achievements": 2, "total_achievements": 5, "completion_percentage": 40,
                  "hardcore_points": 10, "total_points": 25}, "refreshed_at": datetime.now(timezone.utc).isoformat()}}
        with patch.object(application.db, "get_currently_playing_cache", return_value=cache):
            html = (await application.user_profile(request(), ULID)).body.decode()
        self.assertIn("Currently Playing", html)
        self.assertIn("Live Game", html)
        self.assertNotIn("Last Game", html)

    async def test_unknown_ulid_is_404(self):
        with patch.object(application.db, "get_profile_identity", return_value=None):
            with self.assertRaises(HTTPException) as error:
                await application.user_profile(request(), "missing")
        self.assertEqual(error.exception.status_code, 404)

    async def test_award_sections_render_separately_without_duplicate_game(self):
        self.details["awards"] = {"masteries": [{"game_id": 1, "game_title": "Mastered One", "awarded_at": "2025-02-01"}],
                                   "beaten": [{"game_id": 1, "game_title": "Mastered One", "awarded_at": "2024-01-01"},
                                              {"game_id": 2, "game_title": "Beaten Two", "awarded_at": "2025-01-01"}]}
        html = (await application.user_profile(request(), ULID)).body.decode()
        self.assertLess(html.index("Mastered Games"), html.index("Beaten Games"))
        self.assertEqual(html.count("Mastered One"), 1)
        self.assertEqual(html.count("Beaten Two"), 1)
        self.assertIn("<span>Games Mastered</span><strong>1</strong>", html)
        self.assertIn("<span>Games Beaten</span><strong>1</strong>", html)
        self.assertIn('aria-label="1 mastered games"', html)
        self.assertIn('aria-label="1 beaten games"', html)

    def test_canonical_awards_are_sorted_and_not_duplicated(self):
        awards = {"masteries": [{"game_id": 1, "awarded_at": "2024-01-01"},
                                 {"game_id": 2, "awarded_at": "2025-01-01"}],
                  "beaten": [{"game_id": 1, "awarded_at": "2023-01-01"},
                             {"game_id": 3, "awarded_at": "2025-02-01"},
                             {"game_id": 4, "awarded_at": "2024-02-01"}]}
        result = application.sorted_profile_awards(awards)
        self.assertEqual([g["game_id"] for g in result["masteries"]], [2, 1])
        self.assertEqual([g["game_id"] for g in result["beaten"]], [3, 4])

    def test_dashboard_and_history_have_user_links(self):
        root = Path(application.runtime.resource_root)
        for name in ("dashboard", "history", "users"):
            template = (root / "templates" / f"{name}.html").read_text()
            self.assertIn('href="/users/{{', template)

    def test_profile_route_uses_ulid_parameter(self):
        self.assertTrue(any(route.path == "/users/{ra_ulid}" for route in application.app.routes))
