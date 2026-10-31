# Data attribution

Harbour Pulse uses only public data. Forecasts are model output: they age, can
be wrong, and support planning only. The vessel master and team lead decide
using site-approved limits and procedures.

| Source | Used for | Licence |
| --- | --- | --- |
| [Open-Meteo](https://open-meteo.com/) Ensemble API, ECMWF IFS 0.25° | Wind ensemble (51 members, 15 days, 10 m and 100 m) | Data CC BY 4.0; free API for non-commercial use |
| [Open-Meteo](https://open-meteo.com/) Marine API, ECMWF WAM and default model | Deterministic waves and swell | Data CC BY 4.0; free API for non-commercial use |
| [Open-Meteo](https://open-meteo.com/) Forecast API, DMI HARMONIE AROME and DMI seamless | 0–60 h deterministic wind, visibility | Data CC BY 4.0; free API for non-commercial use |
| [Open-Meteo](https://open-meteo.com/) Seasonal API, ECMWF EC46 | Weekly mean-wind outlook for days 16–21 | Data CC BY 4.0; free API for non-commercial use |
| [ECMWF open data](https://www.ecmwf.int/en/forecasts/datasets/open-data), stream `waef` | Wave height ensemble (50 members, 15 days) | CC BY 4.0 |
| [DMI Open Data](https://opendatadocs.dmi.govcloud.dk/), lightning observations | Live lightning within 48 and 80 km | CC BY 4.0 |

Required credits:

- Weather data by [Open-Meteo.com](https://open-meteo.com/), CC BY 4.0.
- Contains ECMWF data, © ECMWF, CC BY 4.0.
- Contains data from the Danish Meteorological Institute (DMI), CC BY 4.0.

Snapshots in `data/snapshots/` contain data from these sources under the same
licences.
