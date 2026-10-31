"""Shared fixtures: synthetic forecasts, provider payloads and API state."""

import unittest
from datetime import UTC, date, datetime, timedelta

from backend.api import planner
from backend.engine.forecast import MemberSet, SiteForecast
from backend.engine.profiles import SITES, JobProfile, build_limits
from backend.ingest.ecmwf_waef import WaveEnsemble
from backend.store import Store

DAY = date(2026, 11, 16)
FETCHED = datetime(2026, 11, 10, 0, tzinfo=UTC)


def make_forecast(
    members: int = 4,
    days: int = 10,
    wind_100m: float = 8.0,
    wave: float = 1.0,
    visibility: float | None = 20000.0,
    overrides: dict[tuple[str, int], list[float | None]] | None = None,
    fetched_at: datetime = FETCHED,
    deterministic: dict[str, list[float | None]] | None = None,
    start: datetime = datetime(2026, 11, 10, tzinfo=UTC),
) -> SiteForecast:
    """Calm conditions everywhere unless overridden per (variable, member)."""
    times = [start + timedelta(hours=h) for h in range(days * 24)]
    base = {
        "wind_speed_10m_ms": wind_100m * 0.8,
        "wind_speed_100m_ms": wind_100m,
        "wave_height_m": wave,
        "visibility_m": visibility,
    }
    variables = {name: [[value] * len(times) for _ in range(members)] for name, value in base.items()}
    for (name, member), series in (overrides or {}).items():
        variables[name][member] = series
    deterministic_set = None
    if deterministic is not None:
        deterministic_set = MemberSet(
            name="DMI test",
            variables={name: [deterministic.get(name, [base[name]] * len(times))] for name in base},
        )
    return SiteForecast(
        site_id="hr1",
        fetched_at=fetched_at,
        times=times,
        ensemble=MemberSet(name="test", variables=variables),
        deterministic=deterministic_set,
        sources=(),
    )


def make_profile(vessel: str = "ctv", task: str = "nacelle", hours: float = 4, **kwargs) -> JobProfile:
    return JobProfile(
        id=kwargs.pop("id", "test"),
        site=SITES[kwargs.pop("site_id", "hr1")],
        vessel=vessel,  # type: ignore[arg-type]
        task=task,  # type: ignore[arg-type]
        work_hours_per_day=hours,
        days_needed=kwargs.pop("days_needed", 1),
        start_date=kwargs.pop("start_date", DAY),
        end_date=kwargs.pop("end_date", DAY),
        consecutive=kwargs.pop("consecutive", False),
        limits=build_limits(vessel, task),  # type: ignore[arg-type]
    )


def series_with(
    forecast: SiteForecast, value: float | None, start: datetime, end: datetime, base: float | None
) -> list[float | None]:
    return [value if start <= time < end else base for time in forecast.times]


def provider_payloads(hours: int = 48, start: datetime = datetime(2026, 11, 10, tzinfo=UTC)) -> dict:
    """Open-Meteo responses: control + 2 wind members, calm, `hours` long."""
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(hours)]
    ensemble = {"time": times, "wind_speed_10m": [5.0] * hours, "wind_speed_100m": [7.0] * hours}
    for member in (1, 2):
        ensemble[f"wind_speed_10m_member{member:02}"] = [5.0 + member] * hours
        ensemble[f"wind_speed_100m_member{member:02}"] = [7.0 + member] * hours
    return {
        "ensemble": {"hourly": ensemble},
        "marine": {
            "hourly": {
                "time": times,
                "wave_height": [1.0] * hours,
                "wave_period": [6.0] * hours,
                "wave_direction": [220.0] * hours,
            }
        },
        "swell": {
            "hourly": {"time": times, "swell_wave_height": [0.4] * hours, "swell_wave_period": [8.0] * hours}
        },
        "visibility": {"hourly": {"time": times, "visibility": [20000.0] * hours}},
        "dmi": {
            "hourly": {
                "time": times,
                "wind_speed_10m": [4.0] * hours,
                "wind_speed_100m": [6.0] * hours,
                "visibility": [21000.0] * hours,
            }
        },
        "seasonal": {
            "weekly": {
                "time": ["2026-11-09", "2026-11-16"],
                "wind_speed_10m_mean": [6.5, 8.0],
                "wind_speed_10m_anomaly": [0.5, 1.2],
            }
        },
    }


def wave_ensemble(run: datetime = datetime(2026, 11, 10, tzinfo=UTC)) -> WaveEnsemble:
    return WaveEnsemble(
        run=run,
        times=[run + timedelta(hours=6 * i) for i in range(5)],
        members={1: [1.0, 1.6, 2.2, 2.2, 2.2], 2: [0.5, 0.5, 0.5, 0.5, 0.5]},
        grid_latitude=55.5,
        grid_longitude=7.75,
    )


class ApiTestCase(unittest.TestCase):
    """Isolates planner state and uses an in-memory store per test."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from backend.main import app

        self.client = TestClient(app)
        self.store = Store(":memory:")
        previous = planner._store
        planner._store = self.store
        planner._forecasts.clear()
        planner._profiles.clear()
        planner._offline.clear()

        def restore() -> None:
            planner._forecasts.clear()
            planner._profiles.clear()
            planner._offline.clear()
            planner._store = previous
            self.store.close()

        self.addCleanup(restore)

    def create_profile(self, **body) -> dict:
        response = self.client.post(
            "/api/profiles",
            json={"site_id": "hr1", "vessel": "ctv", "task": "nacelle", "work_hours_per_day": 4, **body},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()
