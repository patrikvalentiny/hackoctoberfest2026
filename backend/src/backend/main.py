import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Offshore Weather API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str


class ForecastHour(BaseModel):
    time: datetime
    wind_speed_kn: float | None
    wind_gusts_kn: float | None
    wind_direction_deg: float | None
    wave_height_m: float | None
    wave_period_s: float | None
    wave_direction_deg: float | None
    swell_height_m: float | None
    swell_period_s: float | None
    precipitation_probability_pct: float | None
    visibility_m: float | None


class ForecastResponse(BaseModel):
    latitude: float
    longitude: float
    fetched_at: datetime
    source: str
    source_url: str
    hours: list[ForecastHour]


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


def _series(hourly: dict[str, Any], name: str) -> dict[str, float | None]:
    times = hourly.get("time")
    values = hourly.get(name)
    if not isinstance(times, list) or not isinstance(values, list):
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned an incomplete forecast.",
        )
    if len(times) != len(values):
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned mismatched forecast data.",
        )

    return {
        str(timestamp): value if isinstance(value, (int, float)) else None
        for timestamp, value in zip(times, values, strict=True)
    }


def _hourly(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("hourly"), dict):
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned an invalid forecast.",
        )
    return payload["hourly"]


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail="Weather provider returned an invalid forecast timestamp.",
        ) from error
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@app.get("/api/forecast", response_model=ForecastResponse)
async def get_forecast(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> ForecastResponse:
    weather_params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": (
            "wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
            "precipitation_probability,visibility"
        ),
        "wind_speed_unit": "kn",
        "forecast_days": 3,
        "timezone": "GMT",
    }
    marine_params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": (
            "wave_height,wave_period,wave_direction,"
            "swell_wave_height,swell_wave_period"
        ),
        "forecast_days": 3,
        "timezone": "GMT",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            weather_response, marine_response = await asyncio.gather(
                client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params=weather_params,
                ),
                client.get(
                    "https://marine-api.open-meteo.com/v1/marine",
                    params=marine_params,
                ),
            )
        weather_response.raise_for_status()
        marine_response.raise_for_status()
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Weather providers are unavailable. Try again when online.",
        ) from error
    try:
        weather_hourly = _hourly(weather_response.json())
        marine_hourly = _hourly(marine_response.json())
    except ValueError as error:
        raise HTTPException(
            status_code=502,
            detail="Weather providers returned unreadable forecast data.",
        ) from error

    weather_fields = {
        "wind_speed_kn": "wind_speed_10m",
        "wind_gusts_kn": "wind_gusts_10m",
        "wind_direction_deg": "wind_direction_10m",
        "precipitation_probability_pct": "precipitation_probability",
        "visibility_m": "visibility",
    }
    marine_fields = {
        "wave_height_m": "wave_height",
        "wave_period_s": "wave_period",
        "wave_direction_deg": "wave_direction",
        "swell_height_m": "swell_wave_height",
        "swell_period_s": "swell_wave_period",
    }
    weather_series = {
        field: _series(weather_hourly, provider_name)
        for field, provider_name in weather_fields.items()
    }
    marine_series = {
        field: _series(marine_hourly, provider_name)
        for field, provider_name in marine_fields.items()
    }

    first_forecast_hour = datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    common_times = sorted(
        timestamp
        for timestamp in (
            set(weather_series["wind_speed_kn"])
            & set(marine_series["wave_height_m"])
        )
        if _utc_datetime(timestamp) >= first_forecast_hour
    )
    if not common_times:
        raise HTTPException(
            status_code=502,
            detail="Weather providers returned no overlapping forecast hours.",
        )

    hours = [
        ForecastHour(
            time=_utc_datetime(timestamp),
            **{
                field: values.get(timestamp)
                for field, values in {**weather_series, **marine_series}.items()
            },
        )
        for timestamp in common_times
    ]
    return ForecastResponse(
        latitude=latitude,
        longitude=longitude,
        fetched_at=datetime.now(timezone.utc),
        source="Open-Meteo weather and marine models",
        source_url="https://open-meteo.com/",
        hours=hours,
    )
