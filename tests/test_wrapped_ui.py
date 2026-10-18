import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import app as application
from services.wrapped import GenreMetric, WrappedService
from services.wrapped_story import WrappedStorySelector
from tests.test_wrapped import FakeDatabase, complete_rows, day, game
from tests.test_wrapped_story import make_summary


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


def render(summary, plan, wrapped_history_url=None, **extra_context):
    context = dict(
        summary=summary,
        plan=plan,
        available_prototype_years=(2024, 2025),
        wrapped_history_url=wrapped_history_url,
        wrapped_css_version=1,
        wrapped_js_version=1,
        slide_result_previews=application._slide_result_groups(plan),
        selected_slide_result="",
        selected_slide_type="",
        selected_slide_variant="",
    )
    context.update(extra_context)
    return application.templates.get_template("wrapped.html").render(**context)


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
        self.assertEqual(response["context"]["available_prototype_years"], (2024, 2025, 2026))

    async def test_development_context_treats_2026_wrapped_as_final(self):
        rows = complete_rows(start=date(2025, 11, 1), end=date(2026, 10, 1))
        rows["2026-01-01"]["days"]["2026-01-05"] = day(
            10, 50, 100, [game(1, "Prototype Game", 10, 50, 100)],
        )
        now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        rows["2026-10-01"]["covered_through"] = now.isoformat()
        database = FakeDatabase(rows)
        summary = WrappedService(database).generate_year("Player", 2026, now)
        with (
            patch.object(application, "db", database),
            patch.object(application, "WrappedService") as wrapped_service,
        ):
            wrapped_service.return_value.generate_for_user.return_value = [summary]
            context = application.wrapped_prototype_context(2026)

        self.assertEqual(context["summary"].status, "final")
        self.assertEqual(context["plan"].status, "final")
        self.assertNotIn("period_in_progress", context["summary"].coverage.flags)

    async def test_local_history_treats_2026_wrapped_as_complete(self):
        rows = complete_rows(start=date(2025, 11, 1), end=date(2026, 10, 1))
        rows["2026-01-01"]["days"]["2026-01-05"] = day(
            10, 50, 100, [game(1, "Prototype Game", 10, 50, 100)],
        )
        now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
        rows["2026-10-01"]["covered_through"] = now.isoformat()
        database = FakeDatabase(rows)
        summary = WrappedService(database).generate_year("Player", 2026, now)
        with (
            patch.object(application, "db", database),
            patch.object(application, "WrappedService") as wrapped_service,
        ):
            wrapped_service.return_value.generate_for_user.return_value = [summary]
            history = application.history_wrapped_context({"ra_username": "Player"})
            context = application.wrapped_user_year_context("Player", 2026)

        self.assertIsNone(history["in_progress"])
        self.assertEqual(history["completed"][0]["summary"].wrapped_year, 2026)
        self.assertEqual(context["summary"].status, "final")
        self.assertEqual(context["plan"].status, "final")

    async def test_2024_and_2025_plans_render_every_returned_card(self):
        summary_2024, plan_2024, summary_2025, plan_2025 = prototype_samples()
        for summary, plan in ((summary_2024, plan_2024), (summary_2025, plan_2025)):
            with self.subTest(year=plan.wrapped_year):
                markup = render(summary, plan)
                self.assertEqual(markup.count("data-story-card"), len(plan.cards))
                for story_card in plan.cards:
                    self.assertIn(f'data-card-type="{story_card.type}"', markup)

    async def test_development_result_selector_groups_results_by_slide(self):
        _, _, summary, plan = prototype_samples()
        markup = render(summary, plan)
        selector_markup = markup.split('data-slide-result-preview', 1)[1].split("</select>", 1)[0]

        self.assertEqual(selector_markup.count("<optgroup"), len(plan.cards))
        for index, story_card in enumerate(plan.cards, start=1):
            label = f"{index:02d} · {story_card.type.replace('_', ' ')}"
            self.assertIn(label, selector_markup)
            self.assertIn(f'value="{story_card.type}|"', selector_markup)
        self.assertIn('value="game_focus|mixed_year"', selector_markup)
        self.assertIn('value="game_focus|broad_year"', selector_markup)

    async def test_wrapped_years_use_the_five_theme_cycle(self):
        summary_2024, plan_2024, summary_2025, plan_2025 = prototype_samples()
        self.assertIn('class="wrapped-page wrapped-theme-4"', render(summary_2024, plan_2024))
        self.assertIn('class="wrapped-page wrapped-theme-0"', render(summary_2025, plan_2025))

    async def test_monthly_chart_scales_the_busiest_month_to_full_height(self):
        _, _, summary, plan = prototype_samples()
        markup = render(summary, plan)
        monthly_markup = markup.split('data-card-type="monthly_pattern"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="month-column is-busiest" style="--month-share: 100.0"', monthly_markup)

    async def test_biggest_day_shows_achievements_points_and_retropoints(self):
        summary, _ = make_summary([12])
        biggest_day = summary.details.days[0]
        summary.details.days[0] = replace(
            biggest_day,
            hardcore_points=610,
            retro_points=1203,
        )
        plan = WrappedStorySelector().build_plan(summary)
        markup = render(summary, plan)
        day_markup = markup.split('data-card-type="biggest_day"', 1)[1].split("</section>", 1)[0]
        self.assertIn("<span>12</span> achievements", day_markup)
        self.assertIn("<strong>610</strong><span>points</span>", day_markup)
        self.assertIn("<strong>1,203</strong><span>RetroPoints</span>", day_markup)

    async def test_development_selector_previews_every_special_highlight(self):
        summary, _ = make_summary([120])
        plan = WrappedStorySelector().build_plan(summary)
        context = {"summary": summary, "plan": plan}

        self.assertNotIn(
            "major_console_dominance",
            [variant for variant, _, _ in application.SPECIAL_HIGHLIGHT_PREVIEWS],
        )
        self.assertNotIn(
            "extreme_genre_dominance",
            [variant for variant, _, _ in application.SPECIAL_HIGHLIGHT_PREVIEWS],
        )
        self.assertNotIn(
            "very_broad_genre_year",
            [variant for variant, _, _ in application.SPECIAL_HIGHLIGHT_PREVIEWS],
        )
        self.assertNotIn(
            "broad_game_variety",
            [variant for variant, _, _ in application.SPECIAL_HIGHLIGHT_PREVIEWS],
        )

        for variant, _, _ in application.SPECIAL_HIGHLIGHT_PREVIEWS:
            application.apply_special_highlight_preview(context, variant)
            special = next(card for card in plan.cards if card.type == "special_highlight")
            self.assertEqual(special.variant, variant)
            self.assertTrue(special.supporting_data["preview"])
            self.assertIn("title", special.supporting_data["presentation"])

        application.apply_wrapped_slide_result_preview(
            context, "special_highlight", "unusual_retropoint_day",
        )
        markup = render(summary, plan, **{
            key: context[key]
            for key in (
                "slide_result_previews", "selected_slide_result", "selected_slide_type",
                "selected_slide_variant", "initial_card_type",
            )
        })
        special_selector = markup.split('data-slide-result-preview', 1)[1].split("</select>", 1)[0]
        self.assertIn('value="special_highlight|unusual_retropoint_day" selected', special_selector)
        self.assertIn('data-initial-card-type="special_highlight"', markup)

    async def test_development_result_preview_changes_layout_and_data(self):
        _, _, summary, plan = prototype_samples()
        context = {"summary": summary, "plan": plan}

        application.apply_wrapped_slide_result_preview(context, "game_focus", "mixed_year")
        card = next(item for item in plan.cards if item.type == "game_focus")
        self.assertEqual(card.variant, "mixed_year")
        self.assertEqual(card.headline_data["top_10_share"], 63.0)
        self.assertEqual(context["initial_card_type"], "game_focus")

        application.apply_wrapped_slide_result_preview(context, "activity_pattern", "notable_comeback")
        card = next(item for item in plan.cards if item.type == "activity_pattern")
        self.assertEqual(card.variant, "notable_comeback")
        self.assertEqual(card.headline_data["days"], 44)
        self.assertIn("activity_after", card.headline_data)

    async def test_broad_year_chart_shows_achievement_share_beyond_the_top_ten(self):
        _, _, summary, plan = prototype_samples()
        context = {"summary": summary, "plan": plan}
        application.apply_wrapped_slide_result_preview(context, "game_focus", "broad_year")

        markup = render(summary, plan)
        focus_markup = markup.split('data-card-type="game_focus"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="broad-focus-evidence"', focus_markup)
        self.assertIn("Top 10 games", focus_markup)
        self.assertIn("Every other game", focus_markup)
        self.assertIn("accounted for 44.0%", focus_markup)
        self.assertIn("accounted for 56.0%", focus_markup)
        field_markup = focus_markup.split('class="broad-focus-field"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(field_markup.count("<i"), 20)

    async def test_special_previews_show_variant_specific_visual_evidence(self):
        summary, _ = make_summary([25] * 6)
        plan = WrappedStorySelector().build_plan(summary)
        context = {"summary": summary, "plan": plan}

        application.apply_special_highlight_preview(context, "mastery_sprint")
        mastery_markup = render(summary, plan).split('data-card-type="special_highlight"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="special-mastery-games"', mastery_markup)
        self.assertIn("Jul 19–20, 2026", mastery_markup)
        self.assertIn("Game 1", mastery_markup)

        application.apply_special_highlight_preview(context, "extreme_month_dominance")
        month_markup = render(summary, plan).split('data-card-type="special_highlight"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="special-month-card"', month_markup)
        self.assertIn("<strong>July</strong>", month_markup)
        self.assertIn("<span>2026</span>", month_markup)

        application.apply_special_highlight_preview(context, "extreme_single_game_dominance")
        game_markup = render(summary, plan).split('data-card-type="special_highlight"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="special-game-card"', game_markup)
        self.assertIn("Game 1", game_markup)
        self.assertIn("of your year’s achievements", game_markup)
        self.assertIn("All other games · 58.2%", game_markup)
        self.assertIn('class="special-game-share"', game_markup)
        self.assertIn('style="--game-share: 41.8%"', game_markup)

        application.apply_special_highlight_preview(context, "huge_comeback")
        comeback_markup = render(summary, plan).split('data-card-type="special_highlight"', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="special-comeback-card"', comeback_markup)
        self.assertIn("213", comeback_markup)
        self.assertIn("quiet days", comeback_markup)
        self.assertIn("Activity returned", comeback_markup)
        self.assertIn("Sep 3, 2026", comeback_markup)
        self.assertIn("First 8 weeks back", comeback_markup)
        self.assertIn("Sep 24–Sep 30 · 45 achievements · 5 active days", comeback_markup)
        self.assertEqual(comeback_markup.count("--rise-level:"), 8)

    async def test_recap_point_signs_follow_the_value(self):
        _, _, summary, plan = prototype_samples()
        recap = next(item for item in plan.cards if item.type == "final_recap")
        recap.headline_data["hardcore_points"] = -25
        recap.headline_data["retro_points"] = 0
        markup = render(summary, plan).split('data-card-type="final_recap"', 1)[1]
        self.assertIn('<strong>-25 <small>(0)</small></strong>', markup)
        self.assertNotIn("+-25", markup)
        self.assertNotIn("(+0)", markup)

    async def test_year_over_year_copy_and_signs_follow_the_variant(self):
        _, _, summary, plan = prototype_samples()
        yoy = next(item for item in plan.cards if item.type == "year_over_year")
        yoy.variant = "quieter_year"
        yoy.supporting_data["changes"]["hardcore_achievements"] = {
            "previous": 100,
            "current": 70,
            "raw_change": -30,
            "percent_change": -30.0,
        }
        markup = render(summary, plan)
        yoy_markup = markup.split('data-card-type="year_over_year"', 1)[1].split("</section>", 1)[0]
        self.assertIn("A quieter year.", yoy_markup)
        self.assertIn('<b class="is-down">-30.0%</b>', yoy_markup)
        self.assertNotIn("Everything got bigger.", yoy_markup)
        self.assertNotIn("+-30.0%", yoy_markup)

    async def test_console_card_explains_split_leaders(self):
        _, _, summary, plan = prototype_samples()
        console = next(item for item in plan.cards if item.type == "console")
        console.supporting_data["console_sweep"] = False
        console.supporting_data["split_console_leaders"] = True
        console.supporting_data["leader_groups"] = [
            {"console": "Wii", "metrics": ["achievements earned"]},
            {"console": "Events", "metrics": ["games played"]},
            {"console": "PlayStation 2", "metrics": ["points"]},
        ]
        markup = render(summary, plan)
        console_markup = markup.split('data-card-type="console"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Split leaders", console_markup)
        self.assertIn("<dt>Wii</dt><dd>achievements earned</dd>", console_markup)
        self.assertIn("<dt>Events</dt><dd>games played</dd>", console_markup)
        self.assertIn("<dt>PlayStation 2</dt><dd>points</dd>", console_markup)

    async def test_weekday_activity_card_explains_and_compares_the_pattern(self):
        _, _, summary, plan = prototype_samples()
        activity = next(item for item in plan.cards if item.type == "activity_pattern")
        activity.variant = "strong_weekday_pattern"
        activity.headline_data = {
            "weekday": "Monday",
            "share": 35.3,
            "achievements": 677,
            "active_days": 29,
        }
        activity.supporting_data["weekday_breakdown"] = [
            {
                "weekday": weekday,
                "short_label": weekday[:3],
                "achievements": achievements,
                "active_days": 1,
                "share": 0,
                "relative_percent": achievements / 6.77,
            }
            for weekday, achievements in (
                ("Monday", 677), ("Tuesday", 180), ("Wednesday", 199),
                ("Thursday", 113), ("Friday", 170), ("Saturday", 81), ("Sunday", 500),
            )
        ]
        markup = render(summary, plan)
        activity_markup = markup.split('data-card-type="activity_pattern"', 1)[1].split("</section>", 1)[0]
        self.assertIn("<span>Monday</span> led your week.", activity_markup)
        self.assertIn("677 achievements across 29 active Mondays", activity_markup)
        self.assertIn("35.3% of everything you earned", activity_markup)
        self.assertEqual(activity_markup.count("--weekday-level:"), 7)

    async def test_streak_activity_card_celebrates_the_run_with_dates_and_daily_markers(self):
        _, _, summary, plan = prototype_samples()
        activity = next(item for item in plan.cards if item.type == "activity_pattern")
        activity.variant = "notable_streak"
        activity.headline_data = {
            "start_date": date(2026, 9, 11),
            "end_date": date(2026, 9, 24),
            "days": 14,
        }
        activity.supporting_data["streak_achievements"] = 257
        markup = render(summary, plan)
        activity_markup = markup.split('data-card-type="activity_pattern"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Longest run of the year", activity_markup)
        self.assertIn("You kept it going.", activity_markup)
        self.assertIn("257</strong> achievements earned without missing a day", activity_markup)
        self.assertIn("14 days in a row", activity_markup)
        self.assertIn("Sep 11", activity_markup)
        self.assertIn("Sep 24", activity_markup)
        self.assertEqual(activity_markup.count('aria-hidden="true"'), 14)

    async def test_mastery_card_lists_every_mastery_with_dates_not_times(self):
        base = datetime(2026, 1, 5, 20, tzinfo=timezone.utc)
        masteries = [
            {
                "game_id": index + 1,
                "game_title": f"Mastered Game {index + 1}",
                "game_image": f"/{index + 1}.png",
                "date": (base + timedelta(days=index * 10)).isoformat(),
            }
            for index in range(6)
        ]
        summary, _ = make_summary([10] * 6, masteries=masteries)
        plan = WrappedStorySelector().build_plan(summary)
        markup = render(summary, plan)
        mastery_markup = markup.split('data-card-type="mastery"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Every mastery from the year, in order", mastery_markup)
        self.assertEqual(mastery_markup.count("<article>"), 6)
        for index in range(1, 7):
            self.assertIn(f"Game {index}", mastery_markup)
        self.assertIn("Jan 5", mastery_markup)
        self.assertNotIn("AM", mastery_markup)
        self.assertNotIn("PM", mastery_markup)

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
        for omitted in ("genre", "mastery", "year_over_year"):
            self.assertNotIn(f'data-card-type="{omitted}"', markup)

    async def test_refined_cards_use_cached_art_and_profile_data(self):
        _, _, summary, plan = prototype_samples()
        summary.details.games[0] = replace(
            summary.details.games[0],
            image="/prototype-icon.png",
        )
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
        focus_markup = markup.split('data-card-type="game_focus"', 1)[1].split("</section>", 1)[0]
        self.assertIn('src="/prototype-icon.png"', focus_markup)
        self.assertNotIn('src="https://example.test/prototype-cover.png"', focus_markup)
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

    async def test_mixed_game_focus_shows_shared_spotlight_and_concentration_split(self):
        summary, _ = make_summary([6] * 10 + [4] * 10)
        plan = WrappedStorySelector().build_plan(summary)
        focus = next(item for item in plan.cards if item.type == "game_focus")
        self.assertEqual(focus.variant, "mixed_year")

        markup = render(summary, plan)
        focus_markup = markup.split('data-card-type="game_focus"', 1)[1].split("</section>", 1)[0]
        self.assertIn("The spotlight stayed shared.", focus_markup)
        self.assertIn("no single game took it over", focus_markup)
        self.assertIn('class="mixed-focus-evidence"', focus_markup)
        self.assertIn("Top 10 games", focus_markup)
        self.assertIn("All other games", focus_markup)
        self.assertIn('style="--top-ten-share: 60.0%"', focus_markup)

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

    async def test_special_highlight_explains_the_retropoint_multiplier(self):
        _, _, summary, plan = prototype_samples()
        special = replace(
            plan.cards[0],
            id="special-highlight",
            type="special_highlight",
            variant="unusual_retropoint_day",
            headline_data={
                "date": date(2026, 10, 10),
                "hardcore_points": 23,
                "retro_points": 517,
                "ratio": 517 / 23,
            },
            supporting_data={
                "presentation": {
                    "eyebrow": "Oct 10, 2026",
                    "title": "Rarity did the heavy lifting.",
                    "body": "That day’s achievements were valued far above their base score.",
                    "primary": "22.5×",
                    "primary_label": "the base point value",
                    "facts": [
                        {"label": "Base points", "value": "23"},
                        {"label": "RetroPoints", "value": "517"},
                    ],
                    "conversion": True,
                },
                "impressiveness_rank": 11,
            },
        )
        plan.cards = [special]

        markup = render(summary, plan)

        self.assertIn("Rarity did the heavy lifting.", markup)
        self.assertIn("22.5×", markup)
        self.assertIn("the base point value", markup)
        self.assertIn("<span>Base points</span><strong>23</strong>", markup)
        self.assertIn("<span>RetroPoints</span><strong>517</strong>", markup)


if __name__ == "__main__":
    unittest.main()
