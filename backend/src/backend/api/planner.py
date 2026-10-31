"""Planner endpoints. Each one mirrors an agent tool so the UI and the agent
read the same engine results."""

import asyncio
import dataclasses
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Body, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from backend.engine.briefing import BriefingPackError, build_pack, load_pack
from backend.engine.forecast import SiteForecast
from backend.engine.profiles import NOT_EVALUATED, SITES, JobProfile, Site, build_limits
from backend.engine.windows import (
    LOCAL_TZ,
    OUTLOOK_DAYS,
    DayResult,
    Window,
    check_task_fits,
    current_hour,
    explain_day,
    find_windows,
)
from backend.ingest import ecmwf_waef
from backend.ingest.dmi_lightning import (
    ATTRIBUTION as LIGHTNING_ATTRIBUTION,
)
from backend.ingest.dmi_lightning import (
    PROCEDURE_REFERENCE,
    LightningError,
    fetch_lightning,
)
from backend.ingest.ecmwf_waef import WaveDataError, WaveEnsemble
from backend.ingest.open_meteo import ProviderError, build_site_forecast, fetch_payloads
from backend.store import REPO_ROOT, Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

SiteId = Literal["hr1", "hr2", "hr3"]
FORECAST_TTL = timedelta(hours=3)
WAEF_CHECK_EVERY = timedelta(minutes=30)

_forecasts: dict[str, SiteForecast] = {}
_forecast_locks: dict[str, asyncio.Lock] = {}
_profiles: dict[str, JobProfile] = {}
# Sites switched to a loaded briefing pack; no live data is fetched for them.
_offline: dict[str, SiteForecast] = {}
_store: Store | None = None
_waef_status: dict[str, Any] = {"state": "idle", "run": None, "message": None, "steps_done": 0, "steps_total": 0}


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


class ProfileRequest(BaseModel):
    site_id: SiteId
    vessel: Literal["ctv", "sov"]
    task: Literal["nacelle", "hub_locked_rotor", "lifting"]
    work_hours_per_day: float = Field(gt=0, le=12)
    days_needed: int = Field(default=1, ge=1, le=OUTLOOK_DAYS)
    start_date: date | None = None
    end_date: date | None = None
    consecutive: bool = False
    sov_hs_limit_m: float | None = None

    @model_validator(mode="after")
    def check_dates(self) -> ProfileRequest:
        start = self.start_date or _today()
        end = self.end_date or start + timedelta(days=OUTLOOK_DAYS - 1)
        if end < start:
            raise ValueError("end_date must not be before start_date.")
        if (end - start).days >= OUTLOOK_DAYS:
            raise ValueError(f"The planning range is at most {OUTLOOK_DAYS} days.")
        if self.days_needed > (end - start).days + 1:
            raise ValueError("days_needed is longer than the planning range.")
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
        "margin": day.margin,
        "deterministic_window": _window(day.deterministic_window),
        "deterministic_evaluated": day.deterministic_evaluated,
        "limiting_parameter": day.limiting_parameter,
        "limit_failures": day.limit_failures,
        "sunrise": _time(day.sunrise),
        "sunset": _time(day.sunset),
        "recompute_at": _time(day.recompute_at),
        "weekly_outlook": day.weekly_outlook and asdict(day.weekly_outlook),
        "note": day.note,
    }


def _age(forecast: SiteForecast, now: datetime) -> dict[str, Any]:
    hours = (now - forecast.fetched_at).total_seconds() / 3600
    wave_run = next((source.run for source in forecast.sources if source.id == "wave_ensemble"), None)
    return {
        "fetched_at": _time(forecast.fetched_at),
        "age_hours": round(hours, 1),
        "freshness": "fresh" if hours < 6 else "aging" if hours <= 12 else "stale",
        "offline": forecast.site_id in _offline,
        "wave_ensemble_run": _time(wave_run),
    }


def _waves(site_id: str) -> WaveEnsemble | None:
    data = store().latest_waves(site_id)
    return WaveEnsemble.from_dict(data) if data else None


