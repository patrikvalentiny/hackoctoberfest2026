# Agent instructions

## Product context

This repository contains Offshore Weather, an offline-first progressive web
app for offshore technicians, being extended into Harbour Pulse
(`docs/PLAN.md`, `docs/TODO.md`). The backend engine computes work windows and
ensemble probabilities; a planned local Ollama agent will call tools and
explain their results.

**Safety boundary:** forecasts can be stale or inaccurate. Any model only
explains tool results; it must not create or extrapolate forecasts, change
limits, determine whether an operation is safe, or recommend that work
proceed. Preserve the
prominent advisory language and direct users to approved forecasts, site
limits, and procedures.

## Repository map

- `backend/src/backend/main.py` — FastAPI `/health` and `/api/forecast`
  endpoints; requests weather and marine data from Open-Meteo.
- `backend/src/backend/api/planner.py` — planner endpoints that mirror agent
  tools; documented in `backend/README.md`.
- `backend/src/backend/engine/` — profiles, default limits, windows,
  probability and confidence (pure functions).
- `backend/src/backend/ingest/open_meteo.py` — ensemble, marine and DMI
  fetchers normalized into `SiteForecast`.
- `backend/tests/` — mocked provider, engine and input-validation tests.
- `backend/pyproject.toml` and `backend/uv.lock` — backend dependencies and
  Python requirement (`>=3.14`).
- `frontend/src/App.tsx` — planner layout: job form, dashboard, tool panel.
- `frontend/src/lib/planner.ts` — typed planner API client; each call is logged
  by `frontend/src/lib/tool-log.ts` for the tool panel.
- `frontend/src/components/planner/` — calendar, ECharts day detail, job form,
  tool panel. Dashboard data comes only from API results.
- `frontend/src/lib/weather.ts`, `frontend/src/lib/forecast-cache.ts` — older
  `/api/forecast` client and IndexedDB cache, unused by the planner UI.
- `frontend/src/components/ui/` — reusable shadcn/ui components.
- `frontend/vite.config.ts` — `@` alias and PWA/service-worker setup.
- `frontend/package.json` and `frontend/pnpm-lock.yaml` — frontend scripts and
  dependency versions.

## Contracts to preserve

- Backend endpoints: `GET /health` and
  `GET /api/forecast?latitude=<number>&longitude=<number>`.
- Latitude range is -90 to 90; longitude range is -180 to 180.
- Forecast responses include location, UTC `fetched_at`, source metadata, and
  hourly values. Time values are UTC ISO timestamps; wind is in knots, waves
  in metres, visibility in metres, and individual forecast measurements may be
  `null`.
- The frontend stores forecast snapshots by coordinates in IndexedDB and
  remembers the active station in localStorage. Keep offline and stale-data
  states visible and honest.
- The PWA precaches its app shell; browser storage is not guaranteed to
  persist.
- Planner endpoints: `GET /api/sites`, `POST /api/profiles`,
  `GET /api/profiles/{id}/windows`, `GET /api/profiles/{id}/days/{date}`,
  `GET /api/profiles/{id}/task-fit`, `GET /api/data-status`. Missing values
  count as limit failures; task-fit withholds timing for data over 12 h old.
- `VITE_API_URL` overrides the frontend's default API base URL
  (`http://localhost:8000`). Backend CORS currently allows local Vite origins
  `localhost:5173` and `127.0.0.1:5173`.

## Commands

Run from the repository root using PowerShell:

```powershell
# Backend
uv run --directory backend fastapi dev src/backend/main.py
uv run --directory backend python -m unittest discover -s tests

# Frontend
pnpm --dir frontend dev
pnpm --dir frontend build
pnpm --dir frontend lint
```

Start the backend and frontend dev server in separate terminals. Use the
existing lockfiles; do not add dependencies unless the change requires them.

## Working rules

- Read the existing implementation and tests before changing behavior. Prefer
  small, cohesive changes that follow project conventions.
- Preserve input validation, UTC normalization, units, nullable measurements,
  provider error visibility, and offline behavior.
- Do not introduce operational safety recommendations, risk thresholds, or
  language that presents a model summary as authoritative.
- Surface failures clearly; do not mask provider, cache, or model errors with
  success-shaped fallback data.
- Update the root or backend README when user-facing setup, API behavior, or
  offline requirements change.
- Run relevant tests and checks for changed code. For frontend changes, use
  `pnpm --dir frontend build` and `pnpm --dir frontend lint`; for backend
  changes, use the unittest command above.
- Do not state that the local model works offline until model loading and
  inference have actually been exercised on a supported browser/device.
