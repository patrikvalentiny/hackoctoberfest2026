# Agent instructions

## Product context

This repository contains Offshore Weather, an offline-first progressive web
app for offshore technicians. The app displays weather and marine model
forecasts and can summarize downloaded forecast values with a small model
running locally in the browser.

**Safety boundary:** forecasts can be stale or inaccurate. The local model is
for summarization only; it must not create or extrapolate forecasts, determine
whether an operation is safe, or recommend that work proceed. Preserve the
prominent advisory language and direct users to approved forecasts, site
limits, and procedures.

## Repository map

- `backend/src/backend/main.py` — FastAPI `/health` and `/api/forecast`
  endpoints; requests weather and marine data from Open-Meteo.
- `backend/tests/test_weather.py` — mocked provider and input-validation tests.
- `backend/pyproject.toml` and `backend/uv.lock` — backend dependencies and
  Python requirement (`>=3.14`).
- `frontend/src/App.tsx` — main forecast, station, connection, and summary UI.
- `frontend/src/lib/weather.ts` — API URL, typed response model, and formatting.
- `frontend/src/lib/forecast-cache.ts` — IndexedDB forecast cache and
  localStorage station data.
- `frontend/src/workers/summary.worker.ts` — local Qwen 3 0.6B generation using
  Transformers.js, WebGPU when available, and WASM otherwise.
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
- The PWA precaches its app shell. ONNX WASM is runtime-cached on demand, and
  Transformers.js browser caching is enabled for model files. First model use
  requires connectivity; browser storage is not guaranteed to persist.
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
