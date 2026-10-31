"""Open-Meteo fetchers normalized into a SiteForecast.

- Wind: ECMWF IFS 0.25 degree ensemble (control + 50 members), 15 days.
- Waves: the ECMWF waef ensemble (see ecmwf_waef) when downloaded, paired
  with wind members by number. Otherwise ECMWF WAM deterministic, shared by
  every member, because Open-Meteo's wave ensembles return no values here.
- Swell: Open-Meteo default marine model, for display only.
- Visibility: DMI seamless deterministic (HARMONIE, then ECMWF).
- 0-60 h deterministic: DMI HARMONIE AROME Europe.
- Days 16+: ECMWF EC46 weekly mean wind via the Seasonal API.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from backend.engine.forecast import (
    MemberSet,
    Series,
    SiteForecast,
    SourceInfo,
    WeeklyOutlook,
)
from backend.engine.profiles import Site
from backend.ingest.ecmwf_waef import WaveEnsemble, hourly

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
SEASONAL_URL = "https://seasonal-api.open-meteo.com/v1/seasonal"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

ENSEMBLE_MODEL = "ecmwf_ifs025"
WAVE_MODEL = "ecmwf_wam"
VISIBILITY_MODEL = "dmi_seamless"
DMI_MODEL = "dmi_harmonie_arome_europe"
OUTLOOK_MODEL = "ecmwf_ec46"

# Payloads the forecast cannot be built without; the rest are optional.
REQUIRED = ("ensemble", "marine", "visibility", "dmi")
# A wave ensemble run this much older than the wind data is not paired.
MAX_WAVE_RUN_AGE = timedelta(hours=36)


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


def _weekly_outlook(payload: Any) -> tuple[WeeklyOutlook, ...]:
    weekly = payload.get("weekly") if isinstance(payload, dict) else None
    if not isinstance(weekly, dict) or not isinstance(weekly.get("time"), list):
        raise ProviderError("Open-Meteo seasonal returned an invalid outlook.")
    count = len(weekly["time"])
    means = _values(weekly, "wind_speed_10m_mean", count, "Open-Meteo seasonal")
    anomalies = _values(weekly, "wind_speed_10m_anomaly", count, "Open-Meteo seasonal")
    try:
        return tuple(
            WeeklyOutlook(
                week_start=date.fromisoformat(start), wind_speed_10m_mean_ms=mean, wind_speed_10m_anomaly_ms=anomaly
            )
            for start, mean, anomaly in zip(weekly["time"], means, anomalies, strict=True)
            if mean is not None
        )
    except (TypeError, ValueError) as error:
        raise ProviderError("Open-Meteo seasonal returned an invalid week.") from error


def build_site_forecast(
    site: Site,
    payloads: dict[str, Any],
    fetched_at: datetime,
    waves: WaveEnsemble | None = None,
) -> SiteForecast:
    ensemble_hourly = _hourly(payloads["ensemble"], "Open-Meteo ensemble")
    times = _times(ensemble_hourly, "Open-Meteo ensemble")
    count = len(times)
    wind_10m = ensemble_members(ensemble_hourly, "wind_speed_10m", count, "Open-Meteo ensemble")
    wind_100m = ensemble_members(ensemble_hourly, "wind_speed_100m", count, "Open-Meteo ensemble")
    if len(wind_10m) != len(wind_100m) or len(wind_10m) < 2:
        raise ProviderError("Open-Meteo ensemble returned mismatched members.")

    def deterministic(payload: Any, source: str, names: list[str]) -> dict[str, Series]:
        hourly = _hourly(payload, source)
        own_times = _times(hourly, source)
        return {
            name: _aligned(times, own_times, _values(hourly, name, len(own_times), source))
            for name in names
        }

    wam = deterministic(payloads["marine"], "Open-Meteo marine", ["wave_height", "wave_period", "wave_direction"])
    vis = deterministic(payloads["visibility"], "Open-Meteo DMI seamless", ["visibility"])
    harmonie = deterministic(
        payloads["dmi"], "Open-Meteo DMI HARMONIE", ["wind_speed_10m", "wind_speed_100m", "visibility"]
    )
    if all(value is None for value in wam["wave_height"]):
        raise ProviderError("Open-Meteo marine returned no wave heights for this site.")
    notes: list[str] = []
    empty: Series = [None] * count
    swell: dict[str, Series] = {"swell_wave_height": empty, "swell_wave_period": empty}
    try:
        if payloads.get("swell") is None:
            raise ProviderError("no swell response")
        swell = deterministic(payloads["swell"], "Open-Meteo marine swell", list(swell))
    except ProviderError:
        notes.append("Swell data was unavailable for this fetch.")
    outlook: tuple[WeeklyOutlook, ...] = ()
    try:
        if payloads.get("seasonal") is None:
            raise ProviderError("no seasonal response")
        outlook = _weekly_outlook(payloads["seasonal"])
    except ProviderError:
        notes.append("The EC46 weekly outlook was unavailable for this fetch.")

    numbers = [n for n in range(1, len(wind_10m)) if waves is not None and n in waves.members]
    if waves is not None and not numbers:
        notes.append("The ECMWF wave ensemble had no members matching the wind ensemble; it was not used.")
        waves = None
    if waves is not None and fetched_at - waves.run > MAX_WAVE_RUN_AGE:
        notes.append(
            f"The stored ECMWF wave ensemble (run {waves.run:%Y-%m-%d %H} UTC) is too old to pair "
            "with this wind forecast; it was not used."
        )
        waves = None

    shared: dict[str, Series] = {
        "wave_period_s": wam["wave_period"],
        "wave_direction_deg": wam["wave_direction"],
        "swell_wave_height_m": swell["swell_wave_height"],
        "swell_wave_period_s": swell["swell_wave_period"],
        "visibility_m": vis["visibility"],
    }
    if waves is not None:
        # Wind member n (Open-Meteo memberNN) is paired with waef member n.
        # The control wind run has no waef counterpart and is left out.
        wave_members = []
        for number in numbers:
            interpolated = hourly(waves, number, times)
            wave_members.append(
                [value if value is not None else wam["wave_height"][i] for i, value in enumerate(interpolated)]
            )
        wind_10m = [wind_10m[n] for n in numbers]
        wind_100m = [wind_100m[n] for n in numbers]
        wave_end = waves.times[-1]
        notes.append(
            f"Wave heights: ECMWF waef run {waves.run:%Y-%m-%d %H} UTC, {len(numbers)} members "
            "paired with wind members by number; six-hourly values interpolated to hourly. "
            "The wind and wave runs can differ by up to 12 h, so pairing is approximate."
        )
        if wave_end < times[-1]:
            notes.append(f"After {wave_end:%Y-%m-%d %H} UTC wave heights fall back to deterministic WAM.")
    else:
        wave_members = [wam["wave_height"]] * len(wind_10m)
        shared["wave_height_m"] = wam["wave_height"]
        notes.append(
            "Wave heights are deterministic (ECMWF WAM); probabilities reflect wind "
            "ensemble spread only. The ECMWF wave ensemble has not been downloaded yet."
        )
    notes.append("Open-Meteo does not report model run times; their data age is measured from fetch time.")

    members = len(wind_10m)
    ensemble_set = MemberSet(
        name="ECMWF IFS ensemble",
        variables={
            "wind_speed_10m_ms": wind_10m,
            "wind_speed_100m_ms": wind_100m,
            "wave_height_m": wave_members,
            **{name: [series] * members for name, series in shared.items() if name != "wave_height_m"},
        },
        deterministic_variables=frozenset(shared),
    )
    deterministic_set = MemberSet(
        name="DMI HARMONIE",
        variables={
            "wind_speed_10m_ms": [harmonie["wind_speed_10m"]],
            "wind_speed_100m_ms": [harmonie["wind_speed_100m"]],
            "visibility_m": [harmonie["visibility"]],
            # HARMONIE has no waves; the deterministic WAM run is used.
            "wave_height_m": [wam["wave_height"]],
            "wave_period_s": [wam["wave_period"]],
            "wave_direction_deg": [wam["wave_direction"]],
            "swell_wave_height_m": [swell["swell_wave_height"]],
            "swell_wave_period_s": [swell["swell_wave_period"]],
        },
        deterministic_variables=frozenset(
            {"wind_speed_10m_ms", "wind_speed_100m_ms", "visibility_m", "wave_height_m", *shared}
        ),
    )

    sources = [
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
            horizon_end=_horizon_end(times, wam["wave_height"]),
            attribution=f"{ATTRIBUTION}; ECMWF (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/marine-weather-api",
        ),
        SourceInfo(
            id="swell",
            name="Open-Meteo Marine default model",
            model="best_match",
            variables=("swell_wave_height", "swell_wave_period"),
            ensemble_members=1,
            horizon_end=_horizon_end(times, swell["swell_wave_height"]),
            attribution=ATTRIBUTION,
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
        SourceInfo(
            id="outlook",
            name="ECMWF EC46 weekly outlook via Open-Meteo Seasonal",
            model=OUTLOOK_MODEL,
            variables=("wind_speed_10m_mean", "wind_speed_10m_anomaly"),
            ensemble_members=0,
            horizon_end=None,
            attribution=f"{ATTRIBUTION}; ECMWF (CC BY 4.0)",
            url="https://open-meteo.com/en/docs/seasonal-forecast-api",
        ),
    ]
    if waves is not None:
        sources.insert(
            1,
            SourceInfo(
                id="wave_ensemble",
                name="ECMWF waef wave ensemble (open data)",
                model="waef swh",
                variables=("swh",),
                ensemble_members=len(waves.members),
                horizon_end=waves.times[-1],
                attribution="ECMWF open data (CC BY 4.0)",
                url="https://www.ecmwf.int/en/forecasts/datasets/open-data",
                run=waves.run,
            ),
        )
    return SiteForecast(
        site_id=site.id,
        fetched_at=fetched_at,
        times=times,
        ensemble=ensemble_set,
        deterministic=deterministic_set,
        sources=tuple(sources),
        notes=tuple(notes),
        weekly_outlook=outlook,
    )


def _requests(site: Site) -> dict[str, tuple[str, dict[str, Any]]]:
    location = {"latitude": site.latitude, "longitude": site.longitude, "timezone": "GMT"}
    return {
        "ensemble": (
            ENSEMBLE_URL,
            {
                **location,
                "models": ENSEMBLE_MODEL,
                "hourly": "wind_speed_10m,wind_speed_100m",
                "wind_speed_unit": "ms",
                "forecast_days": 15,
            },
        ),
        "marine": (
            MARINE_URL,
            {**location, "models": WAVE_MODEL, "hourly": "wave_height,wave_period,wave_direction", "forecast_days": 16},
        ),
        "swell": (
            MARINE_URL,
            {**location, "hourly": "swell_wave_height,swell_wave_period", "forecast_days": 16},
        ),
        "visibility": (
            FORECAST_URL,
            {**location, "models": VISIBILITY_MODEL, "hourly": "visibility", "forecast_days": 16},
        ),
        "dmi": (
            FORECAST_URL,
            {
                **location,
                "models": DMI_MODEL,
                "hourly": "wind_speed_10m,wind_speed_100m,visibility",
                "wind_speed_unit": "ms",
                "forecast_days": 4,
            },
        ),
        "seasonal": (
            SEASONAL_URL,
            {
                **location,
                "models": OUTLOOK_MODEL,
                "weekly": "wind_speed_10m_mean,wind_speed_10m_anomaly",
                "wind_speed_unit": "ms",
                "forecast_days": 45,
            },
        ),
    }


async def fetch_payloads(site: Site, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Raw provider responses; optional sources are None when they fail."""
    requests = _requests(site)
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=30)

    async def get(url: str, params: dict[str, Any]) -> Any:
        response = await http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    try:
        results = await asyncio.gather(
            *(get(url, params) for url, params in requests.values()), return_exceptions=True
        )
    finally:
        if owns_client:
            await http.aclose()
    payloads: dict[str, Any] = {}
    for name, result in zip(requests, results, strict=True):
        if not isinstance(result, BaseException):
            payloads[name] = result
        elif not isinstance(result, (httpx.HTTPError, ValueError)):
            # A programming error, not a provider problem; do not hide it.
            raise result
        elif name not in REQUIRED:
            payloads[name] = None
        elif isinstance(result, ValueError):
            raise ProviderError("Open-Meteo returned unreadable forecast data.") from result
        else:
            raise ProviderError("Open-Meteo is unavailable. Try again when online.") from result
    return payloads


async def fetch_site_forecast(
    site: Site, client: httpx.AsyncClient | None = None, waves: WaveEnsemble | None = None
) -> SiteForecast:
    payloads = await fetch_payloads(site, client)
    return build_site_forecast(site, payloads, datetime.now(UTC), waves)
