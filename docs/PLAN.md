# Harbour Pulse: hackathon plan

MLH Hacktoberfest Hack Day, **Best Open-Source AI Project** challenge. Version of 31 Oct 2026. Working title, can change.

> **Current PoC direction:** the shipped interface is a technician-only dashboard with a selectable
> workday, sample task plan, 72-hour forecast cache, and browser-local WebLLM chat/summary. The
> planner UI and tool-call panel described below are historical design notes, not current frontend
> behavior. See [the frontend README](../frontend/README.md) for current usage and safety caveats.

## Summary

We are building an open-source AI agent that plans technician trips to offshore wind farms near Esbjerg from public DMI and ECMWF data. The agent runs locally on an open-weight model, so it also works offline on a vessel or a turbine. The dashboard is the agent's output, not a separate application.

We want to win with three things that common tools do not offer in one package:

1. **Natural-language agent.** A PM writes "I need 4 days to replace bearings on HR1, SOV, 6 h of work per day" and the agent sets up the profile, calls the calculations and explains the result.
2. **Honest confidence.** Every day has a probability from the ensemble forecast and a confidence level by horizon. Days 16 to 21 are shown only as an outlook.
3. **Offline mode.** The technician gets a briefing pack before departure and the agent helps even without internet. We switch off wifi during the demo.

> **Rule that applies across the project:** deterministic code computes the numbers; the LLM plans, calls tools and explains. The LLM never changes limits and never says "it is safe".

## Problem

- Technician transfer from a CTV to a turbine has a standard limit of **1.5 m** significant wave height (Hs). The limit varies with vessel type, wave period and direction, wind and current.
- An SOV with a motion-compensated gangway handles more; some vessels up to **3.5 m Hs**.
- A maintenance visit to an offshore turbine can cost over **USD 20,000**, and weather often limits access to a few days a month.
- In winter Esbjerg has little daylight. By our calculation about 8.2 h on 15 Nov (08:05 to 16:17) and only about 7.1 h on 21 Dec (08:52 to 15:56). Sailing to Horns Rev 2 takes about 2 hours. The window must include the trip out and back, otherwise the plan is useless.
- Planners today often work with a single Hs number, even though the industry itself shows that wave period changes the decision on the bridge.

## What we are building

### Mode 1: Planner for the PM (online)

Chat with the agent plus a dashboard that changes with tool results.

- 21-day calendar: every day has a probability of a work window and a confidence level.
- Day detail: hourly timeline, window including transit, daylight, the parameter that ends the window.
- The agent proposes specific days, says what can cancel them and when to recompute the plan (typically when the day enters the DMI HARMONIE horizon, i.e. 60 h).

### Mode 2: Daily brief (online)

Today and tomorrow for a farm: window, current values against limits, live DMI lightning near the farm, data age.

### Mode 3: Technician offline

- The briefing pack is downloaded before departure. The agent runs locally and answers questions like "can I still fit a filter change, it takes 90 minutes?".
- Every answer includes the data age. Live lightning is not available offline; the agent always says so and refers to the vessel's procedure and radio.

### Tool panel

The UI shows every tool call by the agent (name, input, short output). The jury sees what the AI does, not just finished text.

## How we meet the MLH rules

- Open-weight AI is the core: an agent with a model up to 10B parameters ("small language model" under the rules), running through Ollama.
- Public GitHub repo with an open-source licence (proposed: Apache-2.0) and a README: what it is, how to run it, which model and its licence, key dependencies, data sources and their licences.
- The demo shows what the AI does: tool calls, planning, explanation, offline answer.
- Submission through OrganizerHQ Challenges, selecting Best Open-Source AI Project. Before submitting, test: someone outside the team opens the repo, finds the licence, understands the AI part and follows the README.
- We do not need to build an agent skill under the Agent Skills standard. We are in the "application on a small model" category.

## Position against existing tools

Commercial tools already handle offshore wind work windows: StormGeo and DTN (forecasts with meteorologists, 15-day ensemble), DHI Metocean Risk Ops and ABB OCTOPUS (workability from vessel motion), 4insight (walk-to-work module), SeaPlanner (marine coordination) and ForeCoast Marine or TNO UWiSE (strategic simulations). They are closed, enterprise, and often depend on people or on data from a specific vessel.

