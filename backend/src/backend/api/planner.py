"""Planner endpoints. Each one mirrors an agent tool so the UI and the agent
read the same engine results."""

import asyncio
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from backend.engine.forecast import SiteForecast
from backend.engine.profiles import NOT_EVALUATED, SITES, JobProfile, Site, build_limits
from backend.engine.windows import (
    LOCAL_TZ,
    OUTLOOK_DAYS,
    DayResult,
    Window,
    check_task_fits,
    explain_day,
    find_windows,
)
from backend.ingest.open_meteo import ProviderError, fetch_site_forecast

router = APIRouter(prefix="/api")

FORECAST_TTL = timedelta(hours=3)
_forecasts: dict[str, SiteForecast] = {}
_forecast_locks: dict[str, asyncio.Lock] = {}
_profiles: dict[str, JobProfile] = {}


class ProfileRequest(BaseModel):
    site_id: Literal["hr1", "hr2", "hr3"]
    vessel: Literal["ctv", "sov"]
    task: Literal["nacelle", "hub_locked_rotor", "lifting"]
    work_hours_per_day: float = Field(gt=0, le=12)
    days_needed: int = Field(default=1, ge=1, le=OUTLOOK_DAYS)
    start_date: date | None = None
    end_date: date | None = None
    consecutive: bool = False
    sov_hs_limit_m: float | None = None

    @model_validator(mode="after")
    def check_dates(self) -> "ProfileRequest":
        start = self.start_date or _today()
        end = self.end_date or start + timedelta(days=OUTLOOK_DAYS - 1)
        if end < start:
            raise ValueError("end_date must not be before start_date.")
        if (end - start).days >= OUTLOOK_DAYS:
            raise ValueError(f"The planning range is at most {OUTLOOK_DAYS} days.")
        self.start_date, self.end_date = start, end
        return self


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _time(value: datetime | None) -> dict[str, str] | None:
    if value is None:
        return None
    return {
        "utc": value.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "local": value.astimezone(LOCAL_TZ).isoformat(),
    }


def _window(window: Window | None) -> dict[str, Any] | None:
    return window and {"start": _time(window.start), "end": _time(window.end)}


def _site(site: Site) -> dict[str, Any]:
    return asdict(site)


def _profile(profile: JobProfile) -> dict[str, Any]:
    return {
        "profile_id": profile.id,
        "site": _site(profile.site),
        "vessel": profile.vessel,
        "task": profile.task,
        "work_hours_per_day": profile.work_hours_per_day,
        "transit_hours_each_way": profile.transit_hours,
        "days_needed": profile.days_needed,
        "start_date": profile.start_date,
        "end_date": profile.end_date,
        "consecutive": profile.consecutive,
        "limits": [asdict(limit) for limit in profile.limits],
        "not_evaluated": list(profile.not_evaluated),
        "disclaimer": (
            "Default public limits for decision support only. The vessel master "
            "and team lead decide; use site-approved limits and procedures."
        ),
    }


def _day(day: DayResult) -> dict[str, Any]:
    return {
        "date": day.date,
        "confidence": day.confidence,
        "probability": day.probability,
        "members": day.members,
        "members_with_window": day.members_with_window,
        "window": _window(day.window),
        "members_in_window": day.members_in_window,
        "deterministic_window": _window(day.deterministic_window),
        "deterministic_evaluated": day.deterministic_evaluated,
        "limiting_parameter": day.limiting_parameter,
        "limit_failures": day.limit_failures,
        "sunrise": _time(day.sunrise),
        "sunset": _time(day.sunset),
        "recompute_at": _time(day.recompute_at),
        "note": day.note,
    }


def _age(forecast: SiteForecast, now: datetime) -> dict[str, Any]:
    hours = (now - forecast.fetched_at).total_seconds() / 3600
    return {
        "fetched_at": _time(forecast.fetched_at),
        "age_hours": round(hours, 1),
        "freshness": "fresh" if hours < 6 else "aging" if hours <= 12 else "stale",
    }


