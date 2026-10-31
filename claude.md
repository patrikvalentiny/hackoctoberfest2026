# Project guide

## What this project is

Offshore Weather is an offline-first PWA for viewing offshore weather and
marine forecast briefs. It combines provider data with a browser-local model
that summarizes supplied forecast values. The model does not generate
forecasts or assess operational safety.

Treat all forecasts as advisory and potentially stale. Do not describe the app
or its AI summary as a source of operational approval or safety decisions.
Users must follow approved marine forecasts, site limits, and operating
procedures.

## Stack and layout

- `backend/`: Python 3.14+, managed with `uv`; FastAPI and HTTPX.
- `frontend/`: React 19, TypeScript, Vite, Tailwind CSS 4, shadcn/ui, and
  `pnpm`.
- `frontend/src/lib/weather.ts`: API client and forecast/site types.
- `frontend/src/lib/forecast-cache.ts`: IndexedDB forecast snapshots and
  localStorage station profile.
- `frontend/src/workers/summary.worker.ts`: Transformers.js Qwen 3 0.6B
  summarization in a Web Worker; WebGPU is preferred when available, otherwise
  WASM.
- `frontend/src/App.tsx`: station entry, network state, forecast view, and
  summary UI.
- `frontend/vite.config.ts`: Vite aliases and PWA/service-worker configuration.
- `backend/src/backend/main.py`: health and forecast endpoints.
- `backend/tests/test_weather.py`: backend endpoint tests.

## Data and offline behavior

- `GET /health` returns the API health status.
- `GET /api/forecast?latitude=...&longitude=...` combines Open-Meteo weather
  and marine hourly data. Coordinates are validated by FastAPI.
- Forecast timestamps are UTC; wind speeds are knots, wave heights are metres,
  and visibility is metres. Forecast values may be `null`.
- Forecast data is saved per coordinate in IndexedDB. The selected station is
  stored in localStorage. The service worker precaches the app shell; ONNX WASM
  is cached on demand. Transformers.js uses browser caching for model assets.
- A first model run needs internet access to obtain model assets. Browser
  storage may be evicted; do not claim offline model inference has been
  verified unless it has been tested on the target browser/device.
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
- Keep provider values and AI-generated prose clearly distinguishable. The
  local model may summarize only supplied forecast values: do not make it
  invent or extrapolate weather, classify conditions as safe, or recommend
  whether operations should proceed.
- Preserve explicit units, UTC handling, nullable values, coordinate
  validation, offline cache behavior, and meaningful error states.
- Do not silently substitute mock/default forecast data when a provider or
  storage operation fails.
- Update the relevant README when commands, architecture, API contracts, or
  offline behavior change. Run the smallest relevant tests, plus frontend
  build/lint or backend tests when applicable.
- Do not claim model download, local inference, or offline behavior is verified
  without testing it on a supported browser/device.
