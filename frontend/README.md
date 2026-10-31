# Harbour Pulse frontend

The React app is a technician-facing offshore wind maintenance PoC. It shows a selected workday,
a sample task timeline, weather factors, and a browser-local AI chat.

## Local use

Install dependencies with `pnpm install`, then run `pnpm dev`. The forecast API defaults to
`http://localhost:8000`; set `VITE_API_URL` to use another backend.

The Conditions view saves the next 72 hours of hourly forecast data in IndexedDB for offline use.
Use **Summarize locally** to load the WebLLM model into a browser worker and generate a daily
summary on-device. The first model load requires WebGPU and a one-time model download; subsequent
use can work without a connection when the browser retains the model and saved forecast data.
Forecast summaries are decision support only, not observations or go/no-go advice.

The header's demo clock uses Copenhagen local time. The workday selector covers today and the next
two dates, matching the forecast cache window. Sample activities are illustrative, not work orders;
confirm actual tasks, permits, site limits, and vessel-master instructions before operational use.
Forecast wind is measured at 10 m and is not turbine hub-height wind. The prototype does not make
go/no-go decisions or provide a live lightning forecast.

The sample plan highlights access/transfer, inspection, service, and control-check work as a
demonstration of common offshore maintenance concerns. Safety framing follows the G+ offshore wind
industry good-practice guidance and incident-data programme:
[G+ good-practice guidance](https://www.gplusoffshorewind.com/work-programme/workstreams/guidelines),
[G+ incident data](https://www.gplusoffshorewind.com/work-programme/workstreams/statistics), and
[G+ lifesaving rules](https://www.gplusoffshorewind.com/work-programme/workstreams/lifesaving-rules-published).