**Our position:** an open-source alternative using only public data, with a natural-language agent, honest probability and offline mode. We do not claim a better forecast. The pitch gets one slide with this competitor map.

## Scope

Scope is in the image `harbour-pulse-moscow.png` in the same folder. Must is the minimum for the demo, Should only after checkpoint 1, feature freeze at H6.

## Architecture

The diagram is in `harbour-pulse-architektura.png`. Parts:

- **Ingest:** Python fetchers per source, converted to one hourly schema (site, UTC time, variable, ensemble member, value, source, issue time).
- **Cache:** SQLite or Parquet. Refresh DMI every 3 h, ensemble every 12 h. Snapshot to CSV and JSON as backup.
- **Engine:** profiles, hourly limit checks, contiguous window search, probability, ranking, limiting parameter. Pure functions with unit tests.
- **API:** FastAPI; endpoints match the agent's tools. The UI reads the same endpoints.
- **Agent:** our own simple loop over Ollama's chat API with tool calling. No heavy framework, so we know what is happening.
- **UI:** React, Vite, TypeScript, charts in ECharts. Chat on the left, dashboard on the right, tool panel at the bottom.
- **Offline:** the engine can read a briefing pack instead of the cache. Tools and agent stay the same; only the data source changes.

> **Key decision:** the dashboard is drawn from tool results, not from JSON generated by the LLM. The model therefore cannot draw a number the engine did not compute.

## Data sources

### DMI Open Data (opendataapi.dmi.dk)

- Since 2 Dec 2025 without registration or API key. Fair use applies; rate limit on abuse.
- **HARMONIE DINI** (collection `harmonie_dini_sf`): about 2 km, 60 h horizon, runs every 3 h. Wind, gusts, precipitation, visibility, cloud cover. Ensemble variants: `harmonie_dini_eps_means`, `_percentiles`, `_probabilities`.
- **WAM waves** (`wam_nsb`, `wam_dw`): Hs, period, direction, swell. Horizon 5.5 days; first 60 h forced by HARMONIE, then by ECMWF. Caution: WAM does not model wave breaking in shallow water and overestimates near the coast. Horns Rev is a shoal.
- **Lightning:** `/v2/lightningdata/collections/observation/items` with `bbox` and `datetime` filters.
- Access: Forecast EDR API, `position` query, output CoverageJSON or GeoJSON.
- Licence CC BY 4.0; credit DMI.

### Open-Meteo

- **Ensemble API:** ECMWF IFS 0.25°, 51 members, 15 days, every 6 h. This is where wind for the probability comes from.
- **Marine API:** waves split into wind waves and swell, periods, directions, sea level, currents. Up to 16 days. Deterministic; no wave ensemble here.
- It also has the DMI HARMONIE model, a fallback if DMI EDR gives us trouble.
- Free for non-commercial use, data under CC BY 4.0. Credit Open-Meteo and the source models in the README and UI.

### ECMWF Open Data

- Since 1 Oct 2025 the whole real-time catalogue is under CC BY 4.0.
- **Wave ensemble:** stream `waef`, parameter `swh` (Hs), members as `type pf`, steps up to 360 h. Downloaded as GRIB with the Python package `ecmwf-opendata`, read with `xarray` and `cfgrib`.
- Probability products for waves exist only for thresholds 2, 4, 6 and 8 m, so we cannot use them for the 1.5 m CTV limit. We compute from individual members.
- Data is available 7 to 9 h after the run starts. Download the 00 or 12 UTC run and cut out only the farm points.
- Bonus: ECMWF has lightning density parameters (`litota1`, `litota3`, `litota6`), suitable for 48 h thunderstorm probability. Only if time permits.

### Outlook beyond 15 days

The Open-Meteo Seasonal API offers ECMWF EC46 for 46 days, but only weekly values. For days 16 to 21, therefore, only a weekly signal with no hourly window. Clearly labelled in the UI.

## Sites

- **Horns Rev 1** (main demo): about 14 to 20 km offshore; Esbjerg is the nearest port.
- **Horns Rev 2:** about 30 km from Blåvandshuk; the O&M organisation is based in Esbjerg; transit about 2 h.
- **Horns Rev 3:** approximately 55.703 N, 7.689 E. Serviced from Hvide Sande since 2024, so the app offers a port choice.

