"""Normalized hourly forecast data that the engine evaluates."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

# variables[name][member][hour], aligned with SiteForecast.times. Deterministic
# variables are shared by every member of an ensemble set.
Series = list[float | None]


@dataclass(frozen=True)
class MemberSet:
    name: str
    variables: dict[str, list[Series]]
    # Variables that have no spread because one deterministic run is shared.
    deterministic_variables: frozenset[str] = frozenset()

    @property
    def members(self) -> int:
        return len(next(iter(self.variables.values()), []))


@dataclass(frozen=True)
class SourceInfo:
    id: str
    name: str
    model: str
    variables: tuple[str, ...]
    ensemble_members: int
    horizon_end: datetime | None
    attribution: str
    url: str
    # Model run time when the provider reports it.
    run: datetime | None = None


@dataclass(frozen=True)
class WeeklyOutlook:
    week_start: date
    wind_speed_10m_mean_ms: float | None
    wind_speed_10m_anomaly_ms: float | None


@dataclass(frozen=True)
class SiteForecast:
    site_id: str
    fetched_at: datetime
    # UTC hourly timestamps; a value applies from its timestamp for one hour.
    times: list[datetime]
    ensemble: MemberSet
    # One-member set from the high-resolution DMI run; None beyond its horizon.
    deterministic: MemberSet | None
    sources: tuple[SourceInfo, ...]
    notes: tuple[str, ...] = ()
    weekly_outlook: tuple[WeeklyOutlook, ...] = ()


def _round(series: Series) -> Series:
    return [None if value is None else round(value, 2) for value in series]


def _member_set_to_dict(members: MemberSet) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    for name, series in members.variables.items():
        if name in members.deterministic_variables and all(s is series[0] or s == series[0] for s in series):
            variables[name] = {"shared": _round(series[0])}
        else:
            variables[name] = {"members": [_round(s) for s in series]}
    return {
        "name": members.name,
        "members": members.members,
        "deterministic_variables": sorted(members.deterministic_variables),
        "variables": variables,
    }


def _member_set_from_dict(data: dict[str, Any]) -> MemberSet:
    count = data["members"]
    variables = {
        name: [value["shared"]] * count if "shared" in value else value["members"]
        for name, value in data["variables"].items()
    }
    return MemberSet(
        name=data["name"],
        variables=variables,
        deterministic_variables=frozenset(data["deterministic_variables"]),
    )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def forecast_to_dict(forecast: SiteForecast) -> dict[str, Any]:
    """JSON-ready form used by the cache, briefing packs and snapshots."""
    return {
        "site_id": forecast.site_id,
        "fetched_at": _iso(forecast.fetched_at),
        "times": [time.isoformat() for time in forecast.times],
        "ensemble": _member_set_to_dict(forecast.ensemble),
        "deterministic": forecast.deterministic and _member_set_to_dict(forecast.deterministic),
        "sources": [
            {
                **source.__dict__,
                "variables": list(source.variables),
                "horizon_end": _iso(source.horizon_end),
                "run": _iso(source.run),
            }
            for source in forecast.sources
        ],
        "notes": list(forecast.notes),
        "weekly_outlook": [
            {**week.__dict__, "week_start": week.week_start.isoformat()} for week in forecast.weekly_outlook
        ],
    }


def forecast_from_dict(data: dict[str, Any]) -> SiteForecast:
    fetched_at = _parse(data["fetched_at"])
    assert fetched_at is not None
    return SiteForecast(
        site_id=data["site_id"],
        fetched_at=fetched_at,
        times=[datetime.fromisoformat(time) for time in data["times"]],
        ensemble=_member_set_from_dict(data["ensemble"]),
        deterministic=data["deterministic"] and _member_set_from_dict(data["deterministic"]),
        sources=tuple(
            SourceInfo(
                **{
                    **source,
                    "variables": tuple(source["variables"]),
                    "horizon_end": _parse(source["horizon_end"]),
                    "run": _parse(source.get("run")),
                }
            )
            for source in data["sources"]
        ),
        notes=tuple(data["notes"]),
        weekly_outlook=tuple(
            WeeklyOutlook(**{**week, "week_start": date.fromisoformat(week["week_start"])})
            for week in data.get("weekly_outlook", [])
        ),
    )
