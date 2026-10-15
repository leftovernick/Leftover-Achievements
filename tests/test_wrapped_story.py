import os
import time
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from services.wrapped import StreakMetric, WrappedService
from services.wrapped_story import WrappedStorySelector, WrappedStoryService
from tests.test_wrapped import FakeDatabase, complete_rows, day, game


NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def card(plan, card_type):
    return next(item for item in plan.cards if item.type == card_type)


def make_summary(
    achievements,
    *,
    consoles=None,
    genres=None,
    masteries=None,
    day_values=None,
):
    rows = complete_rows()
    consoles = consoles or ["NES"] * len(achievements)
    games = [
        game(index + 1, f"Game {index + 1}", value, value * 5, value * 10, consoles[index])
        for index, value in enumerate(achievements)
    ]
    if day_values is None:
        day_values = [(date(2026, 1, 5), games)]
    for active_date, active_games in day_values:
        rows[active_date.replace(day=1).isoformat()]["days"][active_date.isoformat()] = day(
            sum(item["achievements_earned"] for item in active_games),
            sum(item["hardcore_points"] for item in active_games),
            sum(item["retro_points"] for item in active_games),
            active_games,
        )
    metadata = {
        index + 1: {"game_title": f"Game {index + 1}", "console": consoles[index], "genre": genre}
        for index, genre in enumerate(genres or ["Action"] * len(achievements))
        if genre is not None
    }
    database = FakeDatabase(rows, metadata=metadata, masteries=masteries or [])
    return WrappedService(database).generate_year("Player", 2026, NOW), database