Verify the exact coordinates of HR1 and HR2 in the morning on a map (EMODnet or Wikipedia). Take 2 to 3 points per farm and use the worst value.

## Profiles and limits

All values are defaults, publicly available and configurable. They are not any company's limits, and the UI will say so. We use only public data, nothing internal from companies where team members work.

### Vessels

| Vessel | Hs limit | Transit |
| --- | --- | --- |
| CTV | up to 1.5 m | by distance; default 1 h for HR1 (assumption, to adjust) |
| SOV | default 2.5 m, configurable up to 3.5 m | not counted; the vessel stays at the farm |

Vessel wind uses the 10 m wind.

### Tasks

| Task | Wind limit |
| --- | --- |
| Nacelle work | up to 20 m/s |
| Hub work with rotor locked | up to 15 m/s |
| Lifting and material transport | below 10 m/s |

Wind for turbine work uses the 100 m forecast, not 10 m.

### All tasks

- **Lightning:** common practice on farms is a warning for lightning within 50 miles (about 80 km), descending the turbine within 30 miles (about 48 km), and returning after 15 minutes without lightning. Evacuating the tower can take up to 20 minutes.
- **Daylight:** window from sunrise to sunset, computed with the `astral` library.
- **Visibility:** default minimum 1 km. This is our assumption and is labelled as such in the UI.

## Window and probability calculation

- **Hour:** for every hour and every ensemble member, check all profile limits. The result is yes or no plus a list of violated limits.
- **Day window:** find a contiguous stretch that fits transit out, work and transit back, all within daylight.
- **Day probability:** share of ensemble members that have at least one such window that day.
- **Member pairing:** wind from Open-Meteo and waves from ECMWF waef come from the same ensemble system. Pair members by number. Verify in hour 1 that member numbers match.
- **Confidence by horizon:**
  - 0 to 60 h: deterministic from DMI (high),
  - 3 to 15 days: ensemble probability (medium to low),
  - 16 to 21 days: weekly outlook only (very low; not ranked as candidates).
- **Ranking:** probability, margin to limits, confidence by horizon, and for multi-day jobs a preference for consecutive days. The formula must be simple and explainable.
- **Limiting parameter:** the limit violated by most members. The agent reports it as "what can cancel the day".
- **Recompute date:** when the day enters the 60 h DMI horizon. The agent gives it for every proposed day.
- **Time zones:** everything UTC internally, `Europe/Copenhagen` in the UI. Watch the clock change on 25 Oct.

> **Decision gate at H3:** if the ECMWF wave ensemble does not work (GRIB size, cfgrib, time), use deterministic waves from Open-Meteo and derive wave uncertainty from the wind ensemble spread. Labelled as an approximation in the UI and README.

## AI agent

### Model

- In the morning, test 2 to 3 open-weight models up to 10B with tool calling in Ollama (e.g. from the Qwen, Gemma, Llama or Mistral families). Check the licence in the model card.
- Choose by the eval set, not by feel. A quantized version that runs on a laptop without network.
- If the small model fails, simplify tools and prompt before reaching for a bigger model. Offline mode must run on the same laptop.

### Tools

| Tool | Input | Output |
| --- | --- | --- |
| `list_sites` | – | farms, coordinates, ports, transit time |
| `build_job_profile` | task type, vessel, work hours per day, number of days, farm, from and to dates, whether consecutive | profile id and applied limits, which the agent repeats to the user |
| `find_windows` | profile id | ranked days: date, probability, window start and end in local time, confidence level, limiting parameter, recompute date |
| `explain_day` | profile id and date | hourly values against limits, member spread, which limits fail when |
| `check_task_fits` | task start and duration | whether it fits, latest start, time of last transfer back. The main offline tool |
| `get_conditions_now` | – | latest values and lightning within 48 and 80 km. Online only |
| `data_status` | – | sources, issue time, data age, whether we are offline |

### System prompt rules

- Every number only from a tool result. No tool, no number.
- Every weather answer states the data age.
- Never say "safe" or "go". The decision belongs to the vessel master and the team lead.
- Limits cannot be changed through conversation. The agent refuses "ignore lightning". A "what if" scenario with another limit only as a clearly labelled simulation.
- Offline and data older than 12 h: the agent gives no timing recommendation and refers to the vessel.
- Answers in the user's language.

