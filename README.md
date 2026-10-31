# Offshore Weather

An offline-first progressive web app for offshore marine forecast briefs.

## Stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui
- **PWA and offline storage:** vite-plugin-pwa service worker, IndexedDB forecast snapshots
- **Local summaries:** Transformers.js running Qwen 3 0.6B in a web worker, using WebGPU when available and WASM otherwise
- **Backend:** FastAPI and HTTPX, combining Open-Meteo weather and marine forecast data

The local model summarizes downloaded forecast values. It does not generate
weather predictions or decide whether an operation is safe. Forecasts can be
stale or inaccurate; follow approved marine sources, site limits, and operating
procedures.

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
online, load a forecast to save it on this device. The first local summary
downloads model files; generate one online before going offline. Browser storage
can be cleared by the device, so confirm that the forecast and model are cached
before relying on offline access.

Set `VITE_API_URL` in `frontend/.env.local` when the API is not at
`http://localhost:8000`.

## Verify

```powershell
uv run --directory backend python -m unittest discover -s tests
pnpm --dir frontend build
pnpm --dir frontend lint
```