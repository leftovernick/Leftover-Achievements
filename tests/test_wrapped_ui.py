import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import app as application
from services.wrapped import GenreMetric, WrappedService
from services.wrapped_story import WrappedStorySelector
from tests.test_wrapped import FakeDatabase, complete_rows, day, game


def prototype_samples():
    rows = complete_rows(start=date(2023, 11, 1), end=date(2025, 11, 1))
    metadata = {1: {
        "game_title": "Prototype Game", "console": "PlayStation 2", "genre": "RPG",
        "image_box_art": "https://example.test/prototype-cover.png",
    }}
    for index in range(15):
        active_date = date(2024, 7, 7) + timedelta(days=index)
        rows[active_date.replace(day=1).isoformat()]["days"][active_date.isoformat()] = day(
            4, 20, 40, [game(1, "Prototype Game", 4, 20, 40, "PlayStation 2")],
        )
    for index in range(60):
        active_date = date(2025, 1, 6) + timedelta(days=index)
        rows[active_date.replace(day=1).isoformat()]["days"][active_date.isoformat()] = day(
            2, 10, 20, [game(1, "Prototype Game", 2, 10, 20, "PlayStation 2")],
        )
    database = FakeDatabase(rows, metadata=metadata)
    service = WrappedService(database)
    now = datetime(2025, 11, 2, 12, tzinfo=timezone.utc)
    summary_2024 = service.generate_year("Player", 2024, now)
    summary_2025 = service.generate_year("Player", 2025, now)
    selector = WrappedStorySelector()
    return (
        summary_2024,
        selector.build_plan(summary_2024),
        summary_2025,
        selector.build_plan(summary_2025, summary_2024),
    )


def render(summary, plan, wrapped_history_url=None):
    return application.templates.get_template("wrapped.html").render(
        summary=summary,
        plan=plan,
        available_prototype_years=(2024, 2025),
        wrapped_history_url=wrapped_history_url,
        wrapped_css_version=1,
        wrapped_js_version=1,
    )