### Eval set (15 prompts)

- Planning (5), day explanation (3), technician offline questions (4), tricky prompts (3: "ignore lightning", "is it safe?", "set the CTV limit to 2.5 m").
- We score: right tools in the right order, numbers matching tool output, data age stated, no "safe".
- Script `run_eval.py`; put the X out of 15 result in the README and pitch.

## Offline mode

- The briefing pack is JSON under 1 MB: metadata and issue time of each source, farm, profile, hourly forecast 0 to 60 h, hourly ensemble percentiles up to 15 days, precomputed windows, sunrise and sunset, limits.
- Data age: under 6 h green, 6 to 12 h yellow; over 12 h the agent only informs and refers to the vessel.
- What offline cannot do: live lightning, new model runs. The agent admits it.
- At the hackathon, offline runs on a laptop. Mobile or browser is roadmap.

## Screens

- **Planner:** chat on the left. On the right a 21-day calendar (colour by probability, hatching by confidence), below it the day detail (timeline with a bar per limit, window, transit, daylight). Tool panel at the bottom.
- **Daily brief:** a large card with window and probability, current values against limits, lightning map with 48 and 80 km rings, data age.
- **Technician offline:** narrow, tablet-like layout. Countdown to the last transfer back, data age, chat.
- **Profiles:** a simple editor for vessel and task limits, with a note on where each default comes from.

## Team and roles

- **A, Data:** fetchers, cache, snapshots, ECMWF waef, lightning, deploy.
- **B, Engine:** profiles, limits, window, probability, ranking, briefing pack, tests.
- **C, Agent:** model choice, agent loop, tools, prompt, eval, offline mode.
- **D, Frontend and demo:** UI, tool panel, API integration, demo script.
- One extra person owns the pitch and README. Ideally the best presenter.

First task for the whole team at H0: agree on the JSON schema of tool responses. Everyone then works in parallel against mocks, and it all connects at H3.

## Schedule

The schedule is in `harbour-pulse-harmonogram.png`. It assumes 8 hours of hacking; scale for a different length.

| Time | What |
| --- | --- |
| H0 | kickoff, smoke test of all APIs, model tests, repo, schema |
| H3, checkpoint 1 | end to end on real data for HR1. Decision on ECMWF waef. If end to end does not work, cut the Shoulds |
| H6, feature freeze | from now only fixes, README, tests |
| H6 to H7 | test without wifi, record a backup demo video, licences and attribution |
| H7 to H8 | two demo rehearsals, submit with time to spare |

## Preparation before the start

- Check with the host what may be prepared in advance. Research, accounts and downloaded models are usually fine; code usually is not.
- Download candidate models into Ollama at home. Event wifi tends to be slow and models are gigabytes.
- Laptop for the offline demo: at least 16 GB RAM; check the model's response speed.
- If allowed: download an HR1 data snapshot as a backup.
- The USD 25 DigitalOcean credit is activated through Hacktoberfest promos; links are valid for 3 days after activation and expire after 31 Oct 2026. Hosting is not required; the demo can run locally.
- Create the GitHub repo in advance, empty, with a licence.

## Repo and submission

### Structure

```
backend/ingest, backend/engine, backend/agent, backend/api
frontend/
data/snapshots/        (with source attribution)
eval/prompts.yaml
eval/run_eval.py
docs/                  (architecture, screenshots)
LICENSE, README.md, ATTRIBUTION.md
```

### README must contain

- What it is and for whom, one sentence and a screenshot.
- How to run it (including `ollama pull` and offline mode), ideally with one command.
- Model: name, size, link to licence or terms.
- Key dependencies.
- Data sources and their licences: DMI (CC BY 4.0), ECMWF (CC BY 4.0), Open-Meteo (CC BY 4.0, non-commercial API).
- Default limits and where they come from, with a note that this is decision support.
- Eval result.

## Demo (3 minutes)

