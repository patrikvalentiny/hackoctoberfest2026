# Harbour Pulse: TODO

Compared [PLAN.md](PLAN.md) with the repository at 2026-10-31 (commit `078dc13`).

**[M]** / **[S]** / **[C]** priorities are estimates based on the plan (Must / Should / Could); `harbour-pulse-moscow.png` is missing. Revisit priorities when available.

## Current state

- **Backend:** FastAPI: `GET /health`, `GET /api/forecast?latitude&longitude`. Fetches deterministic 3-day Open-Meteo forecast and marine data: 10 m wind (knots), waves, swell, visibility, precipitation probability. Validates coordinates; handles UTC, `null`, and 502 errors. 2 passing unit tests.
- **Frontend:** React 19, Vite, Tailwind 4, shadcn/ui, PWA service worker, IndexedDB forecast cache, localStorage stations, online/offline status.
- **AI:** Qwen 3 0.6B via Transformers.js in a web worker; summarizes values only. No tools or Ollama.
- **Notebook:** Ollama installed (`llama3.2`, `deepseek-r1:1.5b`), 36 GB RAM; `uv` and `pnpm` work.

## Main gaps vs. plan

| Plan | Current |
| --- | --- |
| Ollama agent with tool calling, model up to 10B | Browser Qwen 0.6B, summaries only |
| Engine for limits, windows, ensemble probabilities | Raw data only |
| DMI HARMONIE/WAM, ECMWF waef, Open-Meteo ensemble, lightning | 3-day deterministic Open-Meteo only |
| 21-day calendar, 3 confidence levels | 3 days, no confidence |
| Chat + dashboard + tool panel, ECharts | Station form and forecast |
| Offline JSON briefing pack | Browser IndexedDB snapshot |
| Wind in m/s; turbine wind at 100 m | Knots; 10 m only |
| Apache-2.0, ATTRIBUTION.md, eval | No license, attribution, or eval |

At H0, decide whether to extend the current app or build a new frontend. Recommendation: extend the backend, rebuild the frontend as chat + dashboard, and reuse the PWA/IndexedDB offline layer.

## H0: Kickoff (all)

- [x] [M] Decide app approach and whether to keep the browser Qwen worker. *Extend backend, rebuild frontend; browser Qwen removed.*
- [ ] [M] Define JSON schemas and mocks for all 7 tools and the briefing pack in `docs/schema/`.
- [ ] [M] Agree on hourly ingest schema: site, UTC time, variable, ensemble member, value, source, issue time.
- [ ] [M] Smoke-test DMI EDR (`harmonie_dini_sf`, `wam_nsb`), DMI lightning, Open-Meteo ensemble/marine/seasonal, and ECMWF `waef`.
- [ ] [M] Verify HR1/HR2 coordinates (EMODnet/Wikipedia); choose 2–3 points per farm. *Not resolved: Wikipedia gives only one centre for the Horns Rev group (55.530 N, 7.906 E). Per-farm points still approximate and flagged; check EMODnet.*
- [x] [M] Add Apache-2.0 `LICENSE`.
- [ ] [M] Pre-pull candidate Ollama models (e.g. Qwen 3 4B/8B, Gemma, Llama 3.x 8B, Mistral 7B); verify tool calling and model-card license.
- [ ] [M] Ask organizers what may be prepared in advance.

## A. Data (ingest, cache)