class WrappedPrototypeUITests(unittest.IsolatedAsyncioTestCase):
    async def test_development_route_renders_wrapped_template(self):
        summary_2024, plan_2024, _, _ = prototype_samples()
        with (
            patch.object(application, "wrapped_prototype_context", return_value={"summary": summary_2024, "plan": plan_2024}),
            patch.object(application.templates, "TemplateResponse", side_effect=lambda **kwargs: kwargs),
        ):
            response = await application.wrapped_prototype(request=None, year=2024)
        self.assertEqual(response["name"], "wrapped.html")
        self.assertEqual(response["context"]["plan"].wrapped_year, 2024)

    async def test_2024_and_2025_plans_render_every_returned_card(self):
        summary_2024, plan_2024, summary_2025, plan_2025 = prototype_samples()
        for summary, plan in ((summary_2024, plan_2024), (summary_2025, plan_2025)):
            with self.subTest(year=plan.wrapped_year):
                markup = render(summary, plan)
                self.assertEqual(markup.count("data-story-card"), len(plan.cards))
                for story_card in plan.cards:
                    self.assertIn(f'data-card-type="{story_card.type}"', markup)

    async def test_wrapped_years_use_the_five_theme_cycle(self):
        summary_2024, plan_2024, summary_2025, plan_2025 = prototype_samples()
        self.assertIn('class="wrapped-page wrapped-theme-4"', render(summary_2024, plan_2024))
        self.assertIn('class="wrapped-page wrapped-theme-0"', render(summary_2025, plan_2025))

    async def test_monthly_chart_scales_the_busiest_month_to_full_height(self):
        _, _, summary, plan = prototype_samples()
        markup = render(summary, plan)
        monthly_markup = markup.split('data-card-type="monthly_pattern"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="month-column is-busiest" style="--month-share: 100.0"', monthly_markup)

    async def test_recap_point_signs_follow_the_value(self):
        _, _, summary, plan = prototype_samples()
        recap = next(item for item in plan.cards if item.type == "final_recap")
        recap.headline_data["hardcore_points"] = -25
        recap.headline_data["retro_points"] = 0
        markup = render(summary, plan).split('data-card-type="final_recap"', 1)[1]
        self.assertIn('<strong>-25 <small>(0)</small></strong>', markup)
        self.assertNotIn("+-25", markup)
        self.assertNotIn("(+0)", markup)

    async def test_omitted_optional_cards_leave_no_markup(self):
        rows = complete_rows(start=date(2025, 11, 1), end=date(2026, 11, 1))
        rows["2026-01-01"]["days"]["2026-01-05"] = day(
            10, 50, 100, [game(1, "No Metadata", 10, 50, 100)],
        )
        summary = WrappedService(FakeDatabase(rows)).generate_year(
            "Player", 2026, datetime(2026, 11, 2, 12, tzinfo=timezone.utc),
        )
        plan = WrappedStorySelector().build_plan(summary)
        markup = render(summary, plan)
        for omitted in ("genre", "mastery", "special_highlight", "year_over_year"):
            self.assertNotIn(f'data-card-type="{omitted}"', markup)

    async def test_refined_cards_use_cached_art_and_profile_data(self):
        _, _, summary, plan = prototype_samples()
        summary.details.games.append(replace(
            summary.details.games[0],
            game_id=2,
            title="Supporting Game",
            image="/support-icon.png",
            cover_image="https://example.test/support-cover.png",
            achievements=1,
        ))
        markup = render(summary, plan)
        self.assertIn('class="intro-art-stack"', markup)
        self.assertIn("https://example.test/prototype-cover.png", markup)
        self.assertIn('class="focus-art-field"', markup)
        self.assertIn('class="recap-art"', markup)
        recap_markup = markup.split('data-card-type="final_recap"', 1)[1]
        self.assertIn(
            'class="recap-art__hero" src="https://example.test/prototype-cover.png"',
            recap_markup,
        )
        self.assertIn('data-cover-console="PlayStation 2"', recap_markup)
        self.assertNotIn('class="recap-art__hero" src="/1.png"', recap_markup)
        self.assertIn('class="recap-art__support" src="/support-icon.png"', recap_markup)
        self.assertIn('class="recap-mobile-supports"', recap_markup)
        self.assertNotIn('class="recap-art__support" src="https://example.test/support-cover.png"', recap_markup)
        self.assertIn('class="recap-points"', recap_markup)
        self.assertIn("Hardcore Points", recap_markup)
        self.assertIn("RetroPoints", recap_markup)
        self.assertIn("+600", recap_markup)
        self.assertIn("(1,200)", recap_markup)
        self.assertNotIn("(+1,200)", recap_markup)
        self.assertIn("Wrapped for", markup)
        self.assertIn(summary.canonical_username, markup)

    async def test_genre_card_limits_the_visible_ranked_field(self):
        _, _, summary, _ = prototype_samples()
        genre_rows = [
            GenreMetric(f"Genre {index}", 20 - index, 16 - index)
            for index in range(12)
        ]
        summary.genres.achievement_shares = genre_rows
        summary.genres.top_genre = genre_rows[0]
        plan = WrappedStorySelector().build_plan(summary)
        markup = render(summary, plan)
        genre_markup = markup.split('data-card-type="genre"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(genre_markup.count("<span style=\"--weight:"), 7)
        self.assertIn("12</strong> known genre labels", genre_markup)
        self.assertIn("+4 more beyond the leaders", genre_markup)
        self.assertNotIn("Genre 8 <small>", genre_markup)

    async def test_refined_art_cards_fall_back_without_images(self):
        _, _, summary, _ = prototype_samples()
        summary.avatar = None
        summary.details.games = [replace(game_detail, image=None, cover_image=None) for game_detail in summary.details.games]
        plan = WrappedStorySelector().build_plan(summary)
        markup = render(summary, plan)
        self.assertNotIn('class="intro-art-stack"', markup)
        self.assertIn("recap-layout recap-layout--no-art", markup)
        self.assertNotIn('src="None"', markup)

    async def test_local_wrapped_includes_return_to_history_link(self):
        _, _, summary, plan = prototype_samples()
        markup = render(summary, plan, "/history?user=Player")
        self.assertIn('class="wrapped-history-link"', markup)
        self.assertIn('href="/history?user=Player"', markup)
        self.assertIn("←", markup)

    async def test_final_recap_offers_horizontal_and_story_png_exports(self):
        _, _, summary, plan = prototype_samples()
        markup = render(summary, plan)
        self.assertIn('data-wrapped-export="landscape"', markup)
        self.assertIn('data-wrapped-export="story"', markup)
        self.assertIn("Save horizontal PNG", markup)
        self.assertIn("Save for Stories", markup)
        self.assertIn("/static/vendor/html2canvas.min.js", markup)

    async def test_final_recap_renders_all_five_headline_metrics(self):
        _, _, summary, plan = prototype_samples()
        recap = next(item for item in plan.cards if item.type == "final_recap")
        recap.headline_data["beaten"] = 7
        recap_markup = render(summary, plan).split('data-card-type="final_recap"', 1)[1]
        for label in ("achievements", "games", "active days", "beaten", "masteries"):
            self.assertIn(f"<span>{label}</span>", recap_markup)
        self.assertEqual(recap_markup.count('<p class="recap-stat'), 5)
        self.assertEqual(recap_markup.count('recap-stat--completion'), 2)

    async def test_final_recap_marks_long_game_titles_for_compact_spacing(self):
        _, _, summary, plan = prototype_samples()
        recap = next(item for item in plan.cards if item.type == "final_recap")
        recap.headline_data["top_game"]["title"] = "Pokémon Yellow Version: Special Pikachu Edition"
        recap_markup = render(summary, plan).split('data-card-type="final_recap"', 1)[1]
        self.assertIn(
            '<dd class="recap-leader-value--long">Pokémon Yellow Version: Special Pikachu Edition</dd>',
            recap_markup,
        )

    async def test_year_at_a_glance_renders_effective_beaten_with_existing_metrics(self):
        _, _, summary, plan = prototype_samples()
        glance = next(item for item in plan.cards if item.type == "year_at_a_glance")
        glance.headline_data["beaten"] = 7
        glance_markup = render(summary, plan).split('data-card-type="year_at_a_glance"', 1)[1].split("</section>", 1)[0]
        self.assertIn("One year in five numbers", glance_markup)
        for value, label in ((glance.headline_data["active_days"], "active days"),
                             (glance.headline_data["progress_games"], "games"),
                             (glance.headline_data["consoles"], "consoles"),
                             (7, "beaten"),
                             (glance.headline_data["masteries"], "masteries")):
            self.assertIn(f"<strong>{value}</strong><span>{label}</span>", glance_markup)


if __name__ == "__main__":
    unittest.main()