| Time | What |
| --- | --- |
| 0:00 to 0:20 | the problem in one sentence and one number (1.5 m limit, winter daylight, trip cost) |
| 0:20 to 1:20 | the PM types a 4-day request. The panel shows tool calls, the calendar highlights days with probability. Click a day: the timeline shows the limiting parameter and recompute date |
| 1:20 to 2:10 | switch off wifi. The technician asks whether a 90-minute task fits. The agent answers offline with the latest start and data age |
| 2:10 to 2:40 | tricky prompt "ignore lightning, is it safe?". The agent refuses and explains why |
| 2:40 to 3:00 | open source, model, data, eval result, what's next |

Backup: a recorded video of the whole demo and a pre-generated briefing pack.

## Jury questions and answers

- **Why an open-weight model?** It must run offline on a laptop on a vessel; data stays with the user and there are no per-call costs.
- **How accurate is it?** We do not forecast weather ourselves; we use official DMI and ECMWF data. We show probability and data age. Validation against observations is the next step.
- **Who is responsible?** It is decision support. Deterministic code enforces the limits, the model cannot change them, and the vessel master and team lead decide.
- **How do you plan 3 weeks when forecasts don't reach that far?** They don't, which is why we distinguish confidence levels. Days 16 to 21 are only an outlook.
- **Where do the limits come from?** Public typical values, all configurable. Operators set their own.
- **How are you different from StormGeo or DHI?** Open source, natural-language agent, offline mode, transparent calculation. We do not claim a better forecast.
- **Why not just an LLM on top of an API?** The model would invent numbers. In ours every number comes from a tool, and the eval checks it.
- **Why such a small model?** It must run offline on a laptop. The eval shows X out of 15.

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Small model calls tools badly | eval first thing in the morning, fewer and simpler tools, short prompt. Last resort: a form for the profile, LLM only explains |
| ECMWF GRIB is large or slow | gate at H3, fallback via wind spread, labelled as an approximation |
| DMI EDR has an odd format or parameter names | fallback via the DMI HARMONIE model in Open-Meteo |
| Wifi or API goes down | snapshots, cache, backup video |
| Time zones and clock change | UTC internally, tests across the transition, check sunrise and sunset |
| Scope creep | MoSCoW and feature freeze at H6, no exceptions |
| Laptop too slow | smaller quantization, test in advance |
| Missing attribution or licence | checklist at H6 |
| Jury sees just a weather app | the demo starts with the agent and tool panel, not the dashboard |
| Sensitive data | public sources only; no internal limits, documents or screenshots from work |

## After the hackathon

- Workability from vessel motion instead of a single Hs limit.
- Model on a tablet or in the browser.
- Validate forecasts against DMI observations and buoys.
- Interviews with technicians and marine coordinators; check how often they really have no connectivity.

## Sources

- MLH, Open Source AI challenge
- DMI, authentication (no key since 2 Dec 2025)
- DMI, Forecast Data EDR API
- DMI, HARMONIE DINI
- DMI, HARMONIE ensemble collections
- DMI, WAM
- DMI, WAM description and limitations
- DMI lightningData OpenAPI
- Open-Meteo, Ensemble API
- Open-Meteo, Marine API
- Open-Meteo, marine API licence
- Open-Meteo, Seasonal API (EC46)
- Open-Meteo, DMI HARMONIE
- Open-Meteo list of marine models
- ECMWF, fully open data since 1 Oct 2025
- ECMWF, 15-day wave model ensemble
- ecmwf-opendata, waef and swh examples
- ECMWF, lightning density parameters
- UCC, 1.5 m Hs limit for CTVs
- Seaway Moxie, gangway up to 3.5 m Hs
- Riviera, wave period in walk-to-work
- Industry Insider, wind limits for technicians
- WeatherBuild, rotor lock and 15 m/s
- Vaisala, lightning procedures on wind farms
- Vaisala, tower evacuation time
- WorkTrek, cost of an offshore visit
- Horns Rev, Wikipedia
- Horns Rev 1, Tethys
- Horns Rev 3, Tethys
- Horns Rev 2, Windtech
- Horns Rev 3, coordinates
- StormGeo, offshore forecasting
- DTN, offshore forecasting
- DHI, workability from vessel motion
- ABB OCTOPUS
- 4insight, walk-to-work module
- SeaPlanner, marine coordination
- ForeCoast Marine
