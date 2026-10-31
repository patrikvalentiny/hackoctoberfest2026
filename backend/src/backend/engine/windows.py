"""Deterministic window, probability and explanation calculations.

Everything here is a pure function of a SiteForecast and a JobProfile. The
results support planning only; they never state that conditions are safe.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sunrise, sunset

from backend.engine.forecast import MemberSet, SiteForecast, WeeklyOutlook
from backend.engine.profiles import JobProfile, Limit, Site

LOCAL_TZ = ZoneInfo("Europe/Copenhagen")
STEP = timedelta(minutes=15)
HOUR = timedelta(hours=1)
DMI_HORIZON = timedelta(hours=60)
MEDIUM_HORIZON = timedelta(days=7)
STALE_AFTER = timedelta(hours=12)
OUTLOOK_DAYS = 21

Confidence = Literal["high", "medium", "low", "outlook"]
CONFIDENCE_RANK: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2, "outlook": 3}


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DayResult:
    date: date
    sunrise: datetime
    sunset: datetime
    confidence: Confidence
    members: int
    members_with_window: int | None
    probability: float | None
    window: Window | None
    members_in_window: int | None
    deterministic_window: Window | None
    deterministic_evaluated: bool
    limiting_parameter: str | None
    limit_failures: dict[str, int]
    recompute_at: datetime | None
    note: str | None
    # Smallest relative distance to a limit in the window, ensemble median.
    margin: float | None = None
    weekly_outlook: WeeklyOutlook | None = None


@dataclass(frozen=True)
class TaskFit:
    data_age_hours: float
    reference: str | None
    fits: bool | None
    last_transfer_back: datetime | None
    latest_start: datetime | None
    ensemble_fraction: float | None
    blocking_limits: tuple[str, ...]
    sunset: datetime
    note: str | None


def daylight(site: Site, day: date) -> tuple[datetime, datetime]:
    observer = Observer(latitude=site.latitude, longitude=site.longitude)
    return (
        sunrise(observer, day, tzinfo=LOCAL_TZ).astimezone(UTC),
        sunset(observer, day, tzinfo=LOCAL_TZ).astimezone(UTC),
    )


def _ceil_step(value: datetime) -> datetime:
    floored = value.replace(minute=value.minute - value.minute % 15, second=0, microsecond=0)
    return floored if floored == value else floored + STEP


class _Checker:
    """Precomputed limit pass/fail per member and hour for one member set."""

    def __init__(self, times: list[datetime], members: MemberSet, limits: tuple[Limit, ...]):
        self.index = {time: i for i, time in enumerate(times)}
        self.members = members.members
        self.limits = limits
        self.ok: dict[str, list[list[bool]]] = {}
        self.values: dict[str, list[list[float | None]]] = {}
        for limit in limits:
            series = members.variables.get(limit.variable)
            if series is None:
                raise ValueError(f"Forecast has no {limit.variable} for limit {limit.id}.")
            self.values[limit.id] = series
            self.ok[limit.id] = [[_passes(value, limit) for value in member] for member in series]

    def hours(self, start: datetime, end: datetime) -> list[int] | None:
        """Indexes of hourly values overlapping [start, end); None if data is missing."""
        hour = start.replace(minute=0, second=0, microsecond=0)
        indexes = []
        while hour < end:
            index = self.index.get(hour)
            if index is None:
                return None
            indexes.append(index)
            hour += HOUR
        return indexes

    def complete(self, start: datetime, end: datetime) -> bool:
        """Whether member 0 has a value for every limit in [start, end)."""
        indexes = self.hours(start, end)
        return indexes is not None and all(
            self.values[limit.id][0][i] is not None for limit in self.limits for i in indexes
        )

    def failing(self, member: int, start: datetime, end: datetime, limits: list[Limit]) -> set[str]:
        indexes = self.hours(start, end)
        if indexes is None:
            return {limit.id for limit in limits}
        return {
            limit.id
            for limit in limits
            if not all(self.ok[limit.id][member][i] for i in indexes)
        }

    def fits(self, member: int, start: datetime, transit: timedelta, work: timedelta) -> bool:
        span_limits = [limit for limit in self.limits if limit.segment == "span"]
        work_limits = [limit for limit in self.limits if limit.segment == "work"]
        end = start + 2 * transit + work
        return not self.failing(member, start, end, span_limits) and not self.failing(
            member, start + transit, start + transit + work, work_limits
        )


def _passes(value: float | None, limit: Limit) -> bool:
    # Missing data never counts as within limits.
    if value is None:
        return False
    return value <= limit.value if limit.comparison == "max" else value >= limit.value


def _confidence(sunset_utc: datetime, forecast: SiteForecast) -> Confidence:
    if not forecast.times or sunset_utc > forecast.times[-1] + HOUR:
        return "outlook"
    lead = sunset_utc - forecast.fetched_at
    if lead <= DMI_HORIZON:
        return "high"
    if lead <= MEDIUM_HORIZON:
        return "medium"
    return "low"


def _candidate_starts(rise: datetime, set_: datetime, total: timedelta) -> list[datetime]:
    starts = []
    start = _ceil_step(rise)
    while start + total <= set_:
        starts.append(start)
        start += STEP
    return starts


def evaluate_day(profile: JobProfile, forecast: SiteForecast, day: date) -> DayResult:
    rise, set_ = daylight(profile.site, day)
    confidence = _confidence(set_, forecast)
    transit = timedelta(hours=profile.transit_hours)
    work = timedelta(hours=profile.work_hours_per_day)
    total = 2 * transit + work
    recompute_at = set_ - DMI_HORIZON
    recompute = recompute_at if recompute_at > forecast.fetched_at else None
    members = forecast.ensemble.members

    if confidence == "outlook":
        week = next(
            (w for w in forecast.weekly_outlook if w.week_start <= day < w.week_start + timedelta(days=7)),
            None,
        )
        return DayResult(
            date=day, sunrise=rise, sunset=set_, confidence=confidence, members=members,
            members_with_window=None, probability=None, window=None, members_in_window=None,
            deterministic_window=None, deterministic_evaluated=False, limiting_parameter=None,
            limit_failures={}, recompute_at=recompute,
            note=(
                "Beyond the hourly ensemble horizon; only a weekly mean-wind signal applies, "
                "with no work window or probability."
                if week
                else "Beyond the hourly ensemble horizon; no outlook data is available."
            ),
            weekly_outlook=week,
        )

    # Windows start no earlier than the data time, so today's past hours drop out.
    starts = _candidate_starts(max(rise, forecast.fetched_at), set_, total)
    if not starts:
        remaining = set_ - max(rise, min(forecast.fetched_at, set_))
        return DayResult(
            date=day, sunrise=rise, sunset=set_, confidence=confidence, members=members,
            members_with_window=0, probability=0.0, window=None, members_in_window=0,
            deterministic_window=None, deterministic_evaluated=False,
            limiting_parameter="daylight", limit_failures={"daylight": members},
            recompute_at=recompute,
            note=(
                f"Transit and work need {total.total_seconds() / 3600:.1f} h but daylight "
                f"left is {remaining.total_seconds() / 3600:.1f} h."
            ),
        )

    checker = _Checker(forecast.times, forecast.ensemble, profile.limits)
    passing = [0] * len(starts)
    members_with_window = 0
    failures = {limit.id: 0 for limit in profile.limits}
    for member in range(members):
        has_window = False
        for i, start in enumerate(starts):
            if checker.fits(member, start, transit, work):
                passing[i] += 1
                has_window = True
        if has_window:
            members_with_window += 1
        else:
            for limit_id in checker.failing(member, rise, set_, list(profile.limits)):
                failures[limit_id] += 1

    best = max(range(len(starts)), key=lambda i: (passing[i], -i))
    window = Window(starts[best], starts[best] + total) if passing[best] else None
    limiting = max(failures, key=lambda key: failures[key]) if any(failures.values()) else None

    deterministic_window = None
    deterministic_evaluated = False
    if forecast.deterministic is not None and confidence == "high":
        dmi = _Checker(forecast.times, forecast.deterministic, profile.limits)
        if dmi.complete(starts[0], starts[-1] + total):
            deterministic_evaluated = True
            deterministic_window = next(
                (Window(start, start + total) for start in starts if dmi.fits(0, start, transit, work)),
                None,
            )

    return DayResult(
        date=day, sunrise=rise, sunset=set_, confidence=confidence, members=members,
        members_with_window=members_with_window,
        probability=round(members_with_window / members, 3), window=window,
        members_in_window=passing[best], deterministic_window=deterministic_window,
        deterministic_evaluated=deterministic_evaluated, limiting_parameter=limiting,
        limit_failures=failures, recompute_at=recompute, note=None,
        margin=_margin(forecast, profile, window) if window else None,
    )


def _margin(forecast: SiteForecast, profile: JobProfile, window: Window) -> float | None:
    median = _median_set(forecast.ensemble)
    checker = _Checker(forecast.times, median, profile.limits)
    indexes = checker.hours(window.start, window.end)
    margins = []
    for limit in profile.limits:
        for i in indexes or []:
            value = median.variables[limit.variable][0][i]
            if value is not None:
                distance = limit.value - value if limit.comparison == "max" else value - limit.value
                margins.append(distance / limit.value)
    return round(min(margins), 3) if margins else None


def find_windows(profile: JobProfile, forecast: SiteForecast) -> tuple[list[DayResult], list[date]]:
    """Evaluate every day in the profile's range and suggest days to use."""
    days = []
    day = profile.start_date
    while day <= profile.end_date:
        days.append(evaluate_day(profile, forecast, day))
        day += timedelta(days=1)
    return days, suggest_days(profile, days)


