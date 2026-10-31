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

These mirror the Harbour Pulse agent tools (see `docs/PLAN.md`). Planner winds
are m/s; every time is returned as `{"utc": ..., "local": ...}` with local time
in `Europe/Copenhagen`.

| Endpoint | Tool | What it returns |
| --- | --- | --- |
| `GET /api/sites` | `list_sites` | Horns Rev 1–3, ports, CTV transit hours |
| `POST /api/profiles` | `build_job_profile` | profile id and the limits applied |
| `GET /api/profiles/{id}/windows` | `find_windows` | per day: probability, confidence, window, limiting parameter, recompute time; suggested days |
| `GET /api/profiles/{id}/days/{date}` | `explain_day` | hourly ensemble spread and members failing each limit |
| `GET /api/profiles/{id}/task-fit?start=...&duration_minutes=...` | `check_task_fits` | whether the task fits, latest start, last transfer back |
| `GET /api/data-status?site_id=hr1` | `data_status` | sources, horizons, data age |

Example profile request:

```json
{"site_id": "hr1", "vessel": "sov", "task": "hub_locked_rotor",
 "work_hours_per_day": 6, "days_needed": 4, "consecutive": true}
```

Profiles and forecasts are held in memory (forecasts refresh after 3 hours),
so they are lost on restart.

### Data

- Wind: ECMWF IFS 0.25° ensemble (control + 50 members, 15 days) via the
  Open-Meteo Ensemble API, at 10 m and 100 m.
- Waves: ECMWF WAM deterministic via Open-Meteo Marine. Open-Meteo's wave
  ensembles return no values at Horns Rev, so **probabilities reflect wind
  spread only** and wave limits pass or fail for all members together.
- Visibility: DMI seamless deterministic via Open-Meteo.
- 0–60 h: DMI HARMONIE AROME deterministic, reported as `deterministic_window`
  on high-confidence days and used by `task-fit` when it covers the period.

### Engine rules

- A day's probability is the share of ensemble members with at least one
  window that fits transit out, work and transit back within daylight
  (sunrise to sunset from `astral`). Window starts are checked every 15 min
  and never before the data time.
- Vessel Hs and visibility limits apply for the whole span; the task wind
  limit (100 m wind) applies during work. Missing values count as failures.
- Confidence: `high` when sunset is within 60 h of the data, `medium` within
  7 days, `low` to the end of the ensemble, then `outlook` with no probability.
- `recompute_at` is sunset minus 60 h, when the day enters the DMI horizon.
- `task-fit` withholds timing when data is older than 12 hours.
- Lightning, wave period and direction, currents and vessel motion are not
  evaluated; every profile lists this in `not_evaluated`.

Default limits are public typical values (CTV 1.5 m Hs; SOV 2.5 m, up to
3.5 m; nacelle 20 m/s, hub with rotor locked 15 m/s, lifting 10 m/s at 100 m;
visibility 1 km, a project assumption). They support planning only; the
vessel master and team lead decide using site-approved limits.

Data: Open-Meteo (CC BY 4.0), ECMWF (CC BY 4.0), DMI (CC BY 4.0).

## Tests

```powershell
uv run --directory backend python -m unittest discover -s tests
```
