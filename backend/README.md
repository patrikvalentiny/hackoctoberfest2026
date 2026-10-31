# Offshore Weather API

Run from the repository root:

```powershell
uv run --directory backend fastapi dev src/backend/main.py
```

`GET /health` checks the API. `GET /api/forecast?latitude=56&longitude=2`
combines hourly wind forecasts with marine wave forecasts from Open-Meteo.
Times are UTC, winds are knots, wave heights are metres, and visibility is
metres. Forecast availability and coverage depend on the provider.

## Planner endpoints

These planning APIs support the backend calculation engine; the current
technician frontend does not expose a planner UI or agent tool calls. Planner
winds are m/s; every time is returned as `{"utc": ..., "local": ...}` with local
time in `Europe/Copenhagen`. Every response includes `data` with the data age,
freshness (`fresh` < 6 h, `aging` 6–12 h, `stale` > 12 h) and offline state.

| Endpoint | Operation | What it returns |
| --- | --- | --- |
| `GET /api/sites` | `list_sites` | Horns Rev 1–3, ports, CTV transit hours |
| `POST /api/profiles` | `build_job_profile` | profile id and the limits applied |
| `GET /api/profiles/{id}/windows` | `find_windows` | per day: probability, confidence, window, limit margin, limiting parameter, recompute time, weekly outlook; suggested days |
| `GET /api/profiles/{id}/days/{date}` | `explain_day` | hourly ensemble spread and members failing each limit |
| `GET /api/profiles/{id}/task-fit?start=...&duration_minutes=...` | `check_task_fits` | whether the task fits, latest start, last transfer back |
| `GET /api/conditions-now?site_id=hr1[&profile_id=...]` | `get_conditions_now` | current-hour forecast against limits; live DMI lightning within 48 and 80 km (online only) |
| `GET /api/data-status?site_id=hr1` | `data_status` | sources, runs, horizons, data age, wave ensemble download state |
| `GET /api/profiles/{id}/briefing-pack` | – | briefing pack JSON to take offline |
| `POST /api/briefing-pack` | – | load a pack; its site switches to offline mode |
| `DELETE /api/briefing-pack/{site_id}` | – | return the site to live data |

Example profile request:

```json
{"site_id": "hr1", "vessel": "sov", "task": "hub_locked_rotor",
 "work_hours_per_day": 6, "days_needed": 4, "consecutive": true}
```

Profiles are held in memory and are lost on restart. Raw provider responses
and the wave ensemble are cached in SQLite at `data/cache/` (refreshed after
3 h). If a refresh fails, the last stored forecast is used with a note and its
real age.

### Data

- Wind: ECMWF IFS 0.25° ensemble (control + 50 members, 15 days) via the
  Open-Meteo Ensemble API, at 10 m and 100 m.
- Waves: the ECMWF open-data wave ensemble (`waef`, `swh`, 50 members to
  360 h), paired with wind members by number and interpolated from six-hourly
  to hourly. The control wind run has no wave pair and is left out. Wind and
  wave runs can differ by up to 12 h, so pairing is approximate. Until a run is
  downloaded, or when the stored run is more than 36 h older than the wind
  data, deterministic ECMWF WAM waves are shared by all members and
  probabilities reflect wind spread only; responses say which applies.
- Swell and the EC46 outlook are optional: if either fails, the forecast is
  still built and a note says what is missing.
- Swell: Open-Meteo Marine default model, display only.
- Visibility: DMI seamless deterministic via Open-Meteo.
- 0–60 h: DMI HARMONIE AROME deterministic, reported as `deterministic_window`
  on high-confidence days and used by `task-fit` when it covers the period.
- Days 16–21: ECMWF EC46 weekly mean wind and anomaly, no window or probability.
- Lightning: DMI observations, last 60 min by default.

### ECMWF wave ensemble download

A run is about 1.2 GB (only the farm points are kept, a few kB). The API
checks for a new 00 or 12 UTC run every 30 minutes and downloads it in the
background. To prefetch at home before an event, or to turn the background job
off on slow networks:

```powershell
uv run --directory backend python -m backend.ingest.ecmwf_waef
$env:HARBOUR_PULSE_WAEF = "0"; uv run --directory backend fastapi dev src/backend/main.py
```

### Offline mode

A briefing pack (< 1 MB) holds the profile, its limits and the full hourly
forecast, so planner endpoints work unchanged without a network. Download one from
`/api/profiles/{id}/briefing-pack`, or save a demo pack for HR1:

```powershell
uv run --directory backend python -m backend.snapshot hr1
```

The frontend saves the pack in IndexedDB when a brief is downloaded. When the
browser detects that it is offline, it loads the pack into the local API with
`POST /api/briefing-pack`. Keep the local API running for offline planner API
use. The pack can also be loaded manually or at startup:

```powershell
$env:HARBOUR_PULSE_PACK = "data/snapshots/<file>.json"; uv run --directory backend fastapi dev src/backend/main.py
```

Offline, `conditions-now` reports that live lightning is unavailable, and
`task-fit` withholds timing once the pack's data is older than 12 hours.

### Engine rules

- A day's probability is the share of ensemble members with at least one
  window that fits transit out, work and transit back within daylight
  (sunrise to sunset from `astral`). Window starts are checked every 15 min
  and never before the data time.
- Vessel Hs and visibility limits apply for the whole span; the task wind
  limit (100 m wind) applies during work. Missing values count as failures.
- Confidence: `high` when sunset is within 60 h of the data, `medium` within
  7 days, `low` to the end of the ensemble, then `outlook` with no probability.
- Ranking: probability, then limit margin (smallest relative distance to a
  limit in the window, ensemble median), then confidence, then date.
- `recompute_at` is sunset minus 60 h, when the day enters the DMI horizon.
- `task-fit` withholds timing when data is older than 12 hours, answers
  `fits: null` when the forecast has no data for the time, reports only
  `daylight` when the trip back cannot finish before sunset, and notes a start
  before sunrise.
- A profile's `days_needed` cannot exceed its date range (at most 21 days).
- Lightning, wave period and direction, currents and vessel motion are not
  part of the window calculation; every profile lists this in `not_evaluated`.

Default limits are public typical values (CTV 1.5 m Hs; SOV 2.5 m, up to
3.5 m; nacelle 20 m/s, hub with rotor locked 15 m/s, lifting 10 m/s at 100 m;
visibility 1 km, a project assumption). They support planning only; the
vessel master and team lead decide using site-approved limits.

Data sources and licences are listed in [ATTRIBUTION.md](../ATTRIBUTION.md).

## Tests

```powershell
uv run --directory backend python -m unittest discover -s tests
```

Tests never use the network or the real cache: providers are mocked (ECMWF
with real GRIB messages built by eccodes) and each API test gets an in-memory
SQLite store. `tests/support.py` holds the shared fixtures.
