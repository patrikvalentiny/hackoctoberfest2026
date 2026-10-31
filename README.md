# Offshore Weather

An offline-first progressive web app for offshore marine forecast briefs,
being extended into Harbour Pulse, an open-source planning agent for offshore
wind technicians (see [docs/PLAN.md](docs/PLAN.md) and
[docs/TODO.md](docs/TODO.md)).

## Stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui
- **PWA and offline storage:** vite-plugin-pwa service worker, IndexedDB forecast snapshots
- **Backend:** FastAPI and HTTPX, combining Open-Meteo weather and marine forecast data
- **Planner engine:** deterministic work-window and ensemble-probability calculations for Horns Rev 1–3 (see [backend/README.md](backend/README.md))

The planner computes work windows against default public limits. It supports
planning only and never decides whether an operation is safe. Forecasts can be
stale or inaccurate; follow approved marine sources, site limits, and operating
procedures. A local Ollama agent that explains the planner results is planned
but not yet built.

## Run locally

Start the backend from the repository root:

```powershell
uv run --directory backend fastapi dev src/backend/main.py
```

In another terminal:

```powershell
pnpm --dir frontend dev
```

Open the Vite URL and enter an offshore site's name and coordinates. While
online, load a forecast to save it on this device. Browser storage can be
cleared by the device, so confirm that the forecast is cached before relying on
offline access.

Set `VITE_API_URL` in `frontend/.env.local` when the API is not at
`http://localhost:8000`.

## Verify

```powershell
uv run --directory backend python -m unittest discover -s tests
pnpm --dir frontend build
pnpm --dir frontend lint
```