- [ ] [M] Create `backend/src/backend/{ingest,engine,agent,api}`; move `main.py` to `api/`. *`ingest`, `engine`, `api` exist; `main.py` stays put and includes the planner router; `agent` to do.*
- [x] [M] Fetch Open-Meteo Ensemble (ECMWF IFS 0.25°, 51 members, 15 days): 10 m/100 m wind in m/s.
- [x] [M] Extend Open-Meteo Marine to 16 days: Hs, period, direction, swell. *Planner uses `ecmwf_wam` (to ~15 days at HR1). Swell from the default marine model (~8 days), display only.*
- [ ] [M] Fetch DMI HARMONIE DINI (EDR `position`, CoverageJSON), 0–60 h: wind, gusts, visibility, precipitation. Fallback: HARMONIE via Open-Meteo. *Fallback in place: `dmi_harmonie_arome_europe` via Open-Meteo (wind 10/100 m, visibility). Direct EDR still to do.*
- [ ] [S] Fetch DMI WAM (`wam_nsb` / `wam_dw`); note Horns Rev shallow-water limits.
- [x] [S] Fetch ECMWF `waef` / `swh` (ecmwf-opendata, xarray, cfgrib) at farm points; 00/12 UTC runs. *Done: background job checks every 30 min, ~1.2 GB per run, farm points cached in SQLite; prefetch with `python -m backend.ingest.ecmwf_waef`. Paired with wind by member number, control run dropped.*
- [x] [M] Fetch DMI lightning by bbox/time; 48 and 80 km radii. *Online only, via `GET /api/conditions-now`.*
- [x] [S] Fetch Open-Meteo Seasonal (EC46); weekly signal for days 16–21. *Weekly mean wind + anomaly on outlook days.*
- [x] [M] Cache in SQLite or Parquet; refresh DMI every 3 h, ensemble every 12 h; store source issue times. *SQLite in `data/cache/`: raw provider payloads (3 h TTL) and the latest waef run. Falls back to the last stored forecast with a note when a refresh fails.*
- [x] [M] Save HR1 CSV/JSON demo fallback to `data/snapshots/`. *JSON briefing pack via `python -m backend.snapshot hr1`.*
- [x] [M] Verify matching Open-Meteo wind and ECMWF wave ensemble members. *Paired by member number; runs can differ by up to 12 h because Open-Meteo does not expose its run time. Documented as approximate.*
- [ ] [C] Add ECMWF lightning density (`litota1/3/6`).
- [ ] [C] Deploy (DigitalOcean credit expires after 2026-10-31; local demo is OK).

## B. Engine

- [x] [M] Model profiles: vessels (CTV 1.5 m, SOV 2.5 m, configurable to 3.5 m, transit); tasks (nacelle 20 m/s, hub 15 m/s, lifting 10 m/s); shared (lightning, daylight, 1 km visibility). Mark each value's source and “default, configurable” status.
- [x] [M] Add farms/ports (HR1/HR2 Esbjerg, HR3 Hvide Sande) and transit times. *HR1 1 h, HR2 2 h, HR3 1.5 h (assumption). Coordinates are approximate, flagged `coordinates_verified: false`.*
- [x] [M] Check hourly limits per ensemble member: pass/fail + breached limits. Use 10 m vessel wind and 100 m turbine wind. *The plan gives no vessel wind limit value, so none is applied; 10 m wind is fetched and shown.*
- [x] [M] Calculate daylight with `astral` (Europe/Copenhagen).
- [x] [M] Find continuous windows for outbound transit + work + return transit, all in daylight.
- [x] [M] Daily probability = share of members with a viable window.
- [x] [M] Confidence: high at 0–60 h (DMI), medium/low at 3–15 days, outlook only at 16–21 days. *Split medium/low at 7 days. Outlook days have no data yet (EC46 to do).*
- [x] [M] Show limiting parameter (most member breaches) and recalculation date (entry into 60 h horizon).
- [x] [S] Rank by probability, limit margin, confidence, and consecutive days; use a simple explainable formula. *Limit margin added: probability, margin, confidence, date.*
- [x] [M] `check_task_fits`: latest start and last transfer back. *Uses DMI HARMONIE when it covers the period, else ensemble median; withholds timing over 12 h.*
- [x] [M] Keep briefing pack JSON under 1 MB: metadata, hourly 0–60 h, percentiles through day 15, precomputed windows, daylight, limits. Engine can use pack instead of cache. *Pack holds profile, limits and full hourly members, so tools run unchanged offline; ~250-350 kB. `GET /api/profiles/{id}/briefing-pack`, `POST /api/briefing-pack`, `HARBOUR_PULSE_PACK`.*
- [ ] [S] H3 fallback: estimate wave uncertainty from wind ensemble spread; label as approximate. *Not needed: waef works. Deterministic WAM is used only until the first run downloads.*
- [x] [M] Unit-test windows, probability, `null`s, DST change (Oct 25), sunrise/sunset.

