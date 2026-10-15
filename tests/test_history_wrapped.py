import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import app as application
from tests.test_wrapped_ui import prototype_samples


def wrapped_summaries():
    summary_2024, _, summary_2025, _ = prototype_samples()
    empty_2023 = replace(
        summary_2024,
        wrapped_year=2023,
        period_start=date(2022, 11, 1),
        period_end=date(2023, 10, 31),
        headline=replace(summary_2024.headline, hardcore_achievements=0, games_with_progress=0),
    )
    current_2026 = replace(
        summary_2025,
        wrapped_year=2026,
        period_start=date(2025, 11, 1),
        period_end=date(2026, 10, 31),
        status="in_progress",
    )
    return [empty_2023, summary_2024, summary_2025, current_2026]


class HistoryWrappedTests(unittest.IsolatedAsyncioTestCase):
    def test_completed_rows_support_space_key_activation(self):
        history_script = Path("static/js/history.js").read_text()
        self.assertIn('document.querySelectorAll("[data-wrapped-link]")', history_script)
        self.assertIn('if (event.key !== " ") return;', history_script)
        self.assertIn("link.click();", history_script)

    def test_availability_exposes_completed_omits_empty_and_keeps_current(self):
        with patch.object(application.WrappedService, "generate_for_user", return_value=wrapped_summaries()):
            context = application.history_wrapped_context({"ra_username": "Player"})
        self.assertEqual(context["in_progress"].wrapped_year, 2026)
        self.assertEqual(
            [entry["summary"].wrapped_year for entry in context["completed"]],
            [2025, 2024],
        )

    def test_selected_history_user_is_exact_and_does_not_fall_through(self):
        users = [
            {"ra_username": "First", "ra_ulid": "ONE"},
            {"ra_username": "Second", "ra_ulid": "TWO"},
        ]
        self.assertEqual(application.select_history_user(users, "second")["ra_username"], "Second")
        self.assertEqual(application.select_history_user(users, "TWO")["ra_username"], "Second")
        self.assertIsNone(application.select_history_user(users, "Missing"))

    def test_history_template_shows_progress_completed_links_and_existing_history(self):
        with patch.object(application.WrappedService, "generate_for_user", return_value=wrapped_summaries()):
            entries = application.history_wrapped_context({"ra_username": "Player"})
        markup = application.templates.get_template("history.html").render(
            weeks=[],
            weeks_page_size=5,
            has_more_weeks=False,
            selected_week_start=None,
            selected_week_label="No completed weeks",
            rankings=[],
            played_game_users=[],
            summary={
                "achievements_display": "0", "hardcore_points_display": "0",
                "retro_points_display": "0", "beaten_display": "—", "masteries_display": "—",
            },
            backfill_pending=False,
            history_users=[{"ra_username": "Player", "display_name": "Player"}],
            selected_history_user={"ra_username": "Player", "display_name": "Player"},
            wrapped_in_progress=entries["in_progress"],
            wrapped_completed=entries["completed"],
        )
        self.assertIn("Completed Weeks", markup)
        self.assertIn("2026", markup)
        self.assertIn("In progress", markup)
        self.assertIn('<a class="history-wrapped-card history-wrapped-card--complete', markup)
        self.assertIn('href="/history/wrapped/2025?user=Player" data-wrapped-link', markup)
        self.assertIn('href="/history/wrapped/2024?user=Player" data-wrapped-link', markup)
        self.assertNotIn('/history/wrapped/2023', markup)
        progress_markup = markup.split('history-wrapped-card--progress', 1)[1].split("</article>", 1)[0]
        self.assertNotIn("href=", progress_markup)
        self.assertNotIn("data-wrapped-link", progress_markup)
        self.assertIn("Game of the year", markup)
        self.assertIn("Top console", markup)
        self.assertIn("history-wrapped-card--theme-1", markup)
        self.assertIn("history-wrapped-card--theme-0", markup)
        self.assertIn("history-wrapped-card--theme-4", markup)

    async def test_local_route_renders_requested_tracked_users_year(self):
        _, _, summary, plan = prototype_samples()
        users = [
            {"ra_username": "First", "ra_ulid": "ONE"},
            {"ra_username": "Second", "ra_ulid": "TWO"},
        ]
        with (
            patch.object(application, "history_user_options", return_value=users),
            patch.object(application, "wrapped_user_year_context", return_value={"summary": summary, "plan": plan}) as build,
            patch.object(application, "wrapped_page_response", side_effect=lambda request, context, **kwargs: {**context, **kwargs}),
        ):
            response = await application.history_wrapped(request=None, year=2025, user="Second")
        build.assert_called_once_with("Second", 2025)
        self.assertEqual(response["summary"], summary)
        self.assertEqual(response["history_url"], "/history?user=Second")

    async def test_local_route_rejects_invalid_user_and_unavailable_year(self):
        users = [{"ra_username": "First", "ra_ulid": "ONE"}]
        with patch.object(application, "history_user_options", return_value=users):
            with self.assertRaises(HTTPException) as invalid:
                await application.history_wrapped(request=None, year=2025, user="Second")
        self.assertEqual(invalid.exception.status_code, 404)

        with (
            patch.object(application, "history_user_options", return_value=users),
            patch.object(
                application,
                "wrapped_user_year_context",
                side_effect=HTTPException(status_code=404, detail="not available"),
            ),
        ):
            with self.assertRaises(HTTPException) as unavailable:
                await application.history_wrapped(request=None, year=2023, user="First")
        self.assertEqual(unavailable.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
