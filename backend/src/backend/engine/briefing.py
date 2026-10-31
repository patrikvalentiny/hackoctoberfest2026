"""Briefing packs: everything the planner needs offline in one JSON file.

A pack holds the job profile with its limits, the full hourly forecast the
engine evaluates (so every tool works unchanged offline), precomputed windows
for reference, and source attribution. It must stay under 1 MB.
"""

import json
from datetime import datetime
from typing import Any

from backend.engine.forecast import SiteForecast, forecast_from_dict, forecast_to_dict
from backend.engine.profiles import JobProfile, profile_from_dict, profile_to_dict

FORMAT = "harbour-pulse-briefing-pack"
VERSION = 1
MAX_BYTES = 1_000_000


class BriefingPackError(Exception):
    """A briefing pack is invalid, too large, or for another format version."""


def build_pack(
    profile: JobProfile, forecast: SiteForecast, windows: dict[str, Any], created_at: datetime
) -> dict[str, Any]:
    pack = {
        "format": FORMAT,
        "version": VERSION,
        "created_at": created_at.isoformat(),
        "disclaimer": (
            "Decision support only. Forecasts age and can be wrong; live lightning is "
            "not included. The vessel master and team lead decide using site-approved "
            "limits and procedures."
        ),
        "profile": profile_to_dict(profile),
        "forecast": forecast_to_dict(forecast),
        "windows": windows,
        "attribution": sorted({source.attribution for source in forecast.sources}),
    }
    size = len(json.dumps(pack, separators=(",", ":"), default=str).encode())
    if size > MAX_BYTES:
        raise BriefingPackError(f"Briefing pack is {size} bytes; the limit is {MAX_BYTES}.")
    return pack


def load_pack(pack: Any) -> tuple[JobProfile, SiteForecast]:
    if not isinstance(pack, dict) or pack.get("format") != FORMAT:
        raise BriefingPackError("This file is not a Harbour Pulse briefing pack.")
    if pack.get("version") != VERSION:
        raise BriefingPackError(f"Unsupported briefing pack version {pack.get('version')}.")
    try:
        profile = profile_from_dict(pack["profile"])
        forecast = forecast_from_dict(pack["forecast"])
    except (KeyError, TypeError, ValueError) as error:
        raise BriefingPackError("The briefing pack is incomplete or damaged.") from error
    if forecast.site_id != profile.site.id:
        raise BriefingPackError("The briefing pack forecast is for a different site than its profile.")
    return profile, forecast