async def _forecast(site_id: str) -> SiteForecast:
    """Briefing pack when offline, else a cached or freshly fetched forecast.

    When a live fetch fails, the last stored forecast is returned with a note;
    its age is reported in every response.
    """
    if site_id in _offline:
        return _offline[site_id]
    lock = _forecast_locks.setdefault(site_id, asyncio.Lock())
    async with lock:
        now = datetime.now(UTC)
        cached = _forecasts.get(site_id)
        if cached and now - cached.fetched_at < FORECAST_TTL:
            return cached
        site = SITES[site_id]
        waves = _waves(site_id)
        stored = store().latest_payloads(site_id)
        stored_forecast = None
        if stored:
            try:
                stored_forecast = build_site_forecast(site, stored[1], stored[0], waves)
            except ProviderError:
                logger.warning("Ignoring unreadable stored forecast for %s.", site_id)
        if stored_forecast and now - stored_forecast.fetched_at < FORECAST_TTL:
            forecast = stored_forecast
        else:
            try:
                payloads = await fetch_payloads(site)
                fetched_at = datetime.now(UTC)
                # Build before saving, so unusable payloads never reach the cache.
                forecast = build_site_forecast(site, payloads, fetched_at, waves)
                store().save_payloads(site_id, fetched_at, payloads)
            except ProviderError as error:
                if stored_forecast is None:
                    raise HTTPException(status_code=502, detail=str(error)) from error
                forecast = dataclasses.replace(
                    stored_forecast,
                    notes=(
                        f"Live refresh failed ({error}); showing the last stored forecast.",
                        *stored_forecast.notes,
                    ),
                )
        _forecasts[site_id] = forecast
        return forecast


def _get_profile(profile_id: str) -> JobProfile:
    profile = _profiles.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Unknown profile_id.")
    return profile


def _windows_payload(profile: JobProfile, forecast: SiteForecast) -> dict[str, Any]:
    days, suggested = find_windows(profile, forecast)
    return {
        "profile_id": profile.id,
        "data": _age(forecast, datetime.now(UTC)),
        "suggested_days": suggested,
        "days": [_day(day) for day in days],
        "notes": list(forecast.notes),
    }


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
    return _windows_payload(profile, await _forecast(profile.site.id))


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


@router.get("/conditions-now")
async def get_conditions_now(
    site_id: SiteId, profile_id: str | None = None, lightning_minutes: int = Query(default=60, ge=15, le=180)
) -> dict[str, Any]:
    profile = _get_profile(profile_id) if profile_id else None
    if profile and profile.site.id != site_id:
        raise HTTPException(status_code=422, detail="profile_id belongs to another site.")
    forecast = await _forecast(site_id)
    now = datetime.now(UTC)
    limits = profile.limits if profile else build_limits("ctv", "nacelle")
    hour = current_hour(limits, forecast, now)
    lightning: dict[str, Any] = {"available": False, "attribution": LIGHTNING_ATTRIBUTION}
    if site_id in _offline:
        lightning["note"] = (
            "Offline: live lightning is not available. Use the vessel's lightning procedure and radio."
        )
    else:
        try:
            summary = await fetch_lightning(SITES[site_id], now, minutes=lightning_minutes)
            lightning = {
                "available": True,
                **{key: _time(value) if isinstance(value, datetime) else value for key, value in asdict(summary).items()},
                "attribution": LIGHTNING_ATTRIBUTION,
            }
        except LightningError as error:
            lightning["note"] = f"{error} Use the vessel's lightning procedure and radio."
    return {
        "site_id": site_id,
        "profile_id": profile.id if profile else None,
        "limits_from": "profile" if profile else "default CTV nacelle profile",
        "data": _age(forecast, now),
        "forecast_now": hour and {**hour, "time": _time(hour["time"])},
        "forecast_note": "Forecast values for the current hour, not observations.",
        "lightning": lightning,
        "lightning_procedure_reference": PROCEDURE_REFERENCE,
    }


