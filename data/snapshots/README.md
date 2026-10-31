# Snapshots

Briefing packs saved with `uv run --directory backend python -m backend.snapshot hr1`,
kept as a demo fallback when wifi or a provider is down. Load one offline with
`HARBOUR_PULSE_PACK=data/snapshots/<file>.json` or `POST /api/briefing-pack`.

Each pack records its fetch time and sources; the data ages from that moment.
Contents come from Open-Meteo, ECMWF and DMI under CC BY 4.0. See
[ATTRIBUTION.md](../../ATTRIBUTION.md).
