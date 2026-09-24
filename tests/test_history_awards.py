import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app as application
from database import database as db


class RecordedHistoryAwardTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", str(Path(self.directory.name) / "test.db"))
        self.db_patch.start()
        db.init_db()
        self.start = datetime(2026, 9, 7, tzinfo=timezone(timedelta(hours=-7)))
        self.end = self.start + timedelta(days=7)

    def tearDown(self):
        self.db_patch.stop()
        self.directory.cleanup()

    def beaten(self, game_id, awarded_at, username="Player", announced=True):
        db.save_processed_beaten_game_event(
            {"username": username, "game_id": game_id, "awarded_at": awarded_at},
            announced=announced,
        )

    def test_earned_time_local_boundaries_and_delayed_detection(self):
        self.beaten(1, "2026-09-07T06:59:59+00:00")  # Previous local week.
        self.beaten(2, "2026-09-07T07:00:00+00:00")
        self.beaten(3, "2026-09-14T06:59:59+00:00")
        self.beaten(4, "2026-09-14T07:00:00+00:00")  # Next local week.
        self.beaten(5, "2026-09-13T06:39:21+00:00", announced=False)
        self.beaten(6, "2026-09-10T12:00:00+00:00", username="Other")
        self.assertEqual(
            db.get_recorded_history_award_counts(self.start, self.end, ["player"]),
            {"beaten": 3, "masteries": 0},
        )

    def test_mastery_reawards_do_not_double_count_games(self):
        for index, date in enumerate(("2026-09-08T12:00:00Z", "2026-09-09T12:00:00Z")):
            db.save_processed_mastery_event(
                {"username": "Player", "game_id": 10, "awarded_at": date,
                 "dedupe_key": f"mastery:{index}"}, announced=False,
            )
        self.assertEqual(
            db.get_recorded_history_award_counts(self.start, self.end, ["Player"]),
            {"beaten": 0, "masteries": 1},
        )

    def test_empty_roster_returns_zero_recorded_awards(self):
        self.assertEqual(
            db.get_recorded_history_award_counts(self.start, self.end, []),
            {"beaten": 0, "masteries": 0},
        )


class HistoryAwardRenderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_uses_saved_awards_even_for_zero_point_players(self):
        week = {"week_start": "2026-09-07", "week_end": "2026-09-13"}
        ranking = {"ra_username": "Player", "hardcore_points": 0,
                   "retro_points": 0, "achievements_earned": 0}
        with (
            patch.object(application, "schedule_history_backfill", new=AsyncMock()),
            patch.object(db, "get_history_weeks", return_value=[week]),
            patch.object(db, "get_history_week", return_value=week),
            patch.object(db, "get_history_rankings", return_value=[ranking]),
            patch.object(db, "history_week_count", return_value=1),
            patch.object(db, "get_recorded_history_award_counts",
                         return_value={"beaten": 1, "masteries": 0}) as counts,
            patch.object(application.templates, "TemplateResponse",
                         side_effect=lambda **kwargs: kwargs["context"]),
        ):
            context = await application.history(request=None, week="2026-09-07")
        self.assertEqual(context["summary"]["beaten_display"], "1")
        self.assertEqual(context["summary"]["masteries_display"], "0")
        self.assertEqual(counts.call_args.args[2], ["Player"])
        self.assertEqual(counts.call_args.args[1].date().isoformat(), "2026-09-14")

    async def test_history_exposes_games_grouped_under_each_player(self):
        week = {"week_start": "2026-09-07", "week_end": "2026-09-13"}
        ranking = {
            "ra_username": "Player", "canonical_username": "Player", "ra_ulid": "ABC", "avatar": None,
            "hardcore_points": 5, "retro_points": 9, "achievements_earned": 1,
            "played_games": [{"game_id": 10, "game_title": "Played Game", "console": "NES",
                              "achievements_earned": 1, "hardcore_points": 5, "retro_points": 9}],
        }
        with (
            patch.object(application, "schedule_history_backfill", new=AsyncMock()),
            patch.object(db, "get_history_weeks", return_value=[week]),
            patch.object(db, "get_history_week", return_value=week),
            patch.object(db, "get_history_rankings", return_value=[ranking]),
            patch.object(db, "history_week_count", return_value=1),
            patch.object(db, "get_recorded_history_award_counts", return_value={"beaten": 0, "masteries": 0}),
            patch.object(application.templates, "TemplateResponse", side_effect=lambda **kwargs: kwargs["context"]),
        ):
            context = await application.history(request=None, week="2026-09-07")

        game = context["played_game_users"][0]["played_games"][0]
        self.assertEqual(game["game_title"], "Played Game")
        self.assertEqual(game["hardcore_points_display"], "5")