async def _forecast(site_id: str) -> SiteForecast:
    lock = _forecast_locks.setdefault(site_id, asyncio.Lock())
    async with lock:
        cached = _forecasts.get(site_id)
        if cached and datetime.now(UTC) - cached.fetched_at < FORECAST_TTL:
            return cached
        try:
            forecast = await fetch_site_forecast(SITES[site_id])
        except ProviderError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        _forecasts[site_id] = forecast
        return forecast


def _get_profile(profile_id: str) -> JobProfile:
    profile = _profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown profile_id.")
    return profile


@router.get("/sites")
def list_sites() -> dict[str, Any]:
    return {"sites": [_site(site) for site in SITES.values()]}


@router.post("/profiles")
def build_job_profile(request: ProfileRequest) -> dict[str, Any]:
    try:
        limits = build_limits(request.vessel, request.task, request.sov_hs_limit_m)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    assert request.start_date and request.end_date
    profile = JobProfile(
        id=uuid4().hex[:8],
        site=SITES[request.site_id],
        vessel=request.vessel,
        task=request.task,
        work_hours_per_day=request.work_hours_per_day,
        days_needed=request.days_needed,
        start_date=request.start_date,
        end_date=request.end_date,
        consecutive=request.consecutive,
        limits=limits,
        not_evaluated=NOT_EVALUATED,
    )
    _profiles[profile.id] = profile
    return _profile(profile)


@router.get("/profiles/{profile_id}/windows")
async def find_profile_windows(profile_id: str) -> dict[str, Any]:
    profile = _get_profile(profile_id)
    forecast = await _forecast(profile.site.id)
    days, suggested = find_windows(profile, forecast)
    return {
        "profile_id": profile.id,
        "data": _age(forecast, datetime.now(UTC)),
        "suggested_days": suggested,
        "days": [_day(day) for day in days],
        "notes": list(forecast.notes),
    }


@router.get("/profiles/{profile_id}/days/{day}")
async def explain_profile_day(profile_id: str, day: date) -> dict[str, Any]:
    profile = _get_profile(profile_id)
    forecast = await _forecast(profile.site.id)
    result, hours = explain_day(profile, forecast, day)
    return {
        "profile_id": profile.id,
        "data": _age(forecast, datetime.now(UTC)),
        "day": _day(result),
        "limits": [asdict(limit) for limit in profile.limits],
        "hours": [{**hour, "time": _time(hour["time"])} for hour in hours],
        "notes": list(forecast.notes),
    }


@router.get("/profiles/{profile_id}/task-fit")
async def check_profile_task_fit(
    profile_id: str,
    start: datetime,
    duration_minutes: int = Query(gt=0, le=12 * 60),
) -> dict[str, Any]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=LOCAL_TZ)
    profile = _get_profile(profile_id)
    forecast = await _forecast(profile.site.id)
    fit = check_task_fits(profile, forecast, start, timedelta(minutes=duration_minutes), datetime.now(UTC))
    return {
        "profile_id": profile.id,
        "data": _age(forecast, datetime.now(UTC)),
        "start": _time(start),
        "duration_minutes": duration_minutes,
        "reference": fit.reference,
        "fits": fit.fits,
        "latest_start": _time(fit.latest_start),
        "last_transfer_back": _time(fit.last_transfer_back),
        "ensemble_fraction": fit.ensemble_fraction,
        "blocking_limits": list(fit.blocking_limits),
        "sunset": _time(fit.sunset),
        "note": fit.note,
        "not_evaluated": list(profile.not_evaluated),
    }


@router.get("/data-status")
async def data_status(site_id: Literal["hr1", "hr2", "hr3"]) -> dict[str, Any]:
    forecast = await _forecast(site_id)
    return {
        "site_id": site_id,
        "offline": False,
        "data": _age(forecast, datetime.now(UTC)),
        "sources": [
            {**asdict(source), "horizon_end": _time(source.horizon_end)} for source in forecast.sources
        ],
        "notes": list(forecast.notes),
    }
