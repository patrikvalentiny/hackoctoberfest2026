"""Sites, vessels, tasks and default limits.

All limits are public, typical defaults for decision support. They are not the
limits of any operator and must be replaced by site-approved values.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal

Comparison = Literal["max", "min"]
Segment = Literal["span", "work"]
VesselId = Literal["ctv", "sov"]
TaskId = Literal["nacelle", "hub_locked_rotor", "lifting"]


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    latitude: float
    longitude: float
    port: str
    ctv_transit_hours: float
    coordinates_verified: bool
    note: str


@dataclass(frozen=True)
class Limit:
    id: str
    label: str
    variable: str
    comparison: Comparison
    value: float
    unit: str
    # "span" applies from departure to return, "work" only while working.
    segment: Segment
    source: str


@dataclass(frozen=True)
class JobProfile:
    id: str
    site: Site
    vessel: VesselId
    task: TaskId
    work_hours_per_day: float
    days_needed: int
    start_date: date
    end_date: date
    consecutive: bool
    limits: tuple[Limit, ...]
    not_evaluated: tuple[str, ...] = field(default=())

    @property
    def transit_hours(self) -> float:
        # The SOV stays at the farm, so only a CTV sails out and back each day.
        return self.site.ctv_transit_hours if self.vessel == "ctv" else 0.0


SITES: dict[str, Site] = {
    site.id: site
    for site in (
        Site(
            id="hr1",
            name="Horns Rev 1",
            latitude=55.483,
            longitude=7.833,
            port="Esbjerg",
            ctv_transit_hours=1.0,
            coordinates_verified=False,
            note="Approximate centre; verify on EMODnet. CTV transit is an assumption.",
        ),
        Site(
            id="hr2",
            name="Horns Rev 2",
            latitude=55.600,
            longitude=7.583,
            port="Esbjerg",
            ctv_transit_hours=2.0,
            coordinates_verified=False,
            note="Approximate centre; verify on EMODnet. Transit about 2 h from Esbjerg (Wikipedia).",
        ),
        Site(
            id="hr3",
            name="Horns Rev 3",
            latitude=55.703,
            longitude=7.689,
            port="Hvide Sande",
            ctv_transit_hours=1.5,
            coordinates_verified=False,
            note="Serviced from Hvide Sande since 2024. CTV transit is an assumption.",
        ),
    )
}

CTV_HS_LIMIT_M = 1.5
SOV_HS_DEFAULT_M = 2.5
SOV_HS_MAX_M = 3.5

TASK_WIND_LIMITS_MS: dict[TaskId, tuple[str, float, str]] = {
    "nacelle": ("Nacelle work", 20.0, "Typical public value for nacelle work."),
    "hub_locked_rotor": (
        "Hub work, rotor locked",
        15.0,
        "Typical public value for hub entry with the rotor locked.",
    ),
    "lifting": (
        "Lifting and material transport",
        10.0,
        "Typical public value for crane lifts; limit is below 10 m/s.",
    ),
}

MIN_VISIBILITY_M = 1000.0

NOT_EVALUATED = (
    "Lightning: forecasts do not include it. Check live lightning data and the "
    "vessel's lightning procedure before and during work.",
    "Wave period and direction, current and vessel motion are not evaluated; "
    "only significant wave height is compared with the vessel limit.",
)


def vessel_hs_limit(vessel: VesselId, sov_hs_limit_m: float | None) -> float:
    if vessel == "ctv":
        if sov_hs_limit_m is not None:
            raise ValueError("A custom Hs limit applies only to an SOV.")
        return CTV_HS_LIMIT_M
    if sov_hs_limit_m is None:
        return SOV_HS_DEFAULT_M
    if not SOV_HS_DEFAULT_M <= sov_hs_limit_m <= SOV_HS_MAX_M:
        raise ValueError(
            f"SOV Hs limit must be between {SOV_HS_DEFAULT_M} and {SOV_HS_MAX_M} m."
        )
    return sov_hs_limit_m


def build_limits(
    vessel: VesselId, task: TaskId, sov_hs_limit_m: float | None = None
) -> tuple[Limit, ...]:
    hs_limit = vessel_hs_limit(vessel, sov_hs_limit_m)
    task_label, task_wind, task_source = TASK_WIND_LIMITS_MS[task]
    vessel_source = (
        "Typical public CTV transfer limit."
        if vessel == "ctv"
        else "Default for motion-compensated gangway; configurable up to 3.5 m."
    )
    return (
        Limit(
            id="wave_height",
            label=f"{vessel.upper()} significant wave height",
            variable="wave_height_m",
            comparison="max",
            value=hs_limit,
            unit="m",
            segment="span",
            source=vessel_source,
        ),
        Limit(
            id="wind_100m",
            label=f"{task_label}, wind at 100 m",
            variable="wind_speed_100m_ms",
            comparison="max",
            value=task_wind,
            unit="m/s",
            segment="work",
            source=task_source,
        ),
        Limit(
            id="visibility",
            label="Minimum visibility",
            variable="visibility_m",
            comparison="min",
            value=MIN_VISIBILITY_M,
            unit="m",
            segment="span",
            source="Project assumption, not an industry standard.",
        ),
    )


def profile_to_dict(profile: JobProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["start_date"] = profile.start_date.isoformat()
    data["end_date"] = profile.end_date.isoformat()
    return data


def profile_from_dict(data: dict[str, Any]) -> JobProfile:
    """Rebuild a profile exactly as saved, including its limits."""
    return JobProfile(
        id=data["id"],
        site=Site(**data["site"]),
        vessel=data["vessel"],
        task=data["task"],
        work_hours_per_day=data["work_hours_per_day"],
        days_needed=data["days_needed"],
        start_date=date.fromisoformat(data["start_date"]),
        end_date=date.fromisoformat(data["end_date"]),
        consecutive=data["consecutive"],
        limits=tuple(Limit(**limit) for limit in data["limits"]),
        not_evaluated=tuple(data["not_evaluated"]),
    )
