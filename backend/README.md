# Offshore Weather API

Run from the repository root:

```powershell
uv run --directory backend fastapi dev src/backend/main.py
```

`GET /health` checks the API. `GET /api/forecast?latitude=56&longitude=2`
combines hourly wind forecasts with marine wave forecasts from Open-Meteo.
Times are UTC, winds are knots, wave heights are metres, and visibility is
metres. Forecast availability and coverage depend on the provider.