## C. Agent

- [ ] [M] Evaluate 2–3 offline, quantized Ollama models up to 10B; document name, size, license in README.
- [ ] [M] Build a custom loop over Ollama chat API with tool calling (no framework).
- [ ] [M] Expose tools as FastAPI endpoints and agent tools: `list_sites`, `build_job_profile`, `find_windows`, `explain_day`, `check_task_fits`, `get_conditions_now`, `data_status`. *All 7 endpoints done, incl. `get_conditions_now`; see `backend/README.md`. Agent tool wiring to do.*
- [ ] [M] Chat endpoint returns response text and tool calls (name, input, short output) for the tool panel.
- [ ] [M] System prompt: numbers only from tools; show data age; never say “safe”/“go”; conversation cannot change limits (“what-if” must be labeled simulation); if offline or data is >12 h old, give no time recommendation; reply in user's language.
- [ ] [M] Offline agent uses the briefing pack; `get_conditions_now` reports that live lightning is unavailable.
- [ ] [M] Add `eval/prompts.yaml` (15 prompts: 5 planning, 3 explanations, 4 offline, 3 tricky) and `eval/run_eval.py` (tool choice/order, output-matched numbers, data age, no “safe”).
- [ ] [S] Add code-level guard against “safe” / “go” in responses.
- [ ] [C] Last-resort fallback: profile form; LLM only explains.

## D. Frontend and demo

- [ ] [M] Planner layout: chat left, dashboard right, tool panel below.
- [ ] [M] 21-day calendar: color by probability, hatching by confidence, days 16–21 as outlook.
- [ ] [M] Day detail (ECharts): hourly timeline, limit bars, window, transit, daylight, limiting parameter, recalculation date.
- [ ] [M] Render dashboard only from API tool results, never LLM JSON.
- [ ] [M] Show every agent tool call in the tool panel.
- [ ] [M] Offline technician view: narrow layout, countdown to last return transfer, data age (green <6 h, yellow 6–12 h, >12 h informational only), chat.
- [ ] [S] Daily brief: window/probability, current values vs. limits, 48/80 km lightning map, data age.
- [ ] [S] Profile editor with default-value sources.
- [ ] [M] Use Europe/Copenhagen; attribute DMI, ECMWF, Open-Meteo; show “decision support; captain decides”.
- [ ] [M] Rename PWA manifest from “Offshore Weather” to Harbour Pulse, if retained.
- [ ] [M] Prepare a 3-minute demo from PLAN.md and a preloaded 4-day HR1 query.

## Pitch, README, submission

- [ ] [M] Rewrite `README.md`: purpose, screenshot, one-command setup (including `ollama pull` and offline mode), model/license, dependencies, data sources/licenses, default limits/sources, eval results.
- [x] [M] Add `ATTRIBUTION.md`: DMI and ECMWF (CC BY 4.0); Open-Meteo (CC BY 4.0, non-commercial API).
- [ ] [M] Update `claude.md` and `agents.md`: replace browser-Qwen-only guidance after agent migration; retain safety rules. *Browser model removed from both; rewrite again once the Ollama agent lands.*
- [ ] [M] Add source URLs to PLAN.md.
- [ ] [M] Add MoSCoW, architecture, and timeline diagrams to `docs/`.
- [ ] [S] Add competitor map slide (StormGeo, DTN, DHI, ABB OCTOPUS, 4insight, SeaPlanner, ForeCoast, UWiSE).
- [ ] [M] Have someone outside the team find the license, understand the AI, and follow README.
- [ ] [M] Submit via OrganizerHQ Challenges, Best Open-Source AI Project.

## Checkpoints

- [ ] **H3:** Run end-to-end on real HR1 data; choose ECMWF `waef` or approximation. Drop Should items if it fails.
- [ ] **H6, feature freeze:** bug fixes, README, tests only; check licenses and attribution.
- [ ] **H6–H7:** Test offline on demo laptop (model, briefing pack, agent); record backup video and generate backup pack.
- [ ] **H7–H8:** Rehearse twice and submit early.
