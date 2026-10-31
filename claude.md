# Project guide

## What this project is

Offshore Weather is an offline-first PWA for viewing offshore weather and
marine forecast briefs. It is being extended into Harbour Pulse, a planning
agent for offshore wind technicians (`docs/PLAN.md`, `docs/TODO.md`). A
deterministic backend engine computes work windows and probabilities; a
planned local Ollama agent will only call tools and explain their results. No
model may generate forecasts, change limits, or assess operational safety.

Treat all forecasts as advisory and potentially stale. Do not describe the app
or its AI explanations as a source of operational approval or safety decisions.
Users must follow approved marine forecasts, site limits, and operating
procedures.

## Stack and layout

- `backend/`: Python 3.14+, managed with `uv`; FastAPI and HTTPX.
- `frontend/`: React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui, and
  `pnpm`.
- `frontend/src/App.tsx`: planner layout (job form, dashboard, tool panel).
- `frontend/src/lib/planner.ts`: typed client for the planner endpoints; every
  call is recorded in `frontend/src/lib/tool-log.ts` for the tool panel.
- `frontend/src/components/planner/`: 21-day calendar, ECharts day detail,
  job form and tool panel. Dashboard data comes only from API results.
- `frontend/src/lib/weather.ts`, `forecast-cache.ts`: older `/api/forecast`
  client and IndexedDB cache, currently unused by the planner UI.
- `frontend/vite.config.ts`: Vite aliases and PWA/service-worker configuration.
- `backend/src/backend/main.py`: health and forecast endpoints; includes the
  planner router.
- `backend/src/backend/api/planner.py`: planner endpoints mirroring the agent
  tools (sites, profiles, windows, day explanation, task fit, data status).
- `backend/src/backend/engine/`: profiles and default limits, window search,
  ensemble probability, confidence tiers. Pure functions.
- `backend/src/backend/ingest/open_meteo.py`: Open-Meteo ensemble wind, ECMWF
  WAM waves, DMI visibility and HARMONIE fetchers.
- `backend/tests/`: endpoint, engine, and ingest tests.

## Data and offline behavior

- `GET /health` returns the API health status.
- `GET /api/forecast?latitude=...&longitude=...` combines Open-Meteo weather
  and marine hourly data. Coordinates are validated by FastAPI.
- Forecast timestamps are UTC; wind speeds are knots, wave heights are metres,
  and visibility is metres. Forecast values may be `null`.
- Forecast data is saved per coordinate in IndexedDB. The selected station is
  stored in localStorage. The service worker precaches the app shell. Browser
  storage may be evicted.
- Planner endpoints use m/s winds and return times as UTC plus
  Europe/Copenhagen local time. Wave heights come from one deterministic run,
  so probabilities reflect wind ensemble spread only; keep that labelled.
- Do not claim offline model inference has been verified unless it has been
  tested on the target device.
- Configure `VITE_API_URL` in `frontend/.env.local` when the API is not at
  `http://localhost:8000`. The backend currently allows local Vite origins on
  port 5173; update CORS deliberately for other deployment origins.

## Development

Run these commands from the repository root in separate PowerShell terminals:

```powershell
uv run --directory backend fastapi dev src/backend/main.py
pnpm --dir frontend dev
```

Verification:

```powershell
uv run --directory backend python -m unittest discover -s tests
pnpm --dir frontend build
pnpm --dir frontend lint
```

## Implementation guidance

- Keep changes focused and follow existing TypeScript, Python, UI component,
  and error-reporting patterns.
- Keep provider values, engine results and AI-generated prose clearly
  distinguishable. Any model may only explain tool results: do not make it
  invent or extrapolate weather, change limits, classify conditions as safe,
  or recommend whether operations should proceed.
- Preserve explicit units, UTC handling, nullable values, coordinate
  validation, offline cache behavior, and meaningful error states.
- Do not silently substitute mock/default forecast data when a provider or
  storage operation fails.
- Update the relevant README when commands, architecture, API contracts, or
  offline behavior change. Run the smallest relevant tests, plus frontend
  build/lint or backend tests when applicable.
- Do not claim model download, local inference, or offline behavior is verified
  without testing it on a supported browser/device.
