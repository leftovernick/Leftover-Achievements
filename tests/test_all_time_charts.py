import asyncio
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from database import database as db
from services.all_time_charts import AllTimeCharts, daily_points, month_ranges, parse_date


class AllTimeChartTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(db, "DB_PATH", str(Path(self.directory.name) / "test.db"))
        self.db_patch.start()
        self.tz_patch = patch.dict(os.environ, {"TZ": "America/Los_Angeles"})
        self.tz_patch.start()
        time.tzset()
        db.init_db()
        self.now = datetime(2026, 2, 18, 12, tzinfo=timezone.utc)
        self.profile = {"username": "Player", "ulid": "ABC", "member_since": "2026-01-08 20:00:00",
                        "hardcore_points": 123, "retro_points": 999, "avatar": None}
        self.users = [{"ra_username": "Player", "ra_ulid": "ABC"}]
        self.achievements = [
            {"AchievementID": 1, "Date": "2026-01-08 20:01:00", "HardcoreMode": 1, "Points": 5, "TrueRatio": 9},
            {"AchievementID": 2, "Date": "2026-01-12 07:59:59", "HardcoreMode": "1", "Points": 10, "TrueRatio": 20},
            {"AchievementID": 3, "Date": "2026-01-12 08:00:00", "HardcoreMode": 1, "Points": 20, "TrueRatio": 40},
            {"AchievementID": 4, "Date": "2026-02-02 12:00:00", "HardcoreMode": True, "Points": 25, "TrueRatio": 50},
            {"AchievementID": 5, "Date": "2026-01-10 12:00:00", "HardcoreMode": 0, "Points": 100, "TrueRatio": 200},
        ]
        self.client = Mock()
        self.client.lookup_user = AsyncMock(return_value=self.profile)
        self.client.achievements_earned_between = AsyncMock(return_value=self.achievements)
        self.service = AllTimeCharts(self.client, db)

    async def asyncTearDown(self):
        await self.service.stop()
        self.db_patch.stop()
        self.directory.cleanup()
        self.tz_patch.stop()
        time.tzset()

    async def refresh(self, **kwargs):
        with patch("services.all_time_charts.asyncio.sleep", new=AsyncMock()):
            await self.service.refresh(self.users, now=self.now, **kwargs)

    async def test_full_backfill_populates_both_metrics_and_every_completed_week(self):
        await self.refresh()
        payload = self.service.payload(self.users, self.now)
        self.assertEqual(payload["ready_users"], 1)
        self.assertFalse(payload["needs_refresh"])
        points = payload["users"][0]["points"]
        self.assertEqual(points[0]["hardcore_points"], 0)
        self.assertEqual(points[0]["date"], "2026-01-08T20:00:00+00:00")
        self.assertEqual(points[1]["hardcore_points"], 35)
        self.assertEqual(points[1]["retro_points"], 69)
        self.assertEqual(points[-1]["hardcore_points"], 123)
        self.assertEqual(points[-1]["retro_points"], 999)
        self.assertEqual(db.history_week_count(), 6)
        first = db.get_history_rankings("2026-01-05")[0]
        second = db.get_history_rankings("2026-01-12")[0]
        self.assertEqual(first["hardcore_points"], 15)
        self.assertEqual(first["retro_points"], 29)
        self.assertEqual(first["achievements_earned"], 2)
        self.assertEqual(second["hardcore_points"], 20)
        self.assertEqual(db.get_history_rankings("2026-02-09")[0]["hardcore_points"], 0)
        self.assertIsNone(db.get_history_week("2026-02-16"))
        self.assertEqual(self.client.achievements_earned_between.await_count, 2)

    async def test_reload_reuses_persisted_cache_without_network_requests(self):
        await self.refresh()
        self.client.reset_mock()
        restarted = AllTimeCharts(self.client, db)
        with patch("services.all_time_charts.asyncio.sleep", new=AsyncMock()):
            await restarted.refresh(self.users, now=self.now)
        self.client.lookup_user.assert_not_awaited()
        self.client.achievements_earned_between.assert_not_awaited()
        self.assertEqual(restarted.payload(self.users, self.now)["ready_users"], 1)

    async def test_refresh_updates_current_month_only_and_preserves_snapshots(self):
        await self.refresh()
        self.client.reset_mock()
        await self.refresh(force=True)
        self.client.lookup_user.assert_awaited_once_with("ABC")
        self.assertEqual(self.client.achievements_earned_between.await_count, 1)
        self.assertEqual(self.client.achievements_earned_between.call_args.args[1].month, 2)
        self.assertEqual(db.get_history_rankings("2026-01-05")[0]["hardcore_points"], 15)

    async def test_failure_leaves_progress_and_missing_ranges_are_not_zero(self):
        self.client.achievements_earned_between.side_effect = [self.achievements, TimeoutError()]
        with patch("services.all_time_charts.logger"):
            await self.refresh()
        self.assertEqual(self.service.payload(self.users, self.now)["ready_users"], 0)
        self.assertIsNone(self.service.cached_week_stats("Player", parse_date("2026-02-02T08:00:00Z"), parse_date("2026-02-09T07:59:59Z")))
        self.client.achievements_earned_between.side_effect = None
        self.client.achievements_earned_between.reset_mock()
        await self.refresh()
        self.assertEqual(self.client.achievements_earned_between.await_count, 1)
        self.assertEqual(self.service.payload(self.users, self.now)["ready_users"], 1)

    async def test_pre_creation_weeks_are_zero_and_cached_week_needs_no_fetch(self):
        await self.refresh()
        points = self.service.cached_week_stats("player", parse_date("2026-01-05T08:00:00Z"), parse_date("2026-01-12T07:59:59Z"))
        self.assertEqual(points["hardcore_points"], 15)
        before = self.service.cached_week_stats("Player", parse_date("2025-12-01T08:00:00Z"), parse_date("2025-12-08T07:59:59Z"))
        self.assertEqual(before["hardcore_points"], 0)

    async def test_previous_partial_month_requires_completion(self):
        await self.refresh()
        later = parse_date("2026-03-03T12:00:00Z")
        payload = self.service.payload(self.users, later)
        self.assertEqual(payload["ready_users"], 0)
        self.assertTrue(payload["needs_refresh"])

    async def test_invalid_creation_date_does_not_invent_a_timeline(self):
        self.client.lookup_user.return_value = {**self.profile, "member_since": None}
        with patch("services.all_time_charts.logger"):
            await self.refresh()
        self.assertIsNone(self.service.payload(self.users, self.now)["start"])
        self.client.achievements_earned_between.assert_not_awaited()

    async def test_duplicate_requests_share_one_background_job(self):
        release = asyncio.Event()
        async def wait(*args):
            await release.wait()
        self.service.refresh = AsyncMock(side_effect=wait)
        self.service.schedule(self.users)
        task = self.service.task
        self.service.schedule(self.users, force=True)
        self.assertIs(self.service.task, task)
        await asyncio.sleep(0)
        self.service.refresh.assert_awaited_once()
        release.set()
        await task

    async def test_weekly_audit_does_not_duplicate_lifetime_fetching(self):
        import app as application
        status = {"current": None, "processed": 0, "deferred": 0, "failed": 0, "fetched": 0}
        with (
            patch.object(application, "history_backfill_status", status),
            patch.object(application.ra_client, "points_earned_between", new=AsyncMock()) as fetch,
        ):
            await application.backfill_history_user(
                self.users[0], [(parse_date("2026-01-05T08:00:00Z"), parse_date("2026-01-12T07:59:59Z"))],
                {"player": self.profile},
            )
        fetch.assert_not_awaited()
        self.assertEqual(status["deferred"], 1)

    async def test_response_failure_has_a_traceback_in_settings_log(self):
        import app as application
        from fastapi import HTTPException
        with (
            patch.object(application.db, "get_tracked_users", side_effect=RuntimeError("simulated response failure")),
            self.assertLogs("app", level="ERROR") as captured,
        ):
            with self.assertRaises(HTTPException) as raised:
                await application.all_time_chart_data()
        self.assertEqual(raised.exception.status_code, 500)
        self.assertIn("Could not build All Time chart response", captured.output[0])
        self.assertIn("Traceback", captured.output[0])

    def test_daily_aggregation_filters_modes_boundaries_and_duplicates(self):
        achievements = self.achievements + [self.achievements[0]]
        days = daily_points(achievements, parse_date("2026-01-08T20:00:00Z"), parse_date("2026-01-31T23:59:59Z"))
        self.assertEqual(sum(row["hardcore_points"] for row in days.values()), 35)
        self.assertEqual(days["2026-01-11"]["hardcore_points"], 10)
        self.assertEqual(days["2026-01-12"]["hardcore_points"], 20)

    def test_month_windows_do_not_overlap_and_handle_leap_year(self):
        ranges = list(month_ranges(parse_date("2024-01-31T23:59:59Z"), parse_date("2024-03-01T12:00:00Z")))
        self.assertEqual(ranges[1][2].date().isoformat(), "2024-02-29")
        self.assertEqual(ranges[0][2] + timedelta(seconds=1), ranges[1][1])

    def test_completed_history_extends_to_account_creation_not_four_weeks(self):
        profile = {**self.profile, "member_since": "2010-01-08 20:00:00"}
        db.save_all_time_chart_profile("Player", profile, self.now)
        for month, _, end in month_ranges(parse_date(profile["member_since"]), self.now):
            db.save_all_time_chart_month("ulid:abc", month.date().isoformat(),
                                         {"hardcore_points": 0, "retro_points": 0}, end, {})
        self.service.materialize_history(self.users, self.now)
        self.assertIsNotNone(db.get_history_week("2010-01-04"))
        self.assertGreater(db.history_week_count(), 800)

    def test_ui_toggle_is_local_and_shared_axis_starts_at_zero(self):
        root = Path(__file__).resolve().parents[1]
        javascript = (root / "static/js/charts.js").read_text()
        template = (root / "templates/charts.html").read_text()
        self.assertIn('data-chart-range="all"', template)
        self.assertIn('data-chart-metric="retro_points"', template)
        self.assertIn("if (allTimeData) renderAllTime(allTimeData)", javascript)
        self.assertIn("options.scales.y.min = 0", javascript)
        self.assertIn("options.scales.x.type = 'linear'", javascript)
