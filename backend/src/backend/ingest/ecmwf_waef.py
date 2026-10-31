"""ECMWF open-data wave ensemble (stream waef, parameter swh) at farm points.

A full run is about 1.2 GB of global GRIB (50 members x 61 six-hourly steps to
360 h). Only the swh byte ranges are downloaded, each message is decoded once,
and only the nearest valid grid value per farm is kept.

Prefetch from the repository root (for example at home, before an event):

    uv run --directory backend python -m backend.ingest.ecmwf_waef
"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from backend.engine.forecast import Series
from backend.engine.profiles import SITES, Site

BASE_URL = "https://data.ecmwf.int/forecasts"
STEPS = tuple(range(0, 361, 6))
MISSING = 9999.0
ATTRIBUTION = "ECMWF open data (CC BY 4.0)"


class WaveDataError(Exception):
    """The ECMWF wave ensemble could not be downloaded or decoded."""


@dataclass(frozen=True)
class WaveEnsemble:
    run: datetime
    # Six-hourly valid times; members[number][i] is swh in metres at times[i].
    times: list[datetime]
    members: dict[int, Series]
    grid_latitude: float
    grid_longitude: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.isoformat(),
            "times": [time.isoformat() for time in self.times],
            "members": {str(number): series for number, series in self.members.items()},
            "grid_latitude": self.grid_latitude,
            "grid_longitude": self.grid_longitude,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WaveEnsemble":
        return cls(
            run=datetime.fromisoformat(data["run"]),
            times=[datetime.fromisoformat(time) for time in data["times"]],
            members={int(number): series for number, series in data["members"].items()},
            grid_latitude=data["grid_latitude"],
            grid_longitude=data["grid_longitude"],
        )


def _url(run: datetime, step: int, extension: str) -> str:
    return (
        f"{BASE_URL}/{run:%Y%m%d}/{run:%H}z/ifs/0p25/waef/"
        f"{run:%Y%m%d%H}0000-{step}h-waef-ef.{extension}"
    )


def candidate_runs(now: datetime, count: int = 4) -> list[datetime]:
    """Most recent 00 and 12 UTC runs, newest first."""
    latest = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    latest = latest.replace(hour=12 if latest.hour >= 12 else 0)
    return [latest - timedelta(hours=12 * i) for i in range(count)]


async def latest_complete_run(client: httpx.AsyncClient, now: datetime) -> datetime | None:
    """Newest run whose final step is published (runs appear 7-9 h after start)."""
    for run in candidate_runs(now):
        response = await client.head(_url(run, STEPS[-1], "index"))
        if response.status_code == 200:
            return run
    return None


async def _swh_messages(
    client: httpx.AsyncClient, run: datetime, step: int, limit: asyncio.Semaphore
) -> list[tuple[int, bytes]]:
    async with limit:
        response = await client.get(_url(run, step, "index"))
    response.raise_for_status()
    rows = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    fields = [row for row in rows if row.get("param") == "swh" and row.get("type") == "pf"]
    if not fields:
        raise WaveDataError(f"Run {run:%Y-%m-%d %H} UTC step {step} h has no swh members.")

    async def fetch(row: dict[str, Any]) -> tuple[int, bytes]:
        start, length = int(row["_offset"]), int(row["_length"])
        for attempt in range(3):
            try:
                async with limit:
                    data = await client.get(
                        _url(run, step, "grib2"), headers={"Range": f"bytes={start}-{start + length - 1}"}
                    )
                data.raise_for_status()
                if len(data.content) != length:
                    raise WaveDataError("Truncated GRIB range.")
                return int(row["number"]), data.content
            except (httpx.HTTPError, WaveDataError):
                if attempt == 2:
                    raise
                await asyncio.sleep(1 + attempt)
        raise AssertionError("unreachable")

    return await asyncio.gather(*(fetch(row) for row in fields))


def _nearest_valid(gid: Any, site: Site) -> tuple[float | None, float, float]:
    import eccodes

    for point in sorted(
        eccodes.codes_grib_find_nearest(gid, site.latitude, site.longitude, npoints=4),
        key=lambda point: point["distance"],
    ):
        if point["value"] != MISSING:
            return float(point["value"]), point["lat"], point["lon"]
    return None, site.latitude, site.longitude


def _decode(messages: list[tuple[int, bytes]], sites: list[Site]) -> dict[str, dict[int, tuple]]:
    import eccodes

    values: dict[str, dict[int, tuple]] = {site.id: {} for site in sites}
    for number, data in messages:
        gid = eccodes.codes_new_from_message(data)
        try:
            for site in sites:
                values[site.id][number] = _nearest_valid(gid, site)
        finally:
            eccodes.codes_release(gid)
    return values


async def download_run(
    run: datetime,
    sites: list[Site],
    client: httpx.AsyncClient | None = None,
    concurrency: int = 8,
    on_step: Callable[[int, int], None] | None = None,
) -> dict[str, WaveEnsemble]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=60)
    limit = asyncio.Semaphore(concurrency)
    per_site: dict[str, dict[int, Series]] = {site.id: {} for site in sites}
    grid: dict[str, tuple[float, float]] = {}
    try:
        for done, step in enumerate(STEPS, start=1):
            messages = await _swh_messages(http, run, step, limit)
            decoded = await asyncio.to_thread(_decode, messages, sites)
            for site in sites:
                for number, (value, lat, lon) in decoded[site.id].items():
                    per_site[site.id].setdefault(number, [None] * len(STEPS))[done - 1] = value
                    if value is not None:
                        grid.setdefault(site.id, (lat, lon))
            if on_step:
                on_step(done, len(STEPS))
    except httpx.HTTPError as error:
        raise WaveDataError("ECMWF open data is unavailable. Try again when online.") from error
    finally:
        if owns_client:
            await http.aclose()

    times = [run + timedelta(hours=step) for step in STEPS]
    result = {}
    for site in sites:
        if site.id not in grid:
            raise WaveDataError(f"No valid ECMWF wave values near {site.name}.")
        result[site.id] = WaveEnsemble(
            run=run,
            times=times,
            members=dict(sorted(per_site[site.id].items())),
            grid_latitude=grid[site.id][0],
            grid_longitude=grid[site.id][1],
        )
    return result


def hourly(ensemble: WaveEnsemble, number: int, times: list[datetime]) -> Series:
    """Linear interpolation of one member's six-hourly values onto `times`."""
    series = ensemble.members.get(number, [])
    known = dict(zip(ensemble.times, series, strict=False))
    step = ensemble.times[1] - ensemble.times[0] if len(ensemble.times) > 1 else timedelta(hours=6)
    result: Series = []
    for time in times:
        if time < ensemble.times[0] or time > ensemble.times[-1]:
            result.append(None)
            continue
        offset = (time - ensemble.times[0]) % step
        before = time - offset
        after = before + step
        low, high = known.get(before), known.get(after)
        if offset == timedelta(0):
            result.append(low)
        elif low is None or high is None:
            result.append(None)
        else:
            result.append(round(low + (high - low) * (offset / step), 3))
    return result


async def _main() -> None:
    from backend.store import DEFAULT_PATH, Store

    store = Store()
    async with httpx.AsyncClient(timeout=60) as client:
        run = await latest_complete_run(client, datetime.now(UTC))
        if run is None:
            raise SystemExit("No complete ECMWF waef run is published yet.")
        print(f"Downloading ECMWF waef swh, run {run:%Y-%m-%d %H} UTC ...")
        ensembles = await download_run(
            run,
            list(SITES.values()),
            client,
            on_step=lambda done, total: print(f"  step {done}/{total}", end="\r", flush=True),
        )
    for site_id, ensemble in ensembles.items():
        store.save_waves(site_id, ensemble.run, ensemble.to_dict())
    print(f"\nSaved {len(ensembles)} sites to {DEFAULT_PATH}.")


if __name__ == "__main__":
    asyncio.run(_main())
