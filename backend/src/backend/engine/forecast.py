"""Normalized hourly forecast data that the engine evaluates."""

from dataclasses import dataclass
from datetime import datetime

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
