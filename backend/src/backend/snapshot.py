"""Save a briefing pack for the demo profile to data/snapshots/.

    uv run --directory backend python -m backend.snapshot [site_id]

The pack uses the cached ECMWF wave ensemble when one has been downloaded.
Load it offline with HARBOUR_PULSE_PACK=<path> or POST /api/briefing-pack.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anyio

from backend.api.planner import _waves, _windows_payload
from backend.engine.briefing import build_pack
from backend.engine.profiles import NOT_EVALUATED, SITES, JobProfile, build_limits
from backend.engine.windows import LOCAL_TZ, OUTLOOK_DAYS
from backend.ingest.open_meteo import build_site_forecast, fetch_payloads
from backend.store import DATA_DIR


async def main(site_id: str) -> None:
    site = SITES[site_id]
    today = datetime.now(LOCAL_TZ).date()
    # The demo request: 4 consecutive days of nacelle work from a CTV, 6 h a day.
    profile = JobProfile(
        id=uuid4().hex[:8],
        site=site,
        vessel="ctv",
        task="nacelle",
        work_hours_per_day=6,
        days_needed=4,
        start_date=today,
        end_date=today + timedelta(days=OUTLOOK_DAYS - 1),
        consecutive=True,
        limits=build_limits("ctv", "nacelle"),
        not_evaluated=NOT_EVALUATED,
    )
    payloads = await fetch_payloads(site)
    created = datetime.now(UTC)
    forecast = build_site_forecast(site, payloads, created, _waves(site_id))
    pack = build_pack(profile, forecast, _windows_payload(profile, forecast), created)

    path = DATA_DIR / "snapshots" / f"{site_id}-{created:%Y%m%dT%H%MZ}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(pack, separators=(",", ":"), default=str)
    path.write_text(text)
    waves = "with" if any(s.id == "wave_ensemble" for s in forecast.sources) else "without"
    print(f"Wrote {path} ({len(text.encode()) / 1000:.0f} kB, {waves} ECMWF wave ensemble).")


if __name__ == "__main__":
    anyio.run(main, sys.argv[1] if len(sys.argv) > 1 else "hr1")
