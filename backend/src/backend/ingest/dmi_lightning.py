"""Live DMI lightning observations around a farm (online only)."""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from backend.engine.profiles import Site

URL = "https://opendataapi.dmi.dk/v2/lightningdata/collections/observation/items"
ATTRIBUTION = "Lightning observations by DMI (CC BY 4.0)"
NEAR_KM = 48.0  # about 30 miles
WIDE_KM = 80.0  # about 50 miles
PAGE_LIMIT = 1000

# Common published practice, quoted for reference only. Site procedures apply.
PROCEDURE_REFERENCE = (
    "Common practice on farms: warning for lightning within 80 km (50 mi), descend "
    "the turbine for lightning within 48 km (30 mi), return after 15 minutes "
    "without lightning. Tower evacuation can take up to 20 minutes. Follow the "
    "vessel's and site's lightning procedure."
)


class LightningError(Exception):
    """DMI lightning data was unavailable or unreadable."""


@dataclass(frozen=True)
class LightningSummary:
    observed_from: datetime
    observed_to: datetime
    strikes_within_48km: int
    strikes_within_80km: int
    nearest_km: float | None
    last_within_48km: datetime | None
    last_within_80km: datetime | None
    truncated: bool


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def bbox(site: Site, radius_km: float = WIDE_KM) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.2
    dlon = radius_km / (111.2 * math.cos(math.radians(site.latitude)))
    return (site.longitude - dlon, site.latitude - dlat, site.longitude + dlon, site.latitude + dlat)


def summarize(features: list[Any], site: Site, start: datetime, end: datetime, truncated: bool) -> LightningSummary:
    strikes: list[tuple[float, datetime]] = []
    for feature in features:
        try:
            lon, lat = feature["geometry"]["coordinates"][:2]
            observed = datetime.fromisoformat(feature["properties"]["observed"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as error:
            raise LightningError("DMI returned an unreadable lightning observation.") from error
        strikes.append((distance_km(site.latitude, site.longitude, lat, lon), observed))
    near = [time for km, time in strikes if km <= NEAR_KM]
    wide = [time for km, time in strikes if km <= WIDE_KM]
    return LightningSummary(
        observed_from=start,
        observed_to=end,
        strikes_within_48km=len(near),
        strikes_within_80km=len(wide),
        nearest_km=round(min(km for km, _ in strikes), 1) if strikes else None,
        last_within_48km=max(near, default=None),
        last_within_80km=max(wide, default=None),
        truncated=truncated,
    )


async def fetch_lightning(
    site: Site, now: datetime, minutes: int = 60, client: httpx.AsyncClient | None = None
) -> LightningSummary:
    end = now.astimezone(UTC).replace(microsecond=0)
    start = end - timedelta(minutes=minutes)
    params = {
        "bbox": ",".join(f"{value:.4f}" for value in bbox(site)),
        "datetime": f"{start:%Y-%m-%dT%H:%M:%SZ}/{end:%Y-%m-%dT%H:%M:%SZ}",
        "limit": PAGE_LIMIT,
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=20)
    try:
        response = await http.get(URL, params=params)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:
        raise LightningError("DMI lightning data is unavailable.") from error
    except ValueError as error:
        raise LightningError("DMI returned unreadable lightning data.") from error
    finally:
        if owns_client:
            await http.aclose()
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise LightningError("DMI returned unreadable lightning data.")
    return summarize(features, site, start, end, truncated=len(features) >= PAGE_LIMIT)