class WrappedStoryTests(unittest.TestCase):
    def setUp(self):
        self.tz_patch = patch.dict(os.environ, {"TZ": "America/Los_Angeles"})
        self.tz_patch.start()
        time.tzset()
        self.selector = WrappedStorySelector()

    def tearDown(self):
        self.tz_patch.stop()
        time.tzset()

    def test_game_focus_variants_and_dominance_flags(self):
        cases = (
            ([10] * 10 + [1] * 10, "focused_year"),
            ([6] * 10 + [4] * 10, "mixed_year"),
            ([5] * 20, "broad_year"),
        )
        for values, expected in cases:
            with self.subTest(expected=expected):
                summary, _ = make_summary(values)
                focus = card(self.selector.build_plan(summary), "game_focus")
                self.assertEqual(focus.variant, expected)

        summary, _ = make_summary([40] + [4] * 15)
        focus = card(self.selector.build_plan(summary), "game_focus")
        self.assertTrue(focus.supporting_data["single_game_dominance"])
        self.assertTrue(focus.supporting_data["extreme_single_game_dominance"])

    def test_console_dominance_sweep_and_split_leaders(self):
        summary, _ = make_summary([60, 40], consoles=["A", "B"])
        console = card(self.selector.build_plan(summary), "console")
        self.assertEqual(console.variant, "console_majority")
        self.assertTrue(console.supporting_data["console_sweep"])
        self.assertIn("console_sweep", console.supporting_data["selection_flags"])

        summary, _ = make_summary([40, 35, 25], consoles=["A", "B", "C"])
        # Make B lead points/RetroPoints while A remains the achievement leader.
        summary.consoles.hardcore_points = [replace(summary.consoles.hardcore_points[1], value=999), summary.consoles.hardcore_points[0]]
        summary.consoles.retro_points = [replace(summary.consoles.retro_points[1], value=999), summary.consoles.retro_points[0]]
        console = card(self.selector.build_plan(summary), "console")
        self.assertEqual(console.variant, "console_dominant")
        self.assertTrue(console.supporting_data["split_console_leaders"])

    def test_genre_eligibility_boundary_and_variants(self):
        summary, _ = make_summary([10] * 10, genres=["Action"] * 7 + [None] * 3)
        self.assertEqual(card(self.selector.build_plan(summary), "genre").variant, "genre_obsession")

        summary, _ = make_summary([10] * 10, genres=["Action"] * 6 + [None] * 4)
        self.assertNotIn("genre", [item.type for item in self.selector.build_plan(summary).cards])

        cases = (
            (["A"] * 7 + ["B"] * 7 + ["C"] * 6, "genre_dominant"),
            (["A"] * 5 + ["B"] * 5 + ["C"] * 5 + ["D"] * 5, "genre_preference"),
            ([f"G{i % 10}" for i in range(20)], "genre_varied"),
        )
        for labels, expected in cases:
            with self.subTest(expected=expected):
                summary, _ = make_summary([5] * 20, genres=labels)
                self.assertEqual(card(self.selector.build_plan(summary), "genre").variant, expected)

    def test_monthly_variants(self):
        def monthly(values):
            games = [game(1, "Game", value, value * 5, value * 10) for value in values]
            dates = []
            for index, payload in enumerate(games):
                month_number = (11 + index - 1) % 12 + 1
                year = 2025 if month_number >= 11 else 2026
                dates.append((date(year, month_number, 5), [payload]))
            summary, _ = make_summary([sum(values)], day_values=dates)
            return card(self.selector.build_plan(summary), "monthly_pattern")

        self.assertEqual(monthly([60, 40]).variant, "dominant_month")
        self.assertEqual(monthly([40, 30, 30]).variant, "strong_month")
        self.assertEqual(monthly([10] * 12).variant, "steady_year")
        self.assertEqual(monthly([10] * 10).variant, "active_most_year")
        self.assertEqual(monthly([10] * 6).variant, "seasonal_year")
        self.assertEqual(monthly([10] * 3).variant, "burst_year")

    def test_activity_priority_and_weekday_fallback(self):
        summary, _ = make_summary([100])
        summary.activity.longest_achievement_streak = StreakMetric(date(2026, 1, 1), date(2026, 1, 2), 2)
        summary.activity.longest_inactive_gap = StreakMetric(date(2026, 1, 3), date(2026, 1, 12), 10)
        self.assertEqual(card(self.selector.build_plan(summary), "activity_pattern").variant, "strong_weekday_pattern")

        values = []
        for index in range(7):
            payload = game(1, "Game", 10, 50, 100)
            values.append((date(2026, 1, 5) + timedelta(days=index), [payload]))
        summary, _ = make_summary([70], day_values=values)
        summary.activity.longest_achievement_streak = StreakMetric(date(2026, 1, 5), date(2026, 1, 11), 7)
        summary.activity.longest_inactive_gap = StreakMetric(date(2026, 1, 12), date(2026, 1, 21), 10)
        self.assertEqual(card(self.selector.build_plan(summary), "activity_pattern").variant, "weekday_fallback")

    def test_only_internal_inactive_gaps_qualify_as_comebacks(self):
        def activity_summary(dates):
            values = []
            for active_date in dates:
                payload = game(1, "Game", 10, 50, 100)
                values.append((active_date, [payload]))
            return make_summary([len(dates) * 10], day_values=values)[0]

        leading = activity_summary([date(2026, 7, 1) + timedelta(days=index) for index in range(15)])
        self.assertGreaterEqual(leading.activity.longest_inactive_gap.days, 180)
        self.assertEqual(card(self.selector.build_plan(leading), "activity_pattern").variant, "notable_streak")

        trailing = activity_summary([date(2025, 11, 1), date(2025, 11, 2)])
        self.assertGreaterEqual(trailing.activity.longest_inactive_gap.days, 180)
        self.assertNotIn("comeback", card(self.selector.build_plan(trailing), "activity_pattern").variant)

        internal = activity_summary([date(2025, 11, 1), date(2026, 2, 1)])
        activity = card(self.selector.build_plan(internal), "activity_pattern")
        self.assertEqual(activity.variant, "major_comeback")
        self.assertEqual(activity.headline_data["days"], 91)
        self.assertEqual(activity.headline_data["activity_before"], date(2025, 11, 1))
        self.assertEqual(activity.headline_data["activity_after"], date(2026, 2, 1))

    def test_2024_regression_shape_uses_streak_not_leading_gap(self):
        dates = [date(2024, 7, 7) + timedelta(days=index) for index in range(15)]
        dates.extend([date(2024, 8, 24), date(2024, 9, 21)])
        rows = complete_rows(start=date(2023, 11, 1), end=date(2024, 11, 1))
        for active_date in dates:
            payload = game(1, "Game", 10, 50, 100)
            rows[active_date.replace(day=1).isoformat()]["days"][active_date.isoformat()] = day(10, 50, 100, [payload])
        summary = WrappedService(FakeDatabase(rows)).generate_year(
            "Player", 2024, datetime(2024, 11, 2, 12, tzinfo=timezone.utc),
        )
        activity = card(self.selector.build_plan(summary), "activity_pattern")
        self.assertEqual(summary.activity.longest_inactive_gap.days, 249)
        self.assertEqual(activity.variant, "notable_streak")
        self.assertEqual(activity.headline_data["days"], 15)

    def test_2025_regression_shape_keeps_streak_and_unique_special(self):
        values = [
            (date(2026, 1, 6) + timedelta(days=index), [game(1, "Game", 1, 5, 10)])
            for index in range(60)
        ]
        values.append((date(2026, 7, 28), [game(1, "Game", 122, 100, 500)]))
        base = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
        masteries = [
            {"game_id": index + 1, "game_title": f"Game {index + 1}", "game_image": None,
             "date": (base + timedelta(hours=index)).isoformat()}
            for index in range(4)
        ]
        summary, _ = make_summary([182], day_values=values, masteries=masteries)
        plan = self.selector.build_plan(summary)
        self.assertEqual(card(plan, "activity_pattern").variant, "strong_streak")
        self.assertEqual(card(plan, "mastery").variant, "mastery_sprint")
        self.assertEqual(card(plan, "special_highlight").variant, "unusual_retropoint_day")

    def test_mastery_cluster_detection(self):
        base = datetime(2026, 1, 5, 12, tzinfo=timezone.utc)
        masteries = [
            {"game_id": index + 1, "game_title": f"Game {index + 1}", "game_image": None,
             "date": (base + timedelta(hours=index)).isoformat()}
            for index in range(4)
        ]
        summary, _ = make_summary([30, 30, 30, 30], masteries=masteries)
        mastery = card(self.selector.build_plan(summary), "mastery")
        self.assertEqual(mastery.variant, "mastery_sprint")
        self.assertEqual(mastery.supporting_data["cluster_count"], 1)
        self.assertEqual(mastery.supporting_data["largest_cluster_size"], 4)

        self.assertNotIn("special_highlight", [item.type for item in self.selector.build_plan(summary).cards])

    def test_special_highlight_skips_duplicated_month_and_biggest_day(self):
        month_summary, _ = make_summary(
            [100],
            day_values=[
                (date(2026, 1, 5), [game(1, "Game", 70, 350, 700)]),
                (date(2026, 2, 5), [game(1, "Game", 30, 150, 300)]),
            ],
        )
        month_plan = self.selector.build_plan(month_summary)
        self.assertEqual(card(month_plan, "monthly_pattern").variant, "dominant_month")
        self.assertNotIn("extreme_month_dominance", [item.variant for item in month_plan.cards])

        day_summary, _ = make_summary([120])
        day_plan = self.selector.build_plan(day_summary)
        self.assertEqual(card(day_plan, "biggest_day").variant, "huge_day")
        self.assertNotIn("massive_single_day", [item.variant for item in day_plan.cards])

    def test_special_highlight_falls_through_to_unique_candidate(self):
        summary, _ = make_summary([120])
        original = summary.details.days[0]
        summary.details.days[0] = replace(original, hardcore_points=100, retro_points=500)
        special = card(self.selector.build_plan(summary), "special_highlight")
        self.assertEqual(special.variant, "unusual_retropoint_day")

    def test_special_highlight_is_omitted_when_all_candidates_duplicate(self):
        summary, _ = make_summary([120])
        plan = self.selector.build_plan(summary)
        self.assertNotIn("special_highlight", [item.type for item in plan.cards])

    def test_zero_activity_exclusion_and_in_progress_opt_in(self):
        empty_db = FakeDatabase(complete_rows())
        service = WrappedStoryService(WrappedService(empty_db))
        self.assertEqual(service.generate_for_user("Player", NOW), [])

        now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
        rows = complete_rows(end=date(2026, 10, 1))
        rows["2026-01-01"]["days"]["2026-01-05"] = day(1, 5, 10, [game(1, "Game", 1, 5, 10)])
        rows["2026-10-01"]["covered_through"] = now.isoformat()
        service = WrappedStoryService(WrappedService(FakeDatabase(rows)))
        self.assertEqual(service.generate_for_user("Player", now), [])
        plans = service.generate_for_user("Player", now, include_in_progress=True)
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].status, "in_progress")
        self.assertTrue(all(item.status == "in_progress" for item in plans[0].cards))

    def test_year_over_year_variants(self):
        previous, _ = make_summary([100])
        previous.headline.active_days = 100
        cases = (
            (200, 200, "big_growth"),
            (120, 110, "moderate_growth"),
            (105, 105, "similar_year"),
            (70, 70, "quieter_year"),
        )
        for achievements, active_days, expected in cases:
            with self.subTest(expected=expected):
                current, _ = make_summary([achievements])
                current.headline.active_days = active_days
                yoy = card(self.selector.build_plan(current, previous), "year_over_year")
                self.assertEqual(yoy.variant, expected)

        current, _ = make_summary([120])
        current.headline.active_days = 1
        previous.headline.active_days = 10
        self.assertEqual(card(self.selector.build_plan(current, previous), "year_over_year").variant, "mixed_year_over_year")

    def test_incomplete_history_suppresses_optional_confident_cards(self):
        previous, _ = make_summary([50])
        summary, _ = make_summary([120], genres=["Action"])
        summary.coverage.complete = False
        summary.coverage.flags.append("history_incomplete")
        plan = self.selector.build_plan(summary, previous)
        types = [item.type for item in plan.cards]
        self.assertNotIn("genre", types)
        self.assertNotIn("special_highlight", types)
        self.assertNotIn("year_over_year", types)
        self.assertEqual(card(plan, "headline_totals").confidence, "low")


if __name__ == "__main__":
    unittest.main()