def suggest_days(profile: JobProfile, days: list[DayResult]) -> list[date]:
    candidates = [day for day in days if day.probability and day.confidence != "outlook"]
    if profile.consecutive:
        by_date = {day.date: day for day in candidates}
        blocks = []
        for first in candidates:
            block = [by_date.get(first.date + timedelta(days=n)) for n in range(profile.days_needed)]
            if all(block):
                probabilities = [day.probability or 0.0 for day in block if day]
                blocks.append((min(probabilities), sum(probabilities), first.date, block))
        if not blocks:
            return []
        best = max(blocks, key=lambda item: (item[0], item[1], -item[2].toordinal()))
        return [day.date for day in best[3] if day]
    ranked = sorted(
        candidates,
        key=lambda day: (
            -(day.probability or 0.0),
            -(day.margin if day.margin is not None else -1.0),
            CONFIDENCE_RANK[day.confidence],
            day.date,
        ),
    )
    return sorted(day.date for day in ranked[: profile.days_needed])


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)


def explain_day(profile: JobProfile, forecast: SiteForecast, day: date) -> tuple[DayResult, list[dict]]:
    """Hourly values against limits for one local day."""
    result = evaluate_day(profile, forecast, day)
    checker = _Checker(forecast.times, forecast.ensemble, profile.limits)
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ).astimezone(UTC)
    end = (datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ) + timedelta(days=1)).astimezone(UTC)
    hours = []
    hour = start
    while hour < end:
        index = checker.index.get(hour)
        if index is not None:
            hours.append(_explain_hour(profile, forecast, checker, hour, index, result))
        hour += HOUR
    return result, hours


