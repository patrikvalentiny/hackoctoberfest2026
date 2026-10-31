# Harbour Pulse

An offline-first progressive web app for offshore marine forecast briefs,
with a local planning agent for offshore wind technicians and planners. The
deterministic engine calculates work windows; a local Qwen model uses those
tools to plan and explain them (see [docs/PLAN.md](docs/PLAN.md) and
[docs/TODO.md](docs/TODO.md)).

## Stack

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, shadcn/ui
- **PWA and offline storage:** vite-plugin-pwa service worker, IndexedDB briefing packs, local chat history
- **Local agent:** Qwen 3.5 4B through Ollama, with a FastAPI tool loop
- **Backend:** FastAPI and HTTPX, combining DMI, ECMWF, and Open-Meteo data
- **Planner engine:** deterministic work-window and ensemble-probability calculations for Horns Rev 1–3, an ECMWF wave ensemble, DMI lightning, a SQLite cache and offline briefing packs (see [backend/README.md](backend/README.md))

The planner computes work windows against default public limits. It supports
planning only and never decides whether an operation is safe. Forecasts can be
stale or inaccurate; follow approved marine sources, site limits, and operating
procedures. Chat answers use deterministic planner tools for forecast values
and timing, and are not operational authorization.

## Run locally

Start the backend from the repository root:

```powershell
uv run --directory backend fastapi dev src/backend/main.py
```

Pull and start the local model once:

```powershell
ollama pull qwen3.5:4b
ollama serve
```

In another terminal, start the frontend:

```powershell
pnpm --dir frontend dev
```

Open the Vite URL. Use chat to describe a plan, or switch to Technician and
download today's job brief while online. The app saves the briefing pack and
chat history on this device. When internet access is lost, keep the local API
and Ollama running; the app loads the saved pack into the planner and Qwen
continues answering through the same local tools. Browser storage can be
cleared by the device, so verify the offline brief before departure.

Set `VITE_API_URL` in `frontend/.env.local` when the API is not at
`http://localhost:8000`.
Set `HARBOUR_PULSE_MODEL` in the backend environment to use a different local
Ollama model. The default is `qwen3.5:4b`. The model is not downloaded by the
app; its license and redistribution terms should be checked before packaging it.

The backend downloads the ECMWF wave ensemble (about 1.2 GB per run) in the
background. Prefetch it before an event with
`uv run --directory backend python -m backend.ingest.ecmwf_waef`, or set
`HARBOUR_PULSE_WAEF=0` on slow networks. Offline mode and briefing packs are
described in [backend/README.md](backend/README.md#offline-mode). Chat is
available only while the local Ollama service and backend are running.

## Licence and data

Code is under the [Apache License 2.0](LICENSE). Forecast and lightning data
come from Open-Meteo, ECMWF and DMI under CC BY 4.0; see
[ATTRIBUTION.md](ATTRIBUTION.md).

## Verify

```powershell
uv run --directory backend python -m unittest discover -s tests
pnpm --dir frontend build
pnpm --dir frontend lint
```