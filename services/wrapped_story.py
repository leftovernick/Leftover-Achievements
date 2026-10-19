"""Deterministic story-card selection for locally generated Wrapped summaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from services.wrapped import WrappedGameDetail, WrappedSummary


StoryConfidence = Literal["high", "medium", "low", "provisional"]
NORMAL_CARD_COUNT_MIN = 11
NORMAL_CARD_COUNT_MAX = 14


@dataclass
class WrappedStoryCard:
    id: str
    type: str
    variant: str
    order: int
    required: bool
    status: str
    headline_data: dict = field(default_factory=dict)
    supporting_data: dict = field(default_factory=dict)
    reason_selected: str = ""
    confidence: StoryConfidence = "high"
    data_quality_flags: list[str] = field(default_factory=list)


@dataclass
class WrappedStoryPlan:
    wrapped_year: int
    status: str
    cards: list[WrappedStoryCard]
    generated_at: datetime
    data_quality_flags: list[str] = field(default_factory=list)


def _metric_game(game: WrappedGameDetail) -> dict:
    return {
        "game_id": game.game_id,
        "title": game.title,
        "image": game.image,
        "console": game.console,
        "achievements": game.achievements,
        "hardcore_points": game.hardcore_points,
        "retro_points": game.retro_points,
        "active_days": game.active_days,
        "genres": list(game.genres),
    }


def _rank_games(summary: WrappedSummary, field_name: str) -> list[WrappedGameDetail]:
    return sorted(
        summary.details.games,
        key=lambda game: (
            -int(getattr(game, field_name)), game.first_active_date,
            game.title.casefold(), game.game_id,
        ),
    )


def _percent(value: int | float, total: int | float) -> float:
    return value / total * 100 if total else 0.0


def _known_console_leader(rows) -> str | None:
    return next((row.console for row in rows if row.console != "Unknown"), None)


def _display_date(value: date | datetime) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def special_highlight_presentation(variant: str, data: dict) -> dict:
    """Turn any qualifying special fact into one consistent visual story."""
    if variant == "mastery_sprint":
        count = data["largest_cluster_size"]
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        start_day = start_date.date() if isinstance(start_date, datetime) else start_date
        end_day = end_date.date() if isinstance(end_date, datetime) else end_date
        if start_day and end_day and start_day != end_day:
            date_label = f"{start_date:%b} {start_date.day}–{end_date.day}, {end_date.year}"
        elif start_date:
            date_label = _display_date(start_date)
        else:
            date_label = "Inside one 24-hour window"
        return {
            "eyebrow": "Mastery sprint",
            "title": "A mastery run with no brakes.",
            "body": "Every game mastered during the run, in order.",
            "primary": f"{count}", "primary_label": "masteries in 24 hours",
            "date_label": date_label,
            "facts": [],
        }
    if variant == "extreme_month_dominance":
        month_date = date.fromisoformat(data["month"])
        return {
            "eyebrow": "Month dominance",
            "title": "One month owned the year.",
            "body": "A majority of the year’s achievements arrived in this one month.",
            "primary": f'{data["share"]:.1f}%', "primary_label": "of the year’s achievements",
            "month_name": month_date.strftime("%B"),
            "month_year": str(month_date.year),
            "facts": [],
        }
    if variant == "extreme_single_game_dominance":
        return {
            "eyebrow": data["game"]["title"],
            "title": "One game took over.",
            "body": "No other game came close to shaping the year this much.",
            "primary": f'{data["share"]:.1f}%', "primary_label": "of your year’s achievements",
            "other_share": f'{100 - data["share"]:.1f}%',
            "game_achievements": f'{data["game"]["achievements"]:,}',
            "facts": [],
        }
    if variant == "huge_comeback":
        quiet_start = data.get("start_date")
        quiet_end = data.get("end_date")
        return_date = data.get("activity_after")
        return {
            "eyebrow": "The comeback",
            "title": "Then you lit it back up.",
            "body": "A long quiet stretch ended with a clean return.",
            "primary": f'{data["days"]:,}', "primary_label": "quiet days",
            "quiet_range": (
                f"{_display_date(quiet_start)}–{_display_date(quiet_end)}"
                if quiet_start and quiet_end else None
            ),
            "return_date": _display_date(return_date) if return_date else None,
            "facts": [],
        }
    return {
        "eyebrow": _display_date(data["date"]),
        "title": "Rarity did the heavy lifting.",
        "body": "That day’s achievements were valued far above their base score.",
        "primary": f'{data["ratio"]:.1f}×', "primary_label": "the base point value",
        "facts": [
            {"label": "Base points", "value": f'{data["hardcore_points"]:,}'},
            {"label": "RetroPoints", "value": f'{data["retro_points"]:,}'},
        ],
        "conversion": True,
    }


def _mastery_clusters(masteries) -> tuple[list[list], float | None]:
    ordered = sorted(masteries, key=lambda mastery: mastery.awarded_at)
    clusters = []
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end].awarded_at - ordered[index].awarded_at <= timedelta(hours=24):
            end += 1
        if end - index >= 2:
            clusters.append(ordered[index:end])
            index = end
        else:
            index += 1
    gaps = [
        (right.awarded_at - left.awarded_at).total_seconds()
        for left, right in zip(ordered, ordered[1:])
    ]
    return clusters, min(gaps) if gaps else None


def _longest_internal_gap(days):
    """Return inactivity strictly between two active Wrapped-period dates."""
    ordered = sorted(day.date for day in days)
    candidates = []
    for left, right in zip(ordered, ordered[1:]):
        gap_days = (right - left).days - 1
        if gap_days > 0:
            candidates.append({
                "start_date": left + timedelta(days=1),
                "end_date": right - timedelta(days=1),
                "days": gap_days,
                "activity_before": left,
                "activity_after": right,
            })
    return min(candidates, key=lambda gap: (-gap["days"], gap["start_date"])) if candidates else None


def comeback_weekly_activity(days, return_date: date, period_end: date, *, week_limit: int = 8) -> list[dict]:
    """Summarize the real calendar weeks immediately following a comeback."""
    weeks = []
    for index in range(week_limit):
        start_date = return_date + timedelta(days=index * 7)
        if start_date > period_end:
            break
        end_date = min(start_date + timedelta(days=6), period_end)
        matching_days = [day for day in days if start_date <= day.date <= end_date]
        weeks.append({
            "week": index + 1,
            "start_date": start_date,
            "end_date": end_date,
            "achievements": sum(day.achievements for day in matching_days),
            "active_days": len(matching_days),
        })

    peak = max((week["achievements"] for week in weeks), default=0)
    for week in weeks:
        week["relative_percent"] = _percent(week["achievements"], peak)
        week["is_peak"] = peak > 0 and week["achievements"] == peak
    return weeks


class WrappedStorySelector:
    """Turn one non-empty Wrapped summary into an ordered, presentation-neutral plan."""

    def build_plan(
        self,
        summary: WrappedSummary,
        previous: WrappedSummary | None = None,
        *,
        include_in_progress: bool = False,
    ) -> WrappedStoryPlan | None:
        if summary.headline.total_achievements == 0:
            return None
        if summary.status == "in_progress" and not include_in_progress:
            return None

        flags = list(dict.fromkeys(summary.coverage.flags))
        history_incomplete = "history_incomplete" in flags
        provisional = summary.status == "in_progress"
        cards = []

        def add(
            card_type: str,
            variant: str,
            *,
            required: bool,
            headline: dict | None = None,
            supporting: dict | None = None,
            reason: str,
            confidence: StoryConfidence | None = None,
            relevant_flags: list[str] | None = None,
        ):
            card_flags = list(dict.fromkeys(relevant_flags if relevant_flags is not None else flags))
            if confidence is None:
                confidence = "provisional" if provisional else ("low" if history_incomplete else "high")
            cards.append(WrappedStoryCard(
                id=f"wrapped-{summary.wrapped_year}-{card_type}",
                type=card_type,
                variant=variant,
                order=len(cards) + 1,
                required=required,
                status=summary.status,
                headline_data=headline or {},
                supporting_data=supporting or {},
                reason_selected=reason,
                confidence=confidence,
                data_quality_flags=card_flags,
            ))

        add(
            "intro", "standard", required=True,
            headline={
                "username": summary.canonical_username,
                "avatar": summary.avatar,
                "wrapped_year": summary.wrapped_year,
                "period_start": summary.period_start,
                "period_end": summary.period_end,
            },
            reason="Every non-empty Wrapped begins with identity and period context.",
            relevant_flags=[flag for flag in flags if flag == "period_in_progress"],
        )
        add(
            "headline_totals", "all_achievements_primary", required=True,
            headline={
                "total_achievements": summary.headline.total_achievements,
                "hardcore_achievements": summary.headline.hardcore_achievements,
                "softcore_achievements": summary.headline.softcore_achievements,
                "hardcore_points": summary.headline.hardcore_points,
                "softcore_points": summary.headline.softcore_points,
                "retro_points": summary.headline.retro_points,
                "primary_metric": "total_achievements",
            },
            reason="Headline totals are part of the stable story backbone.",
        )
        add(
            "year_at_a_glance", "standard", required=True,
            headline={
                "active_days": summary.headline.active_days,
                "progress_games": summary.headline.games_with_progress,
                "consoles": summary.headline.consoles_with_progress,
                "beaten": summary.headline.effective_beaten_games,
                "masteries": summary.headline.mastered_games,
            },
            reason="The annual breadth and activity summary is required for every non-empty year.",
        )

        has_hardcore = summary.headline.hardcore_achievements > 0
        has_softcore = summary.headline.softcore_achievements > 0
        metric_fields = {
            "achievements": "achievements",
            "active_days": "active_days",
        }
        if has_hardcore:
            metric_fields.update(
                hardcore_points="hardcore_points",
                retro_points="retro_points",
            )
        leaders = {name: _rank_games(summary, field)[0] for name, field in metric_fields.items()}
        leader_counts = {}
        for leader in leaders.values():
            leader_counts[leader.game_id] = leader_counts.get(leader.game_id, 0) + 1
        achievement_winner = leaders["achievements"]
        winner_count = leader_counts[achievement_winner.game_id]
        dominant_game_id, dominant_metric_wins = max(
            leader_counts.items(), key=lambda item: (item[1], item[0] == achievement_winner.game_id),
        )
        dominant_metric_game = next(game for game in leaders.values() if game.game_id == dominant_game_id)
        metric_count = len(metric_fields)
        if winner_count == metric_count:
            game_variant = "dominant_all_metrics"
        elif metric_count > 2 and max(leader_counts.values()) >= metric_count - 1:
            game_variant = "dominant_most_metrics"
        else:
            game_variant = "split_leaders"
        add(
            "game_of_the_year", game_variant, required=True,
            headline=_metric_game(achievement_winner),
            supporting={
                "leaders": {metric: _metric_game(game) for metric, game in leaders.items()},
                "achievement_winner_metric_wins": winner_count,
                "dominant_metric_game": _metric_game(dominant_metric_game),
                "dominant_metric_wins": dominant_metric_wins,
                "has_hardcore": has_hardcore,
                "has_softcore": has_softcore,
            },
            reason=(
                f"The achievement winner led all {metric_count} game metrics."
                if game_variant == "dominant_all_metrics"
                else f"{dominant_metric_game.title} led {dominant_metric_wins} of {metric_count} metrics; the achievement winner remains the primary game."
                if game_variant == "dominant_most_metrics"
                else f"The {metric_count} game metrics were meaningfully divided among multiple leaders."
            ),
        )

        total_achievements = summary.headline.total_achievements
        ranked_achievements = _rank_games(summary, "achievements")
        shares = {
            f"top_{count}_share": _percent(sum(game.achievements for game in ranked_achievements[:count]), total_achievements)
            for count in (1, 3, 5, 10)
        }
        top_ten_share = shares["top_10_share"]
        if top_ten_share >= 65:
            focus_variant = "focused_year"
        elif top_ten_share <= 50:
            focus_variant = "broad_year"
        else:
            focus_variant = "mixed_year"
        add(
            "game_focus", focus_variant, required=True,
            headline=shares,
            supporting={
                "single_game_dominance": shares["top_1_share"] >= 25,
                "extreme_single_game_dominance": shares["top_1_share"] >= 35,
            },
            reason=f"The top ten games supplied {top_ten_share:.1f}% of achievements.",
        )

        console_leaders = {
            "achievements": summary.consoles.top_by_achievements.console if summary.consoles.top_by_achievements else None,
            "progress_games": summary.consoles.top_by_games.console if summary.consoles.top_by_games else None,
        }
        if has_hardcore:
            combined_points_by_console = {}
            for rows in (summary.consoles.hardcore_points, summary.consoles.retro_points):
                for row in rows:
                    if row.console != "Unknown":
                        combined_points_by_console[row.console] = combined_points_by_console.get(row.console, 0) + row.value
            console_leaders["points"] = max(
                combined_points_by_console,
                key=combined_points_by_console.get,
                default=None,
            )
        top_console = console_leaders["achievements"]
        top_console_achievements = next(
            (row.value for row in summary.consoles.achievements if row.console == top_console), 0,
        )
        console_share = _percent(top_console_achievements, total_achievements)
        top_console_values = {
            "achievements": top_console_achievements,
            "progress_games": next((row.value for row in summary.consoles.unique_progress_games if row.console == top_console), 0),
            "hardcore_points": next((row.value for row in summary.consoles.hardcore_points if row.console == top_console), 0),
            "retro_points": next((row.value for row in summary.consoles.retro_points if row.console == top_console), 0),
        }
        console_sweep = len(set(console_leaders.values())) == 1
        split_console_leaders = len(set(console_leaders.values())) > 1
        leader_groups_by_console = {}
        console_metric_labels = [
            ("achievements", "achievements earned"),
            ("progress_games", "games played"),
        ]
        if has_hardcore:
            console_metric_labels.append(("points", "points"))
        for metric, label in console_metric_labels:
            leader_groups_by_console.setdefault(console_leaders[metric], []).append(label)
        leader_groups = [
            {"console": console, "metrics": metrics}
            for console, metrics in leader_groups_by_console.items()
        ]
        if console_share >= 50:
            dominance_level = "console_majority"
        elif console_share >= 35:
            dominance_level = "console_dominant"
        else:
            dominance_level = "console_leader"
        console_variant = dominance_level
        console_flags = []
        if console_sweep:
            console_flags.append("console_sweep")
        if split_console_leaders:
            console_flags.append("split_console_leaders")
        add(
            "console", console_variant, required=True,
            headline={"console": top_console, "achievement_share": console_share},
            supporting={
                "leaders": console_leaders,
                "top_console_values": top_console_values,
                "dominance_level": dominance_level,
                "console_sweep": console_sweep,
                "split_console_leaders": split_console_leaders,
                "leader_groups": leader_groups,
                "selection_flags": console_flags,
                "has_hardcore": has_hardcore,
            },
            reason=(f"One console led all {len(console_leaders)} categories." if console_sweep else f"Console leaders differed across the {len(console_leaders)} categories." if split_console_leaders else f"The achievement leader held {console_share:.1f}% of achievements."),
        )

        genre_eligible = summary.genres.coverage_percent >= 70 and not history_incomplete and bool(summary.genres.achievement_shares)
        genre_data = None
        if genre_eligible:
            genre_rows = summary.genres.achievement_shares
            top_share = genre_rows[0].share_percent
            if top_share >= 40:
                genre_variant = "genre_obsession"
            elif top_share >= 30:
                genre_variant = "genre_dominant"
            elif top_share >= 20:
                genre_variant = "genre_preference"
            else:
                genre_variant = "genre_varied"
            cumulative = 0.0
            reach = {50: None, 75: None}
            for index, row in enumerate(genre_rows, 1):
                cumulative += row.share_percent
                for threshold in reach:
                    if reach[threshold] is None and cumulative >= threshold:
                        reach[threshold] = index
            genre_data = {
                "top_genre": genre_rows[0].genre,
                "second_genre": genre_rows[1].genre if len(genre_rows) > 1 else None,
                "top_three": [asdict(row) for row in genre_rows[:3]],
                "top_genre_share": top_share,
                "top_two_share": sum(row.share_percent for row in genre_rows[:2]),
                "top_three_share": sum(row.share_percent for row in genre_rows[:3]),
                "known_genre_labels": len(genre_rows),
                "genres_to_50_percent": reach[50],
                "genres_to_75_percent": reach[75],
                "coverage_percent": summary.genres.coverage_percent,
                "unknown_achievement_share": summary.genres.unknown_achievement_share_percent,
            }
            add(
                "genre", genre_variant, required=False,
                headline={"genre": genre_rows[0].genre, "share": top_share},
                supporting=genre_data,
                reason=f"Genre coverage was {summary.genres.coverage_percent:.1f}%, meeting the 70% threshold.",
                confidence="provisional" if provisional else ("medium" if "genre_metadata_incomplete" in flags else "high"),
                relevant_flags=[flag for flag in flags if flag in {"genre_metadata_incomplete", "period_in_progress"}],
            )

        months = summary.details.months
        active_months = sum(month.achievements > 0 for month in months)
        busiest_month = min(months, key=lambda month: (-month.achievements, month.month))
        points_month = min(months, key=lambda month: (-month.hardcore_points, month.month))
        retro_month = min(months, key=lambda month: (-month.retro_points, month.month))
        busiest_share = _percent(busiest_month.achievements, total_achievements)
        if busiest_share >= 50:
            month_variant = "dominant_month"
        elif busiest_share >= 35:
            month_variant = "strong_month"
        elif active_months == 12 and busiest_share < 25:
            month_variant = "steady_year"
        elif active_months >= 9:
            month_variant = "active_most_year"
        elif active_months >= 4:
            month_variant = "seasonal_year"
        else:
            month_variant = "burst_year"
        add(
            "monthly_pattern", month_variant, required=True,
            headline={"busiest_month": busiest_month.month, "busiest_month_share": busiest_share},
            supporting={
                "months": [asdict(month) for month in months],
                "active_months": active_months,
                "zero_activity_months": 12 - active_months,
                "biggest_points_month": points_month.month,
                "biggest_retro_points_month": retro_month.month,
                "different_value_month": busiest_month.month != points_month.month or busiest_month.month != retro_month.month,
                "has_hardcore": has_hardcore,
            },
            reason=f"The busiest month supplied {busiest_share:.1f}% of annual achievements across {active_months} active months.",
        )

        days = summary.details.days
        biggest_day = min(days, key=lambda day: (-day.achievements, day.date))
        point_day = min(days, key=lambda day: (-day.hardcore_points, day.date))
        retro_day = min(days, key=lambda day: (-day.retro_points, day.date))
        if biggest_day.achievements >= 75:
            day_variant = "huge_day"
        elif biggest_day.achievements >= 40:
            day_variant = "big_day"
        else:
            day_variant = "active_day"
        add(
            "biggest_day", day_variant, required=True,
            headline={
                **asdict(biggest_day),
                "weekday": biggest_day.date.strftime("%A"),
                "games_active": len(biggest_day.active_game_ids),
            },
            supporting={
                "biggest_points_day": asdict(point_day),
                "biggest_retro_points_day": asdict(retro_day),
                "active_games": [
                    _metric_game(game)
                    for game in summary.details.games
                    if game.game_id in biggest_day.active_game_ids
                ],
                "has_hardcore": has_hardcore,
            },
            reason=f"The peak achievement day contained {biggest_day.achievements} achievements.",
        )

        weekday_totals = {index: {"achievements": 0, "active_days": 0} for index in range(7)}
        for day in days:
            values = weekday_totals[day.date.weekday()]
            values["achievements"] += day.achievements
            values["active_days"] += 1
        top_weekday_index = min(weekday_totals, key=lambda index: (-weekday_totals[index]["achievements"], index))
        top_weekday_share = _percent(weekday_totals[top_weekday_index]["achievements"], total_achievements)
        candidates = []
        streak = summary.activity.longest_achievement_streak
        gap = summary.activity.longest_inactive_gap
        internal_gap = _longest_internal_gap(days)
        if streak and streak.days >= 30:
            candidates.append((3, 0, "strong_streak", "streak"))
        elif streak and streak.days >= 14:
            candidates.append((2, 0, "notable_streak", "streak"))
        if internal_gap and internal_gap["days"] >= 90:
            candidates.append((3, 1, "major_comeback", "comeback"))
        elif internal_gap and internal_gap["days"] >= 45:
            candidates.append((2, 1, "notable_comeback", "comeback"))
        if top_weekday_share >= 30:
            candidates.append((2, 2, "strong_weekday_pattern", "weekday"))
        elif top_weekday_share >= 25:
            candidates.append((1, 2, "notable_weekday_pattern", "weekday"))
        if internal_gap and internal_gap["days"] >= 180 and (not streak or streak.days < 45):
            selected_activity = next((item for item in candidates if item[3] == "comeback"), None)
        else:
            selected_activity = max(candidates, key=lambda item: (item[0], -item[1]), default=None)
        if selected_activity is None:
            selected_activity = (0, 2, "weekday_fallback", "weekday")
        _, _, activity_variant, activity_kind = selected_activity
        weekday_names = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        top_weekday_achievements = weekday_totals[top_weekday_index]["achievements"]
        weekday_breakdown = [
            {
                "weekday": weekday_names[index],
                "short_label": weekday_names[index][:3],
                "achievements": values["achievements"],
                "active_days": values["active_days"],
                "share": _percent(values["achievements"], total_achievements),
                "relative_percent": _percent(values["achievements"], top_weekday_achievements),
            }
            for index, values in weekday_totals.items()
        ]
        activity_support = {
            "longest_streak": asdict(streak) if streak else None,
            "streak_achievements": sum(
                day.achievements for day in days
                if streak and streak.start_date <= day.date <= streak.end_date
            ),
            "longest_inactive_gap": asdict(gap) if gap else None,
            "longest_internal_inactive_gap": internal_gap,
            "top_weekday": weekday_names[top_weekday_index],
            "top_weekday_share": top_weekday_share,
            "weekday_totals": weekday_totals,
            "weekday_breakdown": weekday_breakdown,
        }
        activity_headline = activity_support["longest_streak"] if activity_kind == "streak" else internal_gap if activity_kind == "comeback" else {
            "weekday": activity_support["top_weekday"],
            "share": top_weekday_share,
            "achievements": top_weekday_achievements,
            "active_days": weekday_totals[top_weekday_index]["active_days"],
        }
        add(
            "activity_pattern", activity_variant, required=True,
            headline=activity_headline,
            supporting=activity_support,
            reason=f"{activity_kind} won the activity-interest scoring rule ({selected_activity[0]} points).",
        )

        clusters, shortest_gap_seconds = _mastery_clusters(summary.details.masteries)
        largest_cluster_rows = max(clusters, key=len, default=[])
        largest_cluster = len(largest_cluster_rows)
        if summary.headline.mastered_games:
            if largest_cluster >= 4:
                mastery_variant = "mastery_sprint"
            elif largest_cluster >= 3:
                mastery_variant = "mastery_cluster"
            elif summary.headline.mastered_games >= 10:
                mastery_variant = "mastery_year"
            elif summary.headline.mastered_games >= 5:
                mastery_variant = "many_masteries"
            elif summary.headline.mastered_games >= 2:
                mastery_variant = "few_masteries"
            else:
                mastery_variant = "single_mastery"
            add(
                "mastery", mastery_variant, required=False,
                headline={"masteries": summary.headline.mastered_games},
                supporting={
                    "timeline": [asdict(mastery) for mastery in summary.details.masteries],
                    "cluster_count": len(clusters),
                    "largest_cluster_size": largest_cluster,
                    "largest_cluster": [asdict(mastery) for mastery in largest_cluster_rows],
                    "shortest_gap_seconds": shortest_gap_seconds,
                },
                reason=(f"The largest 24-hour mastery cluster contained {largest_cluster} games." if clusters else f"The year recorded {summary.headline.mastered_games} masteries."),
                relevant_flags=[flag for flag in flags if flag in {"history_incomplete", "period_in_progress"}],
            )

        if not history_incomplete:
            special_candidates = []
            if largest_cluster >= 4:
                special_candidates.append((1, "mastery_sprint", {
                    "largest_cluster_size": largest_cluster,
                    "start_date": largest_cluster_rows[0].awarded_at,
                    "end_date": largest_cluster_rows[-1].awarded_at,
                    "masteries": [asdict(mastery) for mastery in largest_cluster_rows],
                }, "mastery_sprint"))
            if busiest_share >= 60:
                special_candidates.append((3, "extreme_month_dominance", {"month": busiest_month.month, "share": busiest_share}, "month_dominance"))
            if shares["top_1_share"] >= 35:
                special_candidates.append((4, "extreme_single_game_dominance", {"game": _metric_game(achievement_winner), "share": shares["top_1_share"]}, "single_game_dominance"))
            if internal_gap and internal_gap["days"] >= 180:
                special_candidates.append((6, "huge_comeback", {
                    **internal_gap,
                    "weekly_activity": comeback_weekly_activity(
                        days, internal_gap["activity_after"], summary.period_end,
                    ),
                }, "comeback"))
            unusual_days = [day for day in days if day.hardcore_points > 0 and day.retro_points >= 500 and day.retro_points >= day.hardcore_points * 4]
            if unusual_days:
                unusual_day = max(unusual_days, key=lambda day: (day.retro_points / day.hardcore_points, day.retro_points))
                special_candidates.append((11, "unusual_retropoint_day", {**asdict(unusual_day), "ratio": unusual_day.retro_points / unusual_day.hardcore_points}, "unusual_retropoint_day"))

            if special_candidates:
                impressiveness_rank, special_variant, special_data, _ = min(
                    special_candidates, key=lambda candidate: candidate[0],
                )
                add(
                    "special_highlight", special_variant, required=False,
                    headline=special_data,
                    supporting={
                        "presentation": special_highlight_presentation(special_variant, special_data),
                        "impressiveness_rank": impressiveness_rank,
                    },
                    reason=f"{special_variant} was the most impressive qualifying special fact.",
                )

        if (
            previous is not None
            and previous.status == "final"
            and previous.headline.total_achievements > 0
            and "history_incomplete" not in previous.coverage.flags
            and not history_incomplete
        ):
            comparisons = {
                # Keep the stable payload key used by the existing view while
                # comparing the new all-mode total stored in its values.
                "hardcore_achievements": (previous.headline.total_achievements, summary.headline.total_achievements),
                "active_days": (previous.headline.active_days, summary.headline.active_days),
                "progress_games": (previous.headline.games_with_progress, summary.headline.games_with_progress),
                "consoles": (previous.headline.consoles_with_progress, summary.headline.consoles_with_progress),
                "masteries": (previous.headline.mastered_games, summary.headline.mastered_games),
            }
            if has_hardcore and previous.headline.hardcore_achievements > 0:
                comparisons.update(
                    hardcore_points=(previous.headline.hardcore_points, summary.headline.hardcore_points),
                    retro_points=(previous.headline.retro_points, summary.headline.retro_points),
                )
            changes = {
                name: {"previous": before, "current": after, "raw_change": after - before,
                       "percent_change": ((after - before) / before * 100) if before else None}
                for name, (before, after) in comparisons.items()
            }
            strong_positive = any(change["percent_change"] is not None and change["percent_change"] >= 15 for change in changes.values())
            strong_negative = any(change["percent_change"] is not None and change["percent_change"] <= -15 for change in changes.values())
            achievement_change = changes["hardcore_achievements"]["percent_change"]
            active_day_change = changes["active_days"]["percent_change"]
            if strong_positive and strong_negative:
                yoy_variant = "mixed_year_over_year"
            elif (achievement_change is not None and achievement_change >= 50) or (active_day_change is not None and active_day_change >= 50):
                yoy_variant = "big_growth"
            elif achievement_change is not None and achievement_change >= 15:
                yoy_variant = "moderate_growth"
            elif achievement_change is not None and -15 <= achievement_change <= 15:
                yoy_variant = "similar_year"
            else:
                yoy_variant = "quieter_year"
            valid_changes = [(name, change["percent_change"]) for name, change in changes.items() if change["percent_change"] is not None]
            increases = [item for item in valid_changes if item[1] > 0]
            decreases = [item for item in valid_changes if item[1] < 0]
            add(
                "year_over_year", yoy_variant, required=False,
                headline={"previous_wrapped_year": previous.wrapped_year, "achievement_change_percent": achievement_change},
                supporting={
                    "changes": changes,
                    "largest_proportional_increase": max(increases, key=lambda item: item[1], default=None),
                    "largest_proportional_decrease": min(decreases, key=lambda item: item[1], default=None),
                },
                reason=f"A previous non-empty completed Wrapped ({previous.wrapped_year}) was available.",
            )

        add(
            "final_recap", "standard", required=True,
            headline={
                "wrapped_year": summary.wrapped_year,
                "total_achievements": summary.headline.total_achievements,
                "hardcore_achievements": summary.headline.hardcore_achievements,
                "softcore_achievements": summary.headline.softcore_achievements,
                "hardcore_points": summary.headline.hardcore_points,
                "softcore_points": summary.headline.softcore_points,
                "retro_points": summary.headline.retro_points,
                "progress_games": summary.headline.games_with_progress,
                "active_days": summary.headline.active_days,
                "beaten": summary.headline.effective_beaten_games,
                "completed": summary.headline.completed_games,
                "masteries": summary.headline.mastered_games,
                "top_game": _metric_game(achievement_winner),
                "top_console": top_console,
                "top_genre": genre_data["top_genre"] if genre_data else None,
                "period_start": summary.period_start,
                "period_end": summary.period_end,
            },
            supporting={
                "observed_beaten_games": summary.headline.observed_beaten_games,
                "completed_games": summary.headline.completed_games,
                "mastery_only_beaten_games": summary.awards.mastery_only_beaten_games,
            },
            reason="Every non-empty Wrapped ends with a presentation-neutral recap payload.",
        )

        return WrappedStoryPlan(
            wrapped_year=summary.wrapped_year,
            status=summary.status,
            cards=cards,
            generated_at=summary.generated_at,
            data_quality_flags=flags,
        )


class WrappedStoryService:
    """Generate default historical story plans without any network access."""

    def __init__(self, wrapped_service):
        self.wrapped_service = wrapped_service
        self.selector = WrappedStorySelector()

    def generate_for_user(
        self,
        username: str,
        now: datetime | None = None,
        *,
        include_in_progress: bool = False,
    ) -> list[WrappedStoryPlan]:
        summaries = self.wrapped_service.generate_for_user(username, now)
        plans = []
        previous_completed = None
        for summary in summaries:
            if summary.headline.total_achievements == 0:
                continue
            previous = previous_completed
            if summary.status == "final":
                plan = self.selector.build_plan(summary, previous)
                previous_completed = summary
            elif include_in_progress:
                plan = self.selector.build_plan(summary, previous, include_in_progress=True)
            else:
                plan = None
            if plan is not None:
                plans.append(plan)
        return plans

    def generate_year(
        self,
        username: str,
        wrapped_year: int,
        now: datetime | None = None,
        *,
        include_in_progress: bool = False,
    ) -> WrappedStoryPlan | None:
        summaries = self.wrapped_service.generate_for_user(username, now)
        target = next((summary for summary in summaries if summary.wrapped_year == wrapped_year), None)
        if target is None:
            raise ValueError("Wrapped year is unavailable for this user")
        previous = next((summary for summary in reversed(summaries) if summary.wrapped_year < wrapped_year and summary.status == "final" and summary.headline.total_achievements > 0), None)
        return self.selector.build_plan(target, previous, include_in_progress=include_in_progress)