def _explain_hour(
    profile: JobProfile, forecast: SiteForecast, checker: _Checker, hour: datetime, index: int, result: DayResult
) -> dict:
    variables = {}
    for name, series in forecast.ensemble.variables.items():
        values = [member[index] for member in series if member[index] is not None]
        if not values:
            variables[name] = None
        elif name in forecast.ensemble.deterministic_variables:
            variables[name] = {"value": values[0]}
        else:
            variables[name] = {
                "min": round(min(values), 2),
                "p10": _quantile(values, 0.1),
                "median": _quantile(values, 0.5),
                "p90": _quantile(values, 0.9),
                "max": round(max(values), 2),
            }
    deterministic = None
    if forecast.deterministic is not None:
        deterministic = {
            name: series[0][index] for name, series in forecast.deterministic.variables.items()
        }
    return {
        "time": hour,
        "daylight": result.sunrise < hour + HOUR and hour < result.sunset,
        "variables": variables,
        "deterministic": deterministic,
        "members_failing": {
            limit.id: sum(not checker.ok[limit.id][m][index] for m in range(checker.members))
            for limit in profile.limits
        },
    }


def _median_set(members: MemberSet) -> MemberSet:
    variables = {}
    for name, series in members.variables.items():
        median = []
        for index in range(len(series[0])):
            values = [member[index] for member in series if member[index] is not None]
            median.append(_quantile(values, 0.5) if values else None)
        variables[name] = [median]
    return MemberSet(name=f"{members.name} median", variables=variables)


