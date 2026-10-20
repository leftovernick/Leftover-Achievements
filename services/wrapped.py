"""Read-only RetroAchievements Wrapped summaries built from the local cache."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re
from typing import Literal


RA_LAUNCH_DATE = date(2011, 11, 1)
EARLIEST_WRAPPED_YEAR = 2012
CURRENT_CACHE_FRESHNESS = timedelta(hours=1)
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SUBSET_TITLE_SUFFIX = re.compile(r"\s*\[Subset(?:\s*-\s*[^\]]*)?\]\s*$", re.IGNORECASE)
NON_CONSOLE_PLATFORMS = frozenset({"events"})

WrappedStatus = Literal["in_progress", "final"]


def wrapped_game_title(title: str) -> str:
    """Present a subset as the main game it belongs to."""
    normalized = SUBSET_TITLE_SUFFIX.sub("", title).strip()
    return normalized or title


@dataclass(frozen=True)
class WrappedPeriod:
    wrapped_year: int
    start_date: date
    end_date: date
    status: WrappedStatus

    @property
    def is_complete(self) -> bool:
        return self.status == "final"


@dataclass(frozen=True)
class DateRange:
    start_date: date
    end_date: date


@dataclass
class WrappedCoverage:
    complete: bool
    covered_from: date | None
    covered_through: date | None
    missing_ranges: list[DateRange]
    genre_coverage_percent: float = 0.0
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatedMetric:
    date: date
    value: int


@dataclass(frozen=True)
class MonthMetric:
    month: str
    value: int


@dataclass(frozen=True)
class StreakMetric:
    start_date: date
    end_date: date
    days: int


@dataclass(frozen=True)
class WeekdayMetric:
    weekday: str
    achievements: int


@dataclass(frozen=True)
class GameMetric:
    game_id: int
    title: str
    image: str | None
    console: str | None
    value: int


@dataclass(frozen=True)
class ConsoleMetric:
    console: str
    value: int


@dataclass(frozen=True)
class GenreMetric:
    genre: str
    achievement_weight: float
    share_percent: float


@dataclass
class WrappedHeadline:
    total_achievements: int = 0
    hardcore_achievements: int = 0
    softcore_achievements: int = 0
    hardcore_points: int = 0
    softcore_points: int = 0
    retro_points: int = 0
    active_days: int = 0
    games_with_progress: int = 0
    consoles_with_progress: int = 0
    completed_games: int = 0
    mastered_games: int = 0
    observed_beaten_games: int = 0
    effective_beaten_games: int = 0

    @property
    def beaten_games_partial(self) -> int:
        """Return the observed beaten-game total used by summary callers."""
        return self.observed_beaten_games


@dataclass
class WrappedActivity:
    achievements_by_month: list[MonthMetric]
    points_by_month: list[MonthMetric]
    retro_points_by_month: list[MonthMetric]
    busiest_day: DatedMetric | None
    busiest_month: MonthMetric | None
    biggest_point_day: DatedMetric | None
    active_days: int
    longest_achievement_streak: StreakMetric | None
    longest_inactive_gap: StreakMetric | None
    favorite_weekday: WeekdayMetric | None
    average_achievements_per_active_day: float


@dataclass
class WrappedGames:
    unique_progress_games: int
    top_by_achievements: GameMetric | None
    top_by_hardcore_points: GameMetric | None
    top_by_retro_points: GameMetric | None
    top_by_active_days: GameMetric | None


@dataclass
class WrappedConsoles:
    achievements: list[ConsoleMetric]
    hardcore_points: list[ConsoleMetric]
    retro_points: list[ConsoleMetric]
    unique_progress_games: list[ConsoleMetric]
    top_by_achievements: ConsoleMetric | None
    top_by_games: ConsoleMetric | None
    total_consoles: int
    unknown_achievements: int


@dataclass
class WrappedGenres:
    achievement_shares: list[GenreMetric]
    top_genre: GenreMetric | None
    unique_progress_games: int
    games_with_genre: int
    games_without_genre: int
    coverage_percent: float
    unknown_achievement_share_percent: float


@dataclass
class WrappedAwards:
    completed_games: int
    completion_by_month: list[MonthMetric]
    mastered_games: int
    mastery_by_month: list[MonthMetric]
    mastery_reliability: Literal["more_reliable"]
    observed_beaten_games: int
    effective_beaten_games: int
    completion_only_beaten_games: int
    mastery_only_beaten_games: int
    beaten_by_month_partial: list[MonthMetric]
    beaten_reliability: Literal["stored_awards"]

    @property
    def beaten_games_partial(self) -> int:
        """Return the observed beaten-game total used by story callers."""
        return self.observed_beaten_games


@dataclass(frozen=True)
class ActivityBoundary:
    date: date
    achievement_at: datetime | None = None
    points: int | None = None
    retro_points: int | None = None
    enrichment_required: bool = True


@dataclass(frozen=True)
class AchievementHighlight:
    achievement_id: int
    title: str
    description: str | None
    badge: str | None
    game_id: int
    game_title: str
    console: str | None
    points: int
    retro_points: int
    unlock_time: datetime
    rarity_percent: float | None = None


@dataclass(frozen=True)
class WrappedGameDetail:
    game_id: int
    title: str
    image: str | None
    cover_image: str | None
    console: str | None
    achievements: int
    hardcore_achievements: int
    softcore_achievements: int
    hardcore_points: int
    retro_points: int
    active_days: int
    genres: tuple[str, ...]
    first_active_date: date


@dataclass(frozen=True)
class WrappedDayDetail:
    date: date
    achievements: int
    hardcore_achievements: int
    softcore_achievements: int
    hardcore_points: int
    retro_points: int
    active_game_ids: tuple[int, ...]


@dataclass(frozen=True)
class WrappedMonthDetail:
    month: str
    achievements: int
    hardcore_achievements: int
    softcore_achievements: int
    hardcore_points: int
    retro_points: int
    active_days: int
    progress_game_ids: tuple[int, ...]
    completions: int
    masteries: int
    beaten_partial: int


@dataclass(frozen=True)
class WrappedAwardDetail:
    awarded_at: datetime
    game_id: int
    game_title: str
    image: str | None
    console: str | None
    genres: tuple[str, ...]


@dataclass
class WrappedDetails:
    games: list[WrappedGameDetail]
    days: list[WrappedDayDetail]
    months: list[WrappedMonthDetail]
    completions: list[WrappedAwardDetail]
    masteries: list[WrappedAwardDetail]
    beaten_partial: list[WrappedAwardDetail]


@dataclass
class WrappedHighlights:
    first_activity: ActivityBoundary | None
    last_activity: ActivityBoundary | None
    rarest_achievement: AchievementHighlight | None = None
    highest_point_achievement: AchievementHighlight | None = None
    highest_retro_points_achievement: AchievementHighlight | None = None


@dataclass
class WrappedSummary:
    canonical_username: str
    avatar: str | None
    member_since: datetime
    wrapped_year: int
    period_start: date
    period_end: date
    status: WrappedStatus
    generated_at: datetime
    coverage: WrappedCoverage
    headline: WrappedHeadline
    activity: WrappedActivity
    games: WrappedGames
    consoles: WrappedConsoles
    genres: WrappedGenres
    awards: WrappedAwards
    highlights: WrappedHighlights
    details: WrappedDetails


def _utc_date(value: date | datetime | None = None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).date() if value.tzinfo is None else value.astimezone(timezone.utc).date()
    return value


def get_wrapped_year_for_date(value: date | datetime) -> int:
    utc_day = _utc_date(value)
    if utc_day < RA_LAUNCH_DATE:
        raise ValueError("RetroAchievements Wrapped begins on November 1, 2011")
    return utc_day.year + 1 if (utc_day.month, utc_day.day) >= (11, 1) else utc_day.year


def get_current_wrapped_year(on_date: date | datetime | None = None) -> int:
    return get_wrapped_year_for_date(_utc_date(on_date))


def get_wrapped_status(wrapped_year: int, on_date: date | datetime | None = None) -> WrappedStatus:
    if wrapped_year < EARLIEST_WRAPPED_YEAR:
        raise ValueError(f"Wrapped year must be {EARLIEST_WRAPPED_YEAR} or later")
    end_date = date(wrapped_year, 10, 31)
    return "final" if _utc_date(on_date) > end_date else "in_progress"


def get_wrapped_period(wrapped_year: int, on_date: date | datetime | None = None) -> WrappedPeriod:
    if wrapped_year < EARLIEST_WRAPPED_YEAR:
        raise ValueError(f"Wrapped year must be {EARLIEST_WRAPPED_YEAR} or later")
    return WrappedPeriod(
        wrapped_year=wrapped_year,
        start_date=date(wrapped_year - 1, 11, 1),
        end_date=date(wrapped_year, 10, 31),
        status=get_wrapped_status(wrapped_year, on_date),
    )


def list_available_wrapped_years(
    member_since: date | datetime,
    on_date: date | datetime | None = None,
) -> list[int]:
    current_day = _utc_date(on_date)
    member_day = max(_utc_date(member_since), RA_LAUNCH_DATE)
    if member_day > current_day:
        return []
    first_year = get_wrapped_year_for_date(member_day)
    current_year = get_wrapped_year_for_date(current_day)
    return list(range(first_year, current_year + 1))


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _profile_key(profile: dict) -> str:
    return (f"ulid:{profile['ulid']}" if profile.get("ulid") else f"username:{profile['username']}").lower()


def _month_keys(period: WrappedPeriod) -> list[str]:
    current = period.start_date.replace(day=1)
    final = period.end_date.replace(day=1)
    keys = []
    while current <= final:
        keys.append(current.isoformat())
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return keys


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _required_interval(period: WrappedPeriod, member_since: datetime, now: datetime) -> tuple[datetime, datetime] | None:
    start = max(_utc_midnight(period.start_date), member_since.astimezone(timezone.utc))
    period_end = _utc_midnight(period.end_date + timedelta(days=1)) - timedelta(seconds=1)
    end = min(period_end, now.astimezone(timezone.utc))
    return (start, end) if start <= end else None


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + timedelta(seconds=1):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _coverage_for_period(
    period: WrappedPeriod,
    member_since: datetime,
    rows: dict[str, dict],
    now: datetime,
) -> WrappedCoverage:
    required = _required_interval(period, member_since, now)
    flags = []
    notes = []
    if not period.is_complete:
        flags.append("period_in_progress")
        notes.append("The current Wrapped period is not final until November 1.")
    if required is None:
        return WrappedCoverage(True, None, None, [], flags=flags, notes=notes)

    required_start, required_end = required
    intervals = []
    for month_start, row in rows.items():
        if row.get("days") is None or not row.get("covered_through"):
            continue
        month = datetime.combine(date.fromisoformat(month_start), time.min, tzinfo=timezone.utc)
        start = max(month, member_since.astimezone(timezone.utc), required_start.astimezone(timezone.utc))
        end = min(_parse_datetime(row["covered_through"]).astimezone(timezone.utc), required_end.astimezone(timezone.utc))
        if start <= end:
            intervals.append((start, end))

    merged = _merge_intervals(intervals)
    effective_required_end = required_end.astimezone(timezone.utc)
    if not period.is_complete and merged and effective_required_end - merged[-1][1] <= CURRENT_CACHE_FRESHNESS:
        merged[-1] = (merged[-1][0], effective_required_end)

    gaps = []
    cursor = required_start.astimezone(timezone.utc)
    for start, end in merged:
        if start > cursor:
            gaps.append((cursor, start - timedelta(seconds=1)))
        cursor = max(cursor, end + timedelta(seconds=1))
    if cursor <= effective_required_end:
        gaps.append((cursor, effective_required_end))

    missing_ranges = [
        DateRange(start.astimezone(timezone.utc).date(), end.astimezone(timezone.utc).date())
        for start, end in gaps
    ]
    if missing_ranges:
        flags.append("history_incomplete")
        notes.append("One or more account-history ranges are not present in the monthly cache.")

    covered_from = merged[0][0].astimezone(timezone.utc).date() if merged else None
    covered_through = merged[-1][1].astimezone(timezone.utc).date() if merged else None
    return WrappedCoverage(
        complete=not missing_ranges,
        covered_from=covered_from,
        covered_through=covered_through,
        missing_ranges=missing_ranges,
        flags=flags,
        notes=notes,
    )


def _longest_run(days: set[date], choose_active: bool, start: date, end: date) -> StreakMetric | None:
    best = None
    run_start = None
    current = start
    while current <= end:
        matches = (current in days) == choose_active
        if matches and run_start is None:
            run_start = current
        if run_start is not None and (not matches or current == end):
            run_end = current if matches and current == end else current - timedelta(days=1)
            candidate = StreakMetric(run_start, run_end, (run_end - run_start).days + 1)
            if best is None or candidate.days > best.days:
                best = candidate
            run_start = None
        current += timedelta(days=1)
    return best


def _top_dated(values: dict[date, int]) -> DatedMetric | None:
    if not values:
        return None
    day, value = min(values.items(), key=lambda item: (-item[1], item[0]))
    return DatedMetric(day, value)


def _top_month(values: dict[str, int]) -> MonthMetric | None:
    if not values or not any(values.values()):
        return None
    month, value = min(values.items(), key=lambda item: (-item[1], item[0]))
    return MonthMetric(month, value)


def _game_metric(game: dict | None, field_name: str) -> GameMetric | None:
    if not game:
        return None
    return GameMetric(
        game_id=game["game_id"],
        title=game["game_title"],
        image=game.get("game_image"),
        console=game.get("console"),
        value=int(game[field_name]),
    )


def _top_game(games: dict[int, dict], field_name: str) -> GameMetric | None:
    if not games:
        return None
    game = min(
        games.values(),
        key=lambda item: (
            -int(item[field_name]), item["first_active_date"],
            item["game_title"].casefold(), item["game_id"],
        ),
    )
    return _game_metric(game, field_name)


def _console_metrics(values: dict[str, int]) -> list[ConsoleMetric]:
    return [ConsoleMetric(name, value) for name, value in sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))]


def _top_console(values: dict[str, int], first_dates: dict[str, date]) -> ConsoleMetric | None:
    known = {name: value for name, value in values.items() if name != "Unknown"}
    if not known:
        return None
    name, value = min(known.items(), key=lambda item: (-item[1], first_dates[item[0]], item[0].casefold()))
    return ConsoleMetric(name, value)


def _award_games(awards: list[dict], period: WrappedPeriod, now: datetime) -> list[dict]:
    end_date = min(period.end_date, now.astimezone(timezone.utc).date())
    by_game = {}
    for award in awards:
        awarded = _parse_datetime(award["date"]).astimezone(timezone.utc)
        if not period.start_date <= awarded.date() <= end_date:
            continue
        existing = by_game.get(award["game_id"])
        if existing is None or awarded < existing["awarded"]:
            by_game[award["game_id"]] = {**award, "awarded": awarded}
    return list(by_game.values())


def _genre_labels(metadata: dict | None) -> tuple[str, ...]:
    labels = [label.strip() for label in ((metadata or {}).get("genre") or "").split(",") if label.strip()]
    return tuple(dict.fromkeys(labels))


def _canonical_game_id(game_id: int, metadata: dict[int, dict]) -> int:
    return int((metadata.get(game_id) or {}).get("parent_game_id") or game_id)


def _canonical_game_values(game: dict, metadata: dict[int, dict]) -> dict:
    source_id = int(game["game_id"])
    canonical_id = _canonical_game_id(source_id, metadata)
    source_metadata = metadata.get(source_id, {})
    canonical_metadata = metadata.get(canonical_id, {})
    canonical_title = (
        canonical_metadata.get("game_title")
        or wrapped_game_title(source_metadata.get("game_title") or game["game_title"])
    )
    canonical_image = (
        canonical_metadata.get("image_icon")
        or canonical_metadata.get("image_box_art")
        or game.get("game_image")
    )
    return {
        "game_id": canonical_id,
        "game_title": canonical_title,
        "game_image": canonical_image,
        "console": canonical_metadata.get("console") or game.get("console") or source_metadata.get("console"),
    }


def _canonicalize_days(days: dict[date, dict], metadata: dict[int, dict]) -> dict[date, dict]:
    for values in days.values():
        canonical_games = {}
        for game in values["games"].values():
            canonical = _canonical_game_values(game, metadata)
            target = canonical_games.setdefault(canonical["game_id"], {
                **canonical,
                "achievements_earned": 0,
                "hardcore_achievements_earned": 0,
                "softcore_achievements_earned": 0,
                "hardcore_points": 0,
                "retro_points": 0,
            })
            for field_name in (
                "achievements_earned", "hardcore_achievements_earned",
                "softcore_achievements_earned", "hardcore_points", "retro_points",
            ):
                target[field_name] += int(game.get(field_name) or 0)
        values["games"] = canonical_games
    return days


def _canonicalize_awards(awards: list[dict], metadata: dict[int, dict]) -> list[dict]:
    canonical_awards = {}
    for award in awards:
        canonical = _canonical_game_values({
            "game_id": award["game_id"],
            "game_title": award["game_title"],
            "game_image": award.get("game_image"),
            "console": award.get("console"),
        }, metadata)
        normalized = {**award, **canonical}
        existing = canonical_awards.get(canonical["game_id"])
        if existing is None or normalized["awarded"] < existing["awarded"]:
            canonical_awards[canonical["game_id"]] = normalized
    return list(canonical_awards.values())


class WrappedService:
    """Build Wrapped summaries without performing RetroAchievements API calls."""

    def __init__(self, database):
        self.db = database

    def generate_for_user(self, username: str, now: datetime | None = None) -> list[WrappedSummary]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        profile, rows, storage_username = self._user_cache(username)
        member_since = _parse_datetime(profile["member_since"])
        return [self.generate_year(storage_username, year, now, profile, rows)
                for year in list_available_wrapped_years(member_since, now)]

    def generate_year(
        self,
        username: str,
        wrapped_year: int,
        now: datetime | None = None,
        profile: dict | None = None,
        rows: dict[str, dict] | None = None,
    ) -> WrappedSummary:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if profile is None or rows is None:
            profile, rows, username = self._user_cache(username)
        member_since = _parse_datetime(profile["member_since"])
        period = get_wrapped_period(wrapped_year, now)
        if wrapped_year not in list_available_wrapped_years(member_since, now):
            raise ValueError("Wrapped year does not overlap this account's lifetime")

        coverage = _coverage_for_period(period, member_since, rows, now)
        if any(row.get("days") is not None and row.get("utc_days") is None for row in rows.values()):
            coverage.flags.append("utc_history_pending")
            coverage.notes.append("Wrapped UTC history is being rebuilt from RetroAchievements data.")
        if any(
            "aggregation_version" in row and int(row.get("aggregation_version") or 1) < 2
            for row in rows.values()
        ):
            coverage.flags.append("softcore_history_pending")
            coverage.notes.append("Wrapped Softcore history is being rebuilt from RetroAchievements data.")
        days = self._period_days(rows, period, now)
        raw_games = self._aggregate_games(days)

        required = _required_interval(period, member_since, now)
        award_end = required[1] if required else now
        masteries = _award_games(self.db.get_recorded_chart_masteries([username], award_end).get(username.lower(), []), period, now)
        completions = _award_games(self.db.get_recorded_chart_completions([username], award_end).get(username.lower(), []), period, now)
        beaten = _award_games(self.db.get_recorded_chart_beaten_games([username], award_end).get(username.lower(), []), period, now)
        award_game_ids = {int(award["game_id"]) for award in masteries + completions + beaten}
        metadata = self.db.get_game_metadata(set(raw_games) | award_game_ids)
        parent_game_ids = {
            int(details["parent_game_id"])
            for details in metadata.values()
            if details.get("parent_game_id")
        }
        if parent_game_ids:
            metadata.update(self.db.get_game_metadata(parent_game_ids))
        days = _canonicalize_days(days, metadata)
        masteries = _canonicalize_awards(masteries, metadata)
        completions = _canonicalize_awards(completions, metadata)
        beaten = _canonicalize_awards(beaten, metadata)
        games = self._aggregate_games(days)
        for game_id, game in games.items():
            details = metadata.get(game_id, {})
            game["game_title"] = details.get("game_title") or game["game_title"]
            game["game_image"] = details.get("image_icon") or details.get("image_box_art") or game.get("game_image")
            game["console"] = game.get("console") or details.get("console")

        activity = self._activity(days, period, member_since, now)
        game_summary = WrappedGames(
            unique_progress_games=len(games),
            top_by_achievements=_top_game(games, "achievements_earned"),
            top_by_hardcore_points=_top_game(games, "hardcore_points"),
            top_by_retro_points=_top_game(games, "retro_points"),
            top_by_active_days=_top_game(games, "active_days"),
        )
        consoles = self._consoles(games)
        genres = self._genres(games, metadata)
        coverage.genre_coverage_percent = genres.coverage_percent
        if genres.games_without_genre:
            coverage.flags.append("genre_metadata_incomplete")
            coverage.notes.append("Genre statistics include an unknown share for games without usable metadata.")

        awards = self._awards(masteries, completions, beaten, period)

        achievement_total = sum(int(values.get("achievements_earned") or 0) for values in days.values())
        hardcore_achievement_total = sum(
            int(values.get("hardcore_achievements_earned") or 0) for values in days.values()
        )
        softcore_achievement_total = sum(
            int(values.get("softcore_achievements_earned") or 0) for values in days.values()
        )
        point_total = sum(int(values.get("hardcore_points") or 0) for values in days.values())
        softcore_point_total = sum(int(values.get("softcore_points") or 0) for values in days.values())
        retro_total = sum(int(values.get("retro_points") or 0) for values in days.values())
        first_activity = self._first_activity(days)
        last_day = max(days) if days else None
        if not days:
            coverage.flags.append("no_activity")

        return WrappedSummary(
            canonical_username=profile["username"],
            avatar=profile.get("avatar"),
            member_since=member_since,
            wrapped_year=wrapped_year,
            period_start=period.start_date,
            period_end=period.end_date,
            status=period.status,
            generated_at=now,
            coverage=coverage,
            headline=WrappedHeadline(
                total_achievements=achievement_total,
                hardcore_achievements=hardcore_achievement_total,
                softcore_achievements=softcore_achievement_total,
                hardcore_points=point_total,
                softcore_points=softcore_point_total,
                retro_points=retro_total,
                active_days=len(days),
                games_with_progress=len(games),
                consoles_with_progress=consoles.total_consoles,
                completed_games=awards.completed_games,
                mastered_games=awards.mastered_games,
                observed_beaten_games=awards.observed_beaten_games,
                effective_beaten_games=awards.effective_beaten_games,
            ),
            activity=activity,
            games=game_summary,
            consoles=consoles,
            genres=genres,
            awards=awards,
            highlights=WrappedHighlights(
                first_activity=first_activity,
                last_activity=ActivityBoundary(last_day) if last_day else None,
            ),
            details=self._details(days, games, metadata, masteries, completions, beaten, period),
        )

    def _user_cache(self, username: str) -> tuple[dict, dict[str, dict], str]:
        profiles, months = self.db.get_all_time_chart_cache()
        cached = profiles.get(username.lower())
        storage_username = username
        if cached is None:
            match = next(
                ((key, value) for key, value in profiles.items()
                 if value["profile"].get("username", "").casefold() == username.casefold()), None,
            )
            if match:
                storage_username, cached = match
        if not cached:
            raise ValueError("No local account-history profile is available for this user")
        profile = cached["profile"]
        if not profile.get("member_since"):
            raise ValueError("RetroAchievements member-since date is unavailable")
        return profile, months.get(_profile_key(profile), {}), storage_username

    @staticmethod
    def _period_days(rows: dict[str, dict], period: WrappedPeriod, now: datetime) -> dict[date, dict]:
        end_date = min(period.end_date, now.astimezone(timezone.utc).date())
        source_values = []
        # Wrapped follows RetroAchievements' UTC clock. Rows without UTC buckets
        # use their daily aggregate until the background refresh replaces them.
        for row in rows.values():
            source_days = row.get("utc_days")
            if source_days is None:
                source_days = row.get("days") or {}
            for day_key, values in source_days.items():
                day = date.fromisoformat(day_key)
                if not period.start_date <= day <= end_date:
                    continue
                source_values.append((day, values))

        # Version 2 cache rows retain unlock identity and mode. Select one annual
        # representation for each achievement: Hardcore supersedes Softcore, and
        # duplicate events in the same mode use their earliest timestamp.
        event_candidates = {}
        game_catalog = {}
        has_event_data = bool(source_values) and all("unlock_events" in values for _, values in source_values)
        for source_day, values in source_values:
            for game in values.get("games") or []:
                game_id = int(game.get("game_id") or 0)
                if game_id:
                    game_catalog.setdefault(game_id, game)
            if not has_event_data:
                continue
            for index, event in enumerate(values.get("unlock_events") or []):
                earned = _parse_datetime(event.get("earned_at"))
                event_day = earned.astimezone(timezone.utc).date()
                if not period.start_date <= event_day <= end_date:
                    continue
                achievement_id = event.get("achievement_id")
                key = ("achievement", int(achievement_id)) if achievement_id is not None else (
                    "anonymous", event.get("earned_at"), event.get("game_id"), index,
                )
                normalized = {**event, "earned": earned, "day": event_day}
                existing = event_candidates.get(key)
                if existing is None or (
                    bool(normalized.get("hardcore")), -earned.timestamp()
                ) > (
                    bool(existing.get("hardcore")), -existing["earned"].timestamp()
                ):
                    event_candidates[key] = normalized

        combined = {}
        if has_event_data:
            for event in event_candidates.values():
                day = event["day"]
                hardcore = bool(event.get("hardcore"))
                game_id = int(event.get("game_id") or 0)
                target = combined.setdefault(day, {
                    "hardcore_points": 0, "softcore_points": 0, "retro_points": 0,
                    "achievements_earned": 0,
                    "hardcore_achievements_earned": 0,
                    "softcore_achievements_earned": 0,
                    "games": {},
                })
                target["achievements_earned"] += 1
                mode_field = "hardcore_achievements_earned" if hardcore else "softcore_achievements_earned"
                target[mode_field] += 1
                if hardcore:
                    target["hardcore_points"] += int(event.get("points") or 0)
                    target["retro_points"] += int(event.get("retro_points") or 0)
                else:
                    target["softcore_points"] += int(event.get("points") or 0)
                if game_id:
                    game = game_catalog.get(game_id, {})
                    merged = target["games"].setdefault(game_id, {
                        "game_id": game_id,
                        "game_title": game.get("game_title") or f"Game #{game_id}",
                        "game_image": game.get("game_image"),
                        "console": game.get("console"),
                        "achievements_earned": 0,
                        "hardcore_achievements_earned": 0,
                        "softcore_achievements_earned": 0,
                        "hardcore_points": 0, "softcore_points": 0, "retro_points": 0,
                    })
                    merged["achievements_earned"] += 1
                    merged[mode_field] += 1
                    if hardcore:
                        merged["hardcore_points"] += int(event.get("points") or 0)
                        merged["retro_points"] += int(event.get("retro_points") or 0)
                    else:
                        merged["softcore_points"] += int(event.get("points") or 0)
                first = target.get("first_achievement_at")
                if first is None or event["earned"] < first:
                    target["first_achievement_at"] = event["earned"]
                    target["first_hardcore_points"] = int(event.get("points") or 0) if hardcore else 0
                    target["first_retro_points"] = int(event.get("retro_points") or 0) if hardcore else 0
            return combined

        # Daily aggregates remain usable when mode-aware unlock facts are unavailable.
        for day, values in source_values:
            target = combined.setdefault(day, {
                "hardcore_points": 0, "softcore_points": 0, "retro_points": 0,
                "achievements_earned": 0,
                "hardcore_achievements_earned": 0,
                "softcore_achievements_earned": 0,
                "games": {},
            })
            hardcore_count = int(values.get("achievements_earned") or 0)
            softcore_count = int(values.get("softcore_achievements_earned") or 0)
            target["hardcore_points"] += int(values.get("hardcore_points") or 0)
            target["softcore_points"] += int(values.get("softcore_points") or 0)
            target["retro_points"] += int(values.get("retro_points") or 0)
            target["hardcore_achievements_earned"] += hardcore_count
            target["softcore_achievements_earned"] += softcore_count
            target["achievements_earned"] += hardcore_count + softcore_count
            for game in values.get("games") or []:
                game_id = int(game.get("game_id") or 0)
                if not game_id:
                    continue
                game_hardcore = int(game.get("achievements_earned") or 0)
                game_softcore = int(game.get("softcore_achievements_earned") or 0)
                merged = target["games"].setdefault(game_id, {
                    "game_id": game_id,
                    "game_title": game.get("game_title") or f"Game #{game_id}",
                    "game_image": game.get("game_image"),
                    "console": game.get("console"),
                    "achievements_earned": 0,
                    "hardcore_achievements_earned": 0,
                    "softcore_achievements_earned": 0,
                    "hardcore_points": 0, "softcore_points": 0, "retro_points": 0,
                })
                merged["achievements_earned"] += game_hardcore + game_softcore
                merged["hardcore_achievements_earned"] += game_hardcore
                merged["softcore_achievements_earned"] += game_softcore
                merged["hardcore_points"] += int(game.get("hardcore_points") or 0)
                merged["softcore_points"] += int(game.get("softcore_points") or 0)
                merged["retro_points"] += int(game.get("retro_points") or 0)
            first_value = values.get("first_achievement_at")
            if first_value:
                first = _parse_datetime(first_value)
                existing = target.get("first_achievement_at")
                if existing is None or first < existing:
                    target["first_achievement_at"] = first
                    target["first_hardcore_points"] = int(values.get("first_hardcore_points") or 0)
                    target["first_retro_points"] = int(values.get("first_retro_points") or 0)
        return {day: values for day, values in combined.items() if values["achievements_earned"] > 0}

    @staticmethod
    def _aggregate_games(days: dict[date, dict]) -> dict[int, dict]:
        games = {}
        for day, values in sorted(days.items()):
            for game in values["games"].values():
                game_id = game["game_id"]
                combined = games.setdefault(game_id, {
                    **game,
                    "achievements_earned": 0,
                    "hardcore_achievements_earned": 0,
                    "softcore_achievements_earned": 0,
                    "hardcore_points": 0,
                    "softcore_points": 0,
                    "retro_points": 0, "active_days": 0,
                    "first_active_date": day,
                })
                for field_name in (
                    "achievements_earned", "hardcore_achievements_earned",
                    "softcore_achievements_earned", "hardcore_points", "softcore_points", "retro_points",
                ):
                    combined[field_name] += int(game.get(field_name) or 0)
                combined["active_days"] += 1
                combined["game_image"] = combined.get("game_image") or game.get("game_image")
                combined["console"] = combined.get("console") or game.get("console")
        return games

    @staticmethod
    def _activity(days: dict[date, dict], period: WrappedPeriod, member_since: datetime, now: datetime) -> WrappedActivity:
        months = _month_keys(period)
        achievements = {month: 0 for month in months}
        points = {month: 0 for month in months}
        retro_points = {month: 0 for month in months}
        weekday_totals = [0] * 7
        for day, values in days.items():
            month = day.replace(day=1).isoformat()
            achievements[month] += values["achievements_earned"]
            points[month] += values["hardcore_points"]
            retro_points[month] += values["retro_points"]
            weekday_totals[day.weekday()] += values["achievements_earned"]

        active_dates = set(days)
        required = _required_interval(period, member_since, now)
        streak = _longest_run(active_dates, True, required[0].astimezone(timezone.utc).date(), required[1].astimezone(timezone.utc).date()) if required else None
        gap = _longest_run(active_dates, False, required[0].astimezone(timezone.utc).date(), required[1].astimezone(timezone.utc).date()) if required else None
        favorite = None
        if any(weekday_totals):
            weekday = min(range(7), key=lambda index: (-weekday_totals[index], index))
            favorite = WeekdayMetric(WEEKDAY_NAMES[weekday], weekday_totals[weekday])
        achievement_total = sum(weekday_totals)
        return WrappedActivity(
            achievements_by_month=[MonthMetric(month, achievements[month]) for month in months],
            points_by_month=[MonthMetric(month, points[month]) for month in months],
            retro_points_by_month=[MonthMetric(month, retro_points[month]) for month in months],
            busiest_day=_top_dated({day: values["achievements_earned"] for day, values in days.items()}),
            busiest_month=_top_month(achievements),
            biggest_point_day=_top_dated({day: values["hardcore_points"] for day, values in days.items()}),
            active_days=len(active_dates),
            longest_achievement_streak=streak,
            longest_inactive_gap=gap,
            favorite_weekday=favorite,
            average_achievements_per_active_day=(achievement_total / len(active_dates) if active_dates else 0.0),
        )

    @staticmethod
    def _consoles(games: dict[int, dict]) -> WrappedConsoles:
        totals = {field_name: {} for field_name in ("achievements_earned", "hardcore_points", "retro_points")}
        game_counts = {}
        first_dates = {}
        for game in games.values():
            console = (game.get("console") or "Unknown").strip() or "Unknown"
            if console.casefold() in NON_CONSOLE_PLATFORMS:
                continue
            first_dates[console] = min(first_dates.get(console, game["first_active_date"]), game["first_active_date"])
            game_counts[console] = game_counts.get(console, 0) + 1
            for field_name in totals:
                totals[field_name][console] = totals[field_name].get(console, 0) + int(game[field_name])
        known = {console for console in game_counts if console != "Unknown"}
        return WrappedConsoles(
            achievements=_console_metrics(totals["achievements_earned"]),
            hardcore_points=_console_metrics(totals["hardcore_points"]),
            retro_points=_console_metrics(totals["retro_points"]),
            unique_progress_games=_console_metrics(game_counts),
            top_by_achievements=_top_console(totals["achievements_earned"], first_dates),
            top_by_games=_top_console(game_counts, first_dates),
            total_consoles=len(known),
            unknown_achievements=totals["achievements_earned"].get("Unknown", 0),
        )

    @staticmethod
    def _genres(games: dict[int, dict], metadata: dict[int, dict]) -> WrappedGenres:
        weights = {}
        first_dates = {}
        games_with_genre = 0
        unknown_weight = 0.0
        achievement_total = sum(game["achievements_earned"] for game in games.values())
        for game_id, game in games.items():
            labels = _genre_labels(metadata.get(game_id))
            if not labels:
                unknown_weight += game["achievements_earned"]
                continue
            games_with_genre += 1
            contribution = game["achievements_earned"] / len(labels)
            for label in labels:
                weights[label] = weights.get(label, 0.0) + contribution
                first_dates[label] = min(first_dates.get(label, game["first_active_date"]), game["first_active_date"])
        metrics = [
            GenreMetric(label, weight, (weight / achievement_total * 100) if achievement_total else 0.0)
            for label, weight in sorted(weights.items(), key=lambda item: (-item[1], first_dates[item[0]], item[0].casefold()))
        ]
        game_total = len(games)
        return WrappedGenres(
            achievement_shares=metrics,
            top_genre=metrics[0] if metrics else None,
            unique_progress_games=game_total,
            games_with_genre=games_with_genre,
            games_without_genre=game_total - games_with_genre,
            coverage_percent=(games_with_genre / game_total * 100) if game_total else 100.0,
            unknown_achievement_share_percent=(unknown_weight / achievement_total * 100) if achievement_total else 0.0,
        )

    @staticmethod
    def _details(
        days: dict[date, dict],
        games: dict[int, dict],
        metadata: dict[int, dict],
        masteries: list[dict],
        completions: list[dict],
        beaten: list[dict],
        period: WrappedPeriod,
    ) -> WrappedDetails:
        month_values = {
            month: {
                "achievements": 0, "hardcore_achievements": 0, "softcore_achievements": 0,
                "hardcore_points": 0, "retro_points": 0,
                "active_days": 0, "game_ids": set(), "completions": 0, "masteries": 0, "beaten": 0,
            }
            for month in _month_keys(period)
        }
        day_details = []
        for day, values in sorted(days.items()):
            month = day.replace(day=1).isoformat()
            target = month_values[month]
            target["achievements"] += int(values["achievements_earned"])
            target["hardcore_achievements"] += int(values["hardcore_achievements_earned"])
            target["softcore_achievements"] += int(values["softcore_achievements_earned"])
            target["hardcore_points"] += int(values["hardcore_points"])
            target["retro_points"] += int(values["retro_points"])
            target["active_days"] += 1
            target["game_ids"].update(values["games"])
            day_details.append(WrappedDayDetail(
                date=day,
                achievements=int(values["achievements_earned"]),
                hardcore_achievements=int(values["hardcore_achievements_earned"]),
                softcore_achievements=int(values["softcore_achievements_earned"]),
                hardcore_points=int(values["hardcore_points"]),
                retro_points=int(values["retro_points"]),
                active_game_ids=tuple(sorted(values["games"])),
            ))
        for award in masteries:
            month_values[award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()]["masteries"] += 1
        for award in completions:
            month_values[award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()]["completions"] += 1
        for award in beaten:
            month_values[award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()]["beaten"] += 1

        def award_detail(award: dict) -> WrappedAwardDetail:
            game_id = int(award["game_id"])
            game = games.get(game_id, {})
            game_metadata = metadata.get(game_id, {})
            return WrappedAwardDetail(
                awarded_at=award["awarded"],
                game_id=game_id,
                game_title=wrapped_game_title(
                    game_metadata.get("game_title") or award["game_title"]
                ),
                image=award.get("game_image") or game.get("game_image"),
                console=game.get("console") or game_metadata.get("console"),
                genres=_genre_labels(game_metadata),
            )

        return WrappedDetails(
            games=[
                WrappedGameDetail(
                    game_id=game_id,
                    title=game["game_title"],
                    image=game.get("game_image"),
                    cover_image=metadata.get(game_id, {}).get("image_box_art"),
                    console=game.get("console"),
                    achievements=int(game["achievements_earned"]),
                    hardcore_achievements=int(game["hardcore_achievements_earned"]),
                    softcore_achievements=int(game["softcore_achievements_earned"]),
                    hardcore_points=int(game["hardcore_points"]),
                    retro_points=int(game["retro_points"]),
                    active_days=int(game["active_days"]),
                    genres=_genre_labels(metadata.get(game_id)),
                    first_active_date=game["first_active_date"],
                )
                for game_id, game in sorted(games.items())
            ],
            days=day_details,
            months=[
                WrappedMonthDetail(
                    month=month,
                    achievements=values["achievements"],
                    hardcore_achievements=values["hardcore_achievements"],
                    softcore_achievements=values["softcore_achievements"],
                    hardcore_points=values["hardcore_points"],
                    retro_points=values["retro_points"],
                    active_days=values["active_days"],
                    progress_game_ids=tuple(sorted(values["game_ids"])),
                    completions=values["completions"],
                    masteries=values["masteries"],
                    beaten_partial=values["beaten"],
                )
                for month, values in month_values.items()
            ],
            completions=[award_detail(award) for award in sorted(completions, key=lambda item: item["awarded"])],
            masteries=[award_detail(award) for award in sorted(masteries, key=lambda item: item["awarded"])],
            beaten_partial=[award_detail(award) for award in sorted(beaten, key=lambda item: item["awarded"])],
        )

    @staticmethod
    def _awards(masteries: list[dict], completions: list[dict], beaten: list[dict], period: WrappedPeriod) -> WrappedAwards:
        months = _month_keys(period)
        completion_counts = {month: 0 for month in months}
        mastery_counts = {month: 0 for month in months}
        beaten_counts = {month: 0 for month in months}
        mastered_game_ids = {int(award["game_id"]) for award in masteries}
        raw_completed_game_ids = {int(award["game_id"]) for award in completions}
        completed_game_ids = raw_completed_game_ids - mastered_game_ids
        observed_beaten_game_ids = {int(award["game_id"]) for award in beaten}
        wrapped_beaten_game_ids = observed_beaten_game_ids - raw_completed_game_ids - mastered_game_ids
        for award in masteries:
            target = award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()
            mastery_counts[target] += 1
        for award in completions:
            if int(award["game_id"]) not in completed_game_ids:
                continue
            target = award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()
            completion_counts[target] += 1
        for award in beaten:
            if int(award["game_id"]) not in wrapped_beaten_game_ids:
                continue
            target = award["awarded"].astimezone(timezone.utc).date().replace(day=1).isoformat()
            beaten_counts[target] += 1
        return WrappedAwards(
            completed_games=len(completed_game_ids),
            completion_by_month=[MonthMetric(month, completion_counts[month]) for month in months],
            mastered_games=len(mastered_game_ids),
            mastery_by_month=[MonthMetric(month, mastery_counts[month]) for month in months],
            mastery_reliability="more_reliable",
            observed_beaten_games=len(observed_beaten_game_ids),
            effective_beaten_games=len(wrapped_beaten_game_ids),
            completion_only_beaten_games=0,
            mastery_only_beaten_games=0,
            beaten_by_month_partial=[MonthMetric(month, beaten_counts[month]) for month in months],
            beaten_reliability="stored_awards",
        )

    @staticmethod
    def _first_activity(days: dict[date, dict]) -> ActivityBoundary | None:
        if not days:
            return None
        first_day = min(days)
        values = days[first_day]
        return ActivityBoundary(
            date=first_day,
            achievement_at=values.get("first_achievement_at"),
            points=values.get("first_hardcore_points"),
            retro_points=values.get("first_retro_points"),
        )


def generate_wrapped_for_user(username: str, database, now: datetime | None = None) -> list[WrappedSummary]:
    return WrappedService(database).generate_for_user(username, now)