@router.get("/data-status")
async def data_status(site_id: SiteId) -> dict[str, Any]:
    forecast = await _forecast(site_id)
    return {
        "site_id": site_id,
        "offline": site_id in _offline,
        "live_lightning": site_id not in _offline,
        "data": _age(forecast, datetime.now(UTC)),
        "sources": [
            {**asdict(source), "horizon_end": _time(source.horizon_end), "run": _time(source.run)}
            for source in forecast.sources
        ],
        "wave_ensemble_download": dict(_waef_status),
        "notes": list(forecast.notes),
    }


@router.get("/profiles/{profile_id}/briefing-pack")
async def download_briefing_pack(profile_id: str) -> JSONResponse:
    profile = _get_profile(profile_id)
    forecast = await _forecast(profile.site.id)
    created = datetime.now(UTC)
    try:
        pack = build_pack(profile, forecast, _windows_payload(profile, forecast), created)
    except BriefingPackError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    filename = f"harbour-pulse-{profile.site.id}-{created:%Y%m%dT%H%MZ}.json"
    return JSONResponse(
        json.loads(json.dumps(pack, default=str)),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def activate_pack(pack: Any) -> JobProfile:
    profile, forecast = load_pack(pack)
    _profiles[profile.id] = profile
    _offline[profile.site.id] = forecast
    return profile


@router.post("/briefing-pack")
def load_briefing_pack(pack: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    """Switch the pack's site to offline mode using the pack's forecast."""
    try:
        profile = activate_pack(pack)
    except BriefingPackError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "profile": _profile(profile),
        "data": _age(_offline[profile.site.id], datetime.now(UTC)),
        "note": "Offline mode: tools now use the briefing pack. Live lightning is not available.",
    }


@router.delete("/briefing-pack/{site_id}")
def unload_briefing_pack(site_id: SiteId) -> dict[str, Any]:
    if _offline.pop(site_id, None) is None:
        raise HTTPException(status_code=404, detail="No briefing pack is loaded for this site.")
    return {"site_id": site_id, "offline": False}


async def refresh_wave_ensemble() -> None:
    """Download the newest complete waef run unless it is already stored."""
    async with httpx.AsyncClient(timeout=60) as client:
        run = await ecmwf_waef.latest_complete_run(client, datetime.now(UTC))
        if run is None:
            _waef_status.update(state="waiting", message="No complete ECMWF waef run published yet.")
            return
        stored = [_waves(site_id) for site_id in SITES]
        if all(waves and waves.run >= run for waves in stored):
            _waef_status.update(state="ready", run=run.isoformat(), message=None)
            return

        def progress(done: int, total: int) -> None:
            _waef_status.update(steps_done=done, steps_total=total)

        _waef_status.update(state="downloading", run=run.isoformat(), message=None, steps_done=0)
        ensembles = await ecmwf_waef.download_run(run, list(SITES.values()), client, on_step=progress)
    for site_id, ensemble in ensembles.items():
        store().save_waves(site_id, ensemble.run, ensemble.to_dict())
    # Rebuild forecasts with the new waves on next request.
    _forecasts.clear()
    _waef_status.update(state="ready", message=None)


async def _wave_ensemble_loop() -> None:
    while True:
        try:
            await refresh_wave_ensemble()
        except (WaveDataError, httpx.HTTPError) as error:
            _waef_status.update(state="error", message=str(error))
            logger.warning("ECMWF wave ensemble refresh failed: %s", error)
        except Exception as error:
            # Keep the loop alive; report the unexpected failure.
            _waef_status.update(state="error", message=f"Unexpected error: {error}")
            logger.exception("ECMWF wave ensemble refresh failed unexpectedly.")
        await asyncio.sleep(WAEF_CHECK_EVERY.total_seconds())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    pack_path = os.environ.get("HARBOUR_PULSE_PACK")
    if pack_path:
        path = Path(pack_path)
        # `uv run --directory backend` changes the working directory, so
        # relative paths may also be meant from the repository root.
        if not path.is_absolute() and not path.exists():
            path = REPO_ROOT / path
        profile = activate_pack(json.loads(path.read_text()))
        logger.info("Loaded briefing pack for %s (profile %s); offline mode.", profile.site.id, profile.id)
    task = None
    if os.environ.get("HARBOUR_PULSE_WAEF", "1") != "0":
        task = asyncio.create_task(_wave_ensemble_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