def check_task_fits(
    profile: JobProfile, forecast: SiteForecast, start: datetime, duration: timedelta, now: datetime
) -> TaskFit:
    """Whether a task starting at `start` fits before the last transfer back.

    Uses the DMI deterministic run when it covers the period, otherwise the
    ensemble median. Timing is withheld when data is older than 12 hours.
    """
    start = start.astimezone(UTC)
    age = now - forecast.fetched_at
    _, set_ = daylight(profile.site, start.astimezone(LOCAL_TZ).date())
    base = dict(data_age_hours=round(age.total_seconds() / 3600, 1), sunset=set_)
    if age > STALE_AFTER:
        return TaskFit(
            **base, reference=None, fits=None, last_transfer_back=None, latest_start=None,
            ensemble_fraction=None, blocking_limits=(),
            note="Forecast data is older than 12 hours; no timing is given. Ask the vessel.",
        )

    transit = timedelta(hours=profile.transit_hours)
    span_limits = [limit for limit in profile.limits if limit.segment == "span"]
    work_limits = [limit for limit in profile.limits if limit.segment == "work"]

    reference_name, reference = "ensemble median", _median_set(forecast.ensemble)
    if forecast.deterministic is not None:
        if _Checker(forecast.times, forecast.deterministic, profile.limits).complete(start, set_):
            reference_name, reference = "DMI HARMONIE deterministic", forecast.deterministic
    checker = _Checker(forecast.times, reference, profile.limits)

    ensemble = _Checker(forecast.times, forecast.ensemble, profile.limits)
    ensemble_ok = sum(
        not ensemble.failing(m, start, start + duration, work_limits)
        and not ensemble.failing(m, start, start + duration + transit, span_limits)
        for m in range(ensemble.members)
    )
    ensemble_fraction = round(ensemble_ok / ensemble.members, 3)

    blocking = checker.failing(0, start, start + transit, span_limits)
    if start + transit > set_ or blocking:
        return TaskFit(
            **base, reference=reference_name, fits=False, last_transfer_back=None, latest_start=None,
            ensemble_fraction=ensemble_fraction, blocking_limits=tuple(sorted(blocking or {"daylight"})),
            note="No transfer back within daylight and limits from this start time.",
        )

    last_transfer = start
    while (
        last_transfer + STEP + transit <= set_
        and not checker.failing(0, start, last_transfer + STEP + transit, span_limits)
    ):
        last_transfer += STEP

    latest_start = None
    candidate = start
    while candidate + duration <= last_transfer:
        if not checker.failing(0, candidate, candidate + duration, work_limits):
            latest_start = candidate
        candidate += STEP

    fits = start + duration <= last_transfer and not checker.failing(0, start, start + duration, work_limits)
    blocking_limits: set[str] = set()
    if not fits:
        blocking_limits = checker.failing(0, start, start + duration, work_limits)
        if start + duration > last_transfer:
            ended = checker.failing(0, start, start + duration + transit, span_limits)
            blocking_limits |= ended or {"daylight"}
    return TaskFit(
        **base, reference=reference_name, fits=fits, last_transfer_back=last_transfer,
        latest_start=latest_start, ensemble_fraction=ensemble_fraction,
        blocking_limits=tuple(sorted(blocking_limits)), note=None,
    )


def current_hour(profile_limits: tuple[Limit, ...], forecast: SiteForecast, now: datetime) -> dict | None:
    """Forecast values for the hour containing `now`; not an observation.

    Uses DMI HARMONIE when it has every value, otherwise the ensemble median.
    """
    hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    index = {time: i for i, time in enumerate(forecast.times)}.get(hour)
    if index is None:
        return None
    reference_name, reference = "ensemble median", _median_set(forecast.ensemble)
    if forecast.deterministic is not None and all(
        forecast.deterministic.variables[limit.variable][0][index] is not None for limit in profile_limits
    ):
        reference_name, reference = "DMI HARMONIE deterministic", forecast.deterministic
    values = {name: series[0][index] for name, series in reference.variables.items()}
    return {
        "time": hour,
        "reference": reference_name,
        "values": values,
        "limits": [
            {
                "id": limit.id,
                "label": limit.label,
                "value": values.get(limit.variable),
                "limit": limit.value,
                "unit": limit.unit,
                "comparison": limit.comparison,
                "within_limit": None
                if values.get(limit.variable) is None
                else _passes(values.get(limit.variable), limit),
            }
            for limit in profile_limits
        ],
    }
