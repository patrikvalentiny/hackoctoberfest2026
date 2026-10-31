"""Open-Meteo fetchers normalized into a SiteForecast.

- Wind: ECMWF IFS 0.25 degree ensemble (control + 50 members), 15 days.
- Waves: ECMWF WAM deterministic. Open-Meteo's wave ensembles return no values
  for the Horns Rev area, so every wind member shares one wave run.
- Visibility: DMI seamless deterministic (HARMONIE, then ECMWF).
- 0-60 h deterministic: DMI HARMONIE AROME Europe.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.engine.forecast import MemberSet, Series, SiteForecast, SourceInfo
from backend.engine.profiles import Site

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

ENSEMBLE_MODEL = "ecmwf_ifs025"
WAVE_MODEL = "ecmwf_wam"
VISIBILITY_MODEL = "dmi_seamless"
DMI_MODEL = "dmi_harmonie_arome_europe"


class ProviderError(Exception):
    """A provider was unreachable or returned unusable data."""


def _hourly(payload: Any, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise ProviderError(f"{source} returned an invalid forecast.")
    hourly = payload["hourly"]
    if not isinstance(hourly.get("time"), list):
        raise ProviderError(f"{source} returned no forecast times.")
    return hourly


def _times(hourly: dict[str, Any], source: str) -> list[datetime]:
    try:
        return [datetime.fromisoformat(value).replace(tzinfo=UTC) for value in hourly["time"]]
    except (TypeError, ValueError) as error:
        raise ProviderError(f"{source} returned an invalid timestamp.") from error


def _values(hourly: dict[str, Any], name: str, length: int, source: str) -> Series:
    values = hourly.get(name)
    if not isinstance(values, list) or len(values) != length:
        raise ProviderError(f"{source} returned incomplete {name} data.")
    return [float(value) if isinstance(value, (int, float)) else None for value in values]


def ensemble_members(hourly: dict[str, Any], name: str, length: int, source: str) -> list[Series]:
    """Control run first, then member01, member02, ... in member order."""
    member_keys = sorted(key for key in hourly if key.startswith(f"{name}_member"))
    return [_values(hourly, key, length, source) for key in [name, *member_keys]]


def _aligned(times: list[datetime], other_times: list[datetime], values: Series) -> Series:
    by_time = dict(zip(other_times, values, strict=True))
    return [by_time.get(time) for time in times]


def _horizon_end(times: list[datetime], *series: Series) -> datetime | None:
    present = [time for i, time in enumerate(times) if all(values[i] is not None for values in series)]
    return present[-1] if present else None


def build_site_forecast(
    site: Site,
    ensemble: Any,
    marine: Any,
    visibility: Any,
    dmi: Any,
    fetched_at: datetime,
) -> SiteForecast:
    ensemble_hourly = _hourly(ensemble, "Open-Meteo ensemble")
    times = _times(ensemble_hourly, "Open-Meteo ensemble")
    count = len(times)
    wind_10m = ensemble_members(ensemble_hourly, "wind_speed_10m", count, "Open-Meteo ensemble")
    wind_100m = ensemble_members(ensemble_hourly, "wind_speed_100m", count, "Open-Meteo ensemble")
    if len(wind_10m) != len(wind_100m) or len(wind_10m) < 2:
        raise ProviderError("Open-Meteo ensemble returned mismatched members.")

    def deterministic(payload: Any, source: str, names: list[str]) -> tuple[list[datetime], dict[str, Series]]:
        hourly = _hourly(payload, source)
        own_times = _times(hourly, source)
        return own_times, {
            name: _aligned(times, own_times, _values(hourly, name, len(own_times), source))
            for name in names
        }

    _, waves = deterministic(marine, "Open-Meteo marine", ["wave_height", "wave_period", "wave_direction"])
    _, vis = deterministic(visibility, "Open-Meteo DMI seamless", ["visibility"])
    _, harmonie = deterministic(
        dmi, "Open-Meteo DMI HARMONIE", ["wind_speed_10m", "wind_speed_100m", "visibility"]
    )
    if all(value is None for value in waves["wave_height"]):
        raise ProviderError("Open-Meteo marine returned no wave heights for this site.")

    members = len(wind_10m)
    shared = {
        "wave_height_m": waves["wave_height"],
        "wave_period_s": waves["wave_period"],
        "wave_direction_deg": waves["wave_direction"],
        "visibility_m": vis["visibility"],
    }
    ensemble_set = MemberSet(
        name="ECMWF IFS ensemble",
        variables={
            "wind_speed_10m_ms": wind_10m,
            "wind_speed_100m_ms": wind_100m,
            **{name: [series] * members for name, series in shared.items()},
        },
        deterministic_variables=frozenset(shared),
    )
    deterministic_set = MemberSet(
        name="DMI HARMONIE",
        variables={
            "wind_speed_10m_ms": [harmonie["wind_speed_10m"]],
            "wind_speed_100m_ms": [harmonie["wind_speed_100m"]],
            "visibility_m": [harmonie["visibility"]],
            # HARMONIE has no waves; the same WAM run is used.
            "wave_height_m": [waves["wave_height"]],
            "wave_period_s": [waves["wave_period"]],
            "wave_direction_deg": [waves["wave_direction"]],
        },
        deterministic_variables=frozenset({"wind_speed_10m_ms", "wind_speed_100m_ms", "visibility_m", *shared}),
    )

    sources = (
        SourceInfo(
            id="ensemble_wind",
            name="ECMWF IFS 0.25° ensemble via Open-Meteo",
            model=ENSEMBLE_MODEL,
            variables=("wind_speed_10m", "wind_speed_100m"),
            ensemble_members=members,
            horizon_end=_horizon_end(times, wind_100m[0]),
            attribution=f"{ATTRIBUTION}; ECMWF (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/ensemble-api",
        ),
        SourceInfo(
            id="waves",
            name="ECMWF WAM via Open-Meteo Marine",
            model=WAVE_MODEL,
            variables=("wave_height", "wave_period", "wave_direction"),
            ensemble_members=1,
            horizon_end=_horizon_end(times, waves["wave_height"]),
            attribution=f"{ATTRIBUTION}; ECMWF (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/marine-weather-api",
        ),
        SourceInfo(
            id="visibility",
            name="DMI seamless via Open-Meteo",
            model=VISIBILITY_MODEL,
            variables=("visibility",),
            ensemble_members=1,
            horizon_end=_horizon_end(times, vis["visibility"]),
            attribution=f"{ATTRIBUTION}; DMI (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/dmi-api",
        ),
        SourceInfo(
            id="dmi_harmonie",
            name="DMI HARMONIE AROME via Open-Meteo",
            model=DMI_MODEL,
            variables=("wind_speed_10m", "wind_speed_100m", "visibility"),
            ensemble_members=1,
            horizon_end=_horizon_end(times, harmonie["wind_speed_100m"], harmonie["visibility"]),
            attribution=f"{ATTRIBUTION}; DMI (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/dmi-api",
        ),
    )
    return SiteForecast(
        site_id=site.id,
        fetched_at=fetched_at,
        times=times,
        ensemble=ensemble_set,
        deterministic=deterministic_set,
        sources=sources,
        notes=(
            "Wave heights are deterministic (ECMWF WAM); probabilities reflect "
            "wind ensemble spread only.",
            "Open-Meteo does not report model run times; data age is measured from fetch time.",
        ),
    )


async def fetch_site_forecast(site: Site, client: httpx.AsyncClient | None = None) -> SiteForecast:
    location = {"latitude": site.latitude, "longitude": site.longitude, "timezone": "GMT"}
    requests = [
        (
            ENSEMBLE_URL,
            {
                **location,
                "models": ENSEMBLE_MODEL,
                "hourly": "wind_speed_10m,wind_speed_100m",
                "wind_speed_unit": "ms",
                "forecast_days": 15,
            },
        ),
        (
            MARINE_URL,
            {
                **location,
                "models": WAVE_MODEL,
                "hourly": "wave_height,wave_period,wave_direction",
                "forecast_days": 16,
            },
        ),
        (
            FORECAST_URL,
            {**location, "models": VISIBILITY_MODEL, "hourly": "visibility", "forecast_days": 16},
        ),
        (
            FORECAST_URL,
            {
                **location,
                "models": DMI_MODEL,
                "hourly": "wind_speed_10m,wind_speed_100m,visibility",
                "wind_speed_unit": "ms",
                "forecast_days": 4,
            },
        ),
    ]
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30)
    try:
        responses = await asyncio.gather(*(http.get(url, params=params) for url, params in requests))
        for response in responses:
            response.raise_for_status()
        payloads = [response.json() for response in responses]
    except httpx.HTTPError as error:
        raise ProviderError("Open-Meteo is unavailable. Try again when online.") from error
    except ValueError as error:
        raise ProviderError("Open-Meteo returned unreadable forecast data.") from error
    finally:
        if owns_client:
            await http.aclose()
    return build_site_forecast(site, *payloads, fetched_at=datetime.now(UTC))
