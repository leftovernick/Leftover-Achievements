import os
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from services.wrapped import (
    WrappedService,
    get_current_wrapped_year,
    get_wrapped_period,
    get_wrapped_status,
    get_wrapped_year_for_date,
    list_available_wrapped_years,
)


def month_end(month_start: date) -> datetime:
    following = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return datetime.combine(following, datetime.min.time(), tzinfo=timezone.utc) - timedelta(seconds=1)


def complete_rows(start=date(2025, 11, 1), end=date(2026, 11, 1)):
    rows = {}
    month = start.replace(day=1)
    while month <= end.replace(day=1):
        rows[month.isoformat()] = {
            "month_start": month.isoformat(),
            "covered_through": month_end(month).isoformat(),
            "days": {},
        }
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return rows


def game(game_id, title, achievements, points, retro, console="NES"):
    return {
        "game_id": game_id,
        "game_title": title,
        "game_image": f"/{game_id}.png",
        "console": console,
        "achievements_earned": achievements,
        "hardcore_points": points,
        "retro_points": retro,
    }


def day(achievements, points, retro, games, first=None):
    payload = {
        "achievements_earned": achievements,
        "hardcore_points": points,
        "retro_points": retro,
        "games": games,
    }
    if first:
        payload.update(
            first_achievement_at=first,
            first_hardcore_points=games[0]["hardcore_points"] if games else 0,
            first_retro_points=games[0]["retro_points"] if games else 0,
        )
    return payload


class FakeDatabase:
    def __init__(self, rows=None, metadata=None, masteries=None, completions=None, beaten=None):
        self.profile = {
            "username": "Player",
            "ulid": "ABC",
            "avatar": "/avatar.png",
            "member_since": "2011-11-01T00:00:00+00:00",
            "hardcore_points": 100,
            "retro_points": 200,
        }
        self.rows = rows or complete_rows()
        self.metadata = metadata or {}
        self.masteries = masteries or []
        self.completions = completions or []
        self.beaten = beaten or []
        self.metadata_calls = 0

    def get_all_time_chart_cache(self):
        return (
            {"player": {"profile": self.profile, "refreshed_at": "2026-11-02T00:00:00+00:00"}},
            {"ulid:abc": self.rows},
        )

    def get_game_metadata(self, game_ids):
        self.metadata_calls += 1
        return {game_id: self.metadata[game_id] for game_id in game_ids if game_id in self.metadata}

    def get_recorded_chart_masteries(self, usernames, end):
        return {"player": self.masteries}

    def get_recorded_chart_completions(self, usernames, end):
        return {"player": self.completions}

    def get_recorded_chart_beaten_games(self, usernames, end):
        return {"player": self.beaten}


class WrappedPeriodTests(unittest.TestCase):
    def test_anniversary_boundaries(self):
        expected = {
            date(2011, 11, 1): 2012,
            date(2012, 10, 31): 2012,
            date(2012, 11, 1): 2013,
            date(2025, 10, 31): 2025,
            date(2025, 11, 1): 2026,
        }
        for value, year in expected.items():
            with self.subTest(value=value):
                self.assertEqual(get_wrapped_year_for_date(value), year)

    def test_pre_launch_dates_and_2011_wrapped_are_rejected(self):
        with self.assertRaises(ValueError):
            get_wrapped_year_for_date(date(2011, 10, 31))
        with self.assertRaises(ValueError):
            get_wrapped_period(2011, date(2026, 1, 1))

    def test_period_is_inclusive_and_status_turns_on_november_first(self):
        period = get_wrapped_period(2026, date(2026, 10, 31))
        self.assertEqual(period.start_date, date(2025, 11, 1))
        self.assertEqual(period.end_date, date(2026, 10, 31))
        self.assertEqual(period.status, "in_progress")
        self.assertFalse(period.is_complete)
        self.assertEqual(get_wrapped_status(2026, date(2026, 11, 1)), "final")

    def test_datetime_boundaries_follow_utc_even_when_local_date_is_earlier(self):
        utc_november = datetime(2026, 11, 1, 0, 30, tzinfo=timezone.utc)
        self.assertEqual(get_wrapped_year_for_date(utc_november), 2027)
        self.assertEqual(get_wrapped_status(2026, utc_november), "final")

    def test_current_year_and_available_years_are_deterministic(self):
        self.assertEqual(get_current_wrapped_year(date(2026, 10, 31)), 2026)
        self.assertEqual(get_current_wrapped_year(date(2026, 11, 1)), 2027)
        self.assertEqual(
            list_available_wrapped_years(date(2011, 11, 1), date(2012, 1, 1)),
            [2012],
        )
        self.assertEqual(
            list_available_wrapped_years(date(2024, 12, 20), date(2026, 10, 14)),
            [2025, 2026],
        )


class WrappedSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tz_patch = patch.dict(os.environ, {"TZ": "America/Los_Angeles"})
        self.tz_patch.start()
        time.tzset()
        self.now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.tz_patch.stop()
        time.tzset()

    def test_period_filtering_uses_utc_day_keys_across_all_partitions(self):
        rows = complete_rows(start=date(2025, 10, 1), end=date(2026, 11, 1))
        for row in rows.values():
            row["utc_days"] = {}
        rows["2025-10-01"]["utc_days"]["2025-10-31"] = day(9, 90, 180, [game(9, "Before", 9, 90, 180)])
        rows["2025-11-01"]["utc_days"]["2025-11-01"] = day(1, 5, 10, [game(1, "First", 1, 5, 10)])
        rows["2026-11-01"]["utc_days"]["2026-10-31"] = day(2, 10, 20, [game(2, "Last", 2, 10, 20)])
        rows["2026-11-01"]["utc_days"]["2026-11-01"] = day(8, 80, 160, [game(8, "After", 8, 80, 160)])

        # Local buckets can disagree near midnight; Wrapped must ignore them.
        rows["2025-10-01"]["days"]["2025-11-01"] = day(20, 200, 400, [game(20, "Local only", 20, 200, 400)])

        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)

        self.assertEqual(summary.headline.hardcore_achievements, 3)
        self.assertEqual(summary.headline.games_with_progress, 2)
        self.assertEqual(summary.highlights.first_activity.date, date(2025, 11, 1))
        self.assertEqual(summary.highlights.last_activity.date, date(2026, 10, 31))

    def test_softcore_is_included_and_hardcore_upgrade_wins_once_across_months(self):
        rows = complete_rows()
        for row in rows.values():
            row["aggregation_version"] = 2
            row["utc_days"] = {}

        def event_day(earned_at, *, hardcore, achievement_id, points):
            return {
                "achievements_earned": int(hardcore),
                "softcore_achievements_earned": int(not hardcore),
                "hardcore_points": points if hardcore else 0,
                "retro_points": points * 2 if hardcore else 0,
                "unlock_events": [{
                    "achievement_id": achievement_id,
                    "hardcore": hardcore,
                    "earned_at": earned_at,
                    "game_id": 7,
                    "points": points,
                    "retro_points": points * 2,
                }],
                "games": [{
                    "game_id": 7, "game_title": "Mode Game", "game_image": "/7.png",
                    "console": "NES", "achievements_earned": int(hardcore),
                    "softcore_achievements_earned": int(not hardcore),
                    "hardcore_points": points if hardcore else 0,
                    "retro_points": points * 2 if hardcore else 0,
                }],
            }

        rows["2025-11-01"]["utc_days"]["2025-11-05"] = event_day(
            "2025-11-05T12:00:00+00:00", hardcore=False, achievement_id=100, points=5,
        )
        rows["2025-12-01"]["utc_days"]["2025-12-07"] = event_day(
            "2025-12-07T12:00:00+00:00", hardcore=True, achievement_id=100, points=5,
        )
        rows["2026-01-01"]["utc_days"]["2026-01-09"] = event_day(
            "2026-01-09T12:00:00+00:00", hardcore=False, achievement_id=101, points=10,
        )

        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)

        self.assertEqual(summary.headline.total_achievements, 2)
        self.assertEqual(summary.headline.hardcore_achievements, 1)
        self.assertEqual(summary.headline.softcore_achievements, 1)
        self.assertEqual(summary.headline.hardcore_points, 5)
        self.assertEqual(summary.headline.softcore_points, 10)
        self.assertEqual(summary.headline.active_days, 2)
        self.assertEqual(summary.details.games[0].achievements, 2)
        self.assertEqual(summary.details.games[0].hardcore_achievements, 1)
        self.assertEqual(summary.details.games[0].softcore_achievements, 1)
        self.assertEqual([item.date for item in summary.details.days], [date(2025, 12, 7), date(2026, 1, 9)])

    def test_complete_coverage_ends_at_utc_october_partition(self):
        rows = complete_rows()
        complete = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)
        self.assertTrue(complete.coverage.complete)

        del rows["2026-11-01"]
        still_complete = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)
        self.assertTrue(still_complete.coverage.complete)

    def test_missing_month_marks_history_incomplete(self):
        rows = complete_rows()
        del rows["2026-03-01"]
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)
        self.assertFalse(summary.coverage.complete)
        self.assertIn("history_incomplete", summary.coverage.flags)

    def test_current_year_can_be_complete_to_date_but_not_final(self):
        now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        rows = complete_rows(end=date(2026, 10, 1))
        rows["2026-10-01"]["covered_through"] = now.isoformat()
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, now)
        self.assertEqual(summary.status, "in_progress")
        self.assertTrue(summary.coverage.complete)
        self.assertIn("period_in_progress", summary.coverage.flags)

    def test_stale_current_year_cache_reports_missing_range(self):
        now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        rows = complete_rows(end=date(2026, 10, 1))
        rows["2026-10-01"]["covered_through"] = "2026-10-01T23:59:59+00:00"
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, now)
        self.assertEqual(summary.status, "in_progress")
        self.assertFalse(summary.coverage.complete)
        self.assertTrue(summary.coverage.missing_ranges)

    def test_streaks_cross_calendar_year_and_ties_choose_earliest(self):
        rows = complete_rows()
        rows["2025-11-01"]["days"].update({
            "2025-12-31": day(2, 10, 20, [game(2, "Later", 2, 10, 20)]),
            "2026-01-01": day(2, 10, 20, [game(2, "Later", 2, 10, 20)]),
            "2026-02-01": day(2, 10, 20, [game(1, "Earlier", 2, 10, 20)]),
        })
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)
        streak = summary.activity.longest_achievement_streak
        self.assertEqual((streak.start_date, streak.end_date, streak.days),
                         (date(2025, 12, 31), date(2026, 1, 1), 2))
        self.assertEqual(summary.games.top_by_achievements.title, "Later")
        self.assertEqual(summary.activity.busiest_day.date, date(2025, 12, 31))

    def test_genres_use_fractional_weights_and_report_unknown(self):
        games = {
            1: {**game(1, "One", 6, 10, 20), "first_active_date": date(2025, 11, 1)},
            2: {**game(2, "Two", 6, 10, 20), "first_active_date": date(2025, 11, 2)},
            3: {**game(3, "Three", 6, 10, 20), "first_active_date": date(2025, 11, 3)},
            4: {**game(4, "Unknown", 6, 10, 20), "first_active_date": date(2025, 11, 4)},
        }
        metadata = {
            1: {"genre": "Action"},
            2: {"genre": "Action, RPG"},
            3: {"genre": "Action, RPG, Puzzle"},
            4: {"genre": "  "},
        }

        genres = WrappedService._genres(games, metadata)
        weights = {row.genre: row.achievement_weight for row in genres.achievement_shares}

        self.assertEqual(weights["Action"], 11.0)
        self.assertEqual(weights["RPG"], 5.0)
        self.assertEqual(weights["Puzzle"], 2.0)
        self.assertAlmostEqual(sum(weights.values()) + 6, 24)
        self.assertEqual(genres.games_without_genre, 1)
        self.assertEqual(genres.coverage_percent, 75.0)
        self.assertEqual(genres.unknown_achievement_share_percent, 25.0)

    def test_subset_games_merge_into_their_parent_game_in_wrapped(self):
        rows = complete_rows()
        rows["2026-01-01"]["days"]["2026-01-05"] = day(
            15,
            75,
            150,
            [
                game(34747, "Pokémon Rumble", 5, 25, 50, "Wii"),
                game(38067, "Pokémon Rumble [Subset - Professor Oak Challenge]", 10, 50, 100, "Wii"),
            ],
        )
        rows["2026-01-01"]["days"]["2026-01-06"] = day(
            3,
            15,
            30,
            [game(38067, "Pokémon Rumble [Subset - Professor Oak Challenge]", 3, 15, 30, "Wii")],
        )
        database = FakeDatabase(rows, metadata={
            34747: {
                "game_title": "Pokémon Rumble",
                "console": "Wii",
                "genre": "Beat 'em Up",
                "image_icon": "https://example.test/pokemon-rumble-icon.png",
                "image_box_art": "https://example.test/pokemon-rumble-cover.png",
            },
            38067: {
                "game_title": "Pokémon Rumble [Subset - Professor Oak Challenge]",
                "console": "Wii",
                "genre": "Beat 'em Up",
                "parent_game_id": 34747,
                "image_icon": "https://example.test/subset-icon.png",
                "image_box_art": "https://example.test/subset-cover.png",
            },
        })

        summary = WrappedService(database).generate_year("Player", 2026, self.now)

        top = summary.games.top_by_achievements
        detail = summary.details.games[0]
        self.assertEqual(summary.headline.games_with_progress, 1)
        self.assertEqual(top.game_id, 34747)
        self.assertEqual(top.title, "Pokémon Rumble")
        self.assertEqual(top.image, "https://example.test/pokemon-rumble-icon.png")
        self.assertEqual(top.value, 18)
        self.assertEqual(detail.game_id, 34747)
        self.assertEqual(detail.title, "Pokémon Rumble")
        self.assertEqual(detail.image, "https://example.test/pokemon-rumble-icon.png")
        self.assertEqual(detail.cover_image, "https://example.test/pokemon-rumble-cover.png")
        self.assertEqual(detail.achievements, 18)
        self.assertEqual(detail.active_days, 2)

    def test_top_genre_and_console_ties_are_deterministic(self):
        games = {
            1: {**game(1, "One", 2, 10, 20, "SNES"), "first_active_date": date(2025, 11, 2)},
            2: {**game(2, "Two", 2, 10, 20, "NES"), "first_active_date": date(2025, 11, 1)},
        }
        genres = WrappedService._genres(games, {1: {"genre": "RPG"}, 2: {"genre": "Action"}})
        consoles = WrappedService._consoles(games)
        self.assertEqual(genres.top_genre.genre, "Action")
        self.assertEqual(consoles.top_by_achievements.console, "NES")

    def test_event_sets_count_in_totals_but_not_console_rankings(self):
        rows = complete_rows()
        rows["2026-01-01"]["days"]["2026-01-05"] = day(
            120,
            600,
            1200,
            [
                game(1, "Event Set", 100, 500, 1000, "Events"),
                game(2, "Console Game", 20, 100, 200, "PlayStation 2"),
            ],
        )
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)

        self.assertEqual(summary.headline.hardcore_achievements, 120)
        self.assertEqual(summary.headline.games_with_progress, 2)
        self.assertEqual(summary.headline.consoles_with_progress, 1)
        self.assertEqual(summary.consoles.top_by_achievements.console, "PlayStation 2")
        for rankings in (
            summary.consoles.achievements,
            summary.consoles.hardcore_points,
            summary.consoles.retro_points,
            summary.consoles.unique_progress_games,
        ):
            self.assertNotIn("Events", [row.console for row in rankings])

    def test_awards_are_read_from_stored_tiers_and_months(self):
        db = FakeDatabase(
            masteries=[{"game_id": 1, "game_title": "Mastered", "game_image": None,
                        "date": "2026-01-02T00:00:00+00:00"}],
            beaten=[{"game_id": 2, "game_title": "Beaten", "game_image": None,
                     "date": "2026-02-02T00:00:00+00:00"}],
        )
        summary = WrappedService(db).generate_year("Player", 2026, self.now)
        self.assertEqual(summary.awards.mastered_games, 1)
        self.assertEqual(summary.awards.beaten_games_partial, 1)
        self.assertEqual(summary.awards.observed_beaten_games, 1)
        self.assertEqual(summary.awards.effective_beaten_games, 1)
        self.assertEqual(summary.headline.effective_beaten_games, 1)
        self.assertEqual(summary.awards.mastery_reliability, "more_reliable")
        self.assertEqual(summary.awards.beaten_reliability, "stored_awards")
        self.assertNotIn("beaten_history_partial", summary.coverage.flags)

    def test_wrapped_award_tiers_do_not_double_count_higher_awards(self):
        db = FakeDatabase(
            masteries=[
                {"game_id": 2, "game_title": "Both", "game_image": None,
                 "date": "2026-01-03T00:00:00+00:00"},
                {"game_id": 3, "game_title": "Mastery only", "game_image": None,
                 "date": "2026-01-04T00:00:00+00:00"},
                {"game_id": 4, "game_title": "Another mastery", "game_image": None,
                 "date": "2026-01-05T00:00:00+00:00"},
            ],
            completions=[
                {"game_id": 4, "game_title": "Completed then mastered", "game_image": None,
                 "date": "2026-01-03T00:00:00+00:00"},
                {"game_id": 5, "game_title": "Completed", "game_image": None,
                 "date": "2026-01-04T00:00:00+00:00"},
            ],
            beaten=[
                {"game_id": 1, "game_title": "Beaten only", "game_image": None,
                 "date": "2026-01-01T00:00:00+00:00"},
                {"game_id": 2, "game_title": "Both", "game_image": None,
                 "date": "2026-01-02T00:00:00+00:00"},
                {"game_id": 5, "game_title": "Completed", "game_image": None,
                 "date": "2026-01-02T00:00:00+00:00"},
            ],
        )
        summary = WrappedService(db).generate_year("Player", 2026, self.now)
        self.assertEqual(summary.awards.observed_beaten_games, 3)
        self.assertEqual(summary.awards.mastered_games, 3)
        self.assertEqual(summary.awards.completed_games, 1)
        self.assertEqual(summary.awards.effective_beaten_games, 1)
        self.assertEqual(summary.awards.mastery_only_beaten_games, 0)
        self.assertEqual(summary.headline.observed_beaten_games, 3)
        self.assertEqual(summary.headline.effective_beaten_games, 1)

    def test_first_activity_is_local_only_and_enrichment_slots_stay_empty(self):
        rows = complete_rows()
        rows["2025-11-01"]["days"]["2025-11-03"] = day(
            1, 5, 9, [game(1, "Game", 1, 5, 9)], "2025-11-03T08:01:00+00:00",
        )
        summary = WrappedService(FakeDatabase(rows)).generate_year("Player", 2026, self.now)
        self.assertEqual(summary.highlights.first_activity.points, 5)
        self.assertTrue(summary.highlights.first_activity.enrichment_required)
        self.assertIsNone(summary.highlights.rarest_achievement)
        self.assertIsNone(summary.highlights.highest_point_achievement)
        self.assertIsNone(summary.highlights.highest_retro_points_achievement)

    def test_generation_batches_metadata_once(self):
        rows = complete_rows()
        rows["2025-11-01"]["days"]["2025-11-03"] = day(
            2, 10, 20, [game(1, "One", 1, 5, 10), game(2, "Two", 1, 5, 10)],
        )
        database = FakeDatabase(rows, metadata={1: {"genre": "Action"}, 2: {"genre": "RPG"}})
        WrappedService(database).generate_year("Player", 2026, self.now)
        self.assertEqual(database.metadata_calls, 1)


if __name__ == "__main__":
    unittest.main()
