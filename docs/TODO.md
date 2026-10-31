# Harbour Pulse: TODO

Porovnání [PLAN.md](PLAN.md) se stavem repa k 31. 10. 2026 (commit `078dc13`).

Priorita **[M]** / **[S]** / **[C]** je odhad podle plánu (Must / Should / Could), protože obrázek `harbour-pulse-moscow.png` v repu není. Po doplnění obrázku priority srovnat.

## Co v repu už je

- **Backend:** FastAPI, `GET /health` a `GET /api/forecast?latitude&longitude`. Volá deterministické Open-Meteo forecast + marine na 3 dny, vítr v 10 m v uzlech, vlny, swell, viditelnost, pravděpodobnost srážek. Validace souřadnic, UTC, `null` hodnoty, chyby 502. 2 unit testy (procházejí).
- **Frontend:** React 19 + Vite + Tailwind 4 + shadcn/ui, PWA (service worker), IndexedDB cache předpovědi, stanice v localStorage, online/offline stav.
- **AI:** Qwen 3 0.6B přes Transformers.js ve web workeru, jen shrnutí hodnot. Bez nástrojů, bez Ollamy.
- **Prostředí na tomto notebooku:** Ollama je nainstalovaná (`llama3.2`, `deepseek-r1:1.5b`), 36 GB RAM, `uv` a `pnpm` fungují.

## Hlavní rozdíly proti plánu

| Plán | Teď |
| --- | --- |
| Agent nad Ollamou s tool callingem, model do 10B | Qwen 0.6B v prohlížeči, jen shrnutí |
| Engine: limity, okna, ensemble pravděpodobnost | nic, jen surová data |
| DMI HARMONIE/WAM, ECMWF waef, Open-Meteo ensemble, blesky | jen Open-Meteo deterministicky, 3 dny |
| 21denní kalendář, 3 úrovně jistoty | 3 dny bez jistoty |
| Chat + dashboard + panel nástrojů, ECharts | formulář se stanicí a výpis předpovědi |
| Briefing pack JSON pro offline | IndexedDB snapshot v prohlížeči |
| Vítr v m/s, pro turbínu ve 100 m | uzly, jen 10 m |
| Apache-2.0, ATTRIBUTION.md, eval | chybí licence, atribuce i eval |

Rozhodnout v H0: **stavět nad stávající appkou** (rozšířit backend, PWA použít jako UI), nebo začít nový frontend podle plánu. Doporučení: backend rozšířit, frontend přestavět na chat + dashboard a stávající PWA/IndexedDB vrstvu znovu použít pro offline.

## H0: kickoff (celý tým)

- [ ] [M] Rozhodnout výše uvedenou otázku (rozšířit vs. nový frontend) a osud browserového Qwen workeru.
- [ ] [M] Domluvit JSON schéma odpovědí všech 7 nástrojů a briefing packu; uložit do `docs/schema/` + mocky.
- [ ] [M] Jednotné hodinové schéma ingestu (site, čas UTC, proměnná, člen ensemble, hodnota, zdroj, čas vydání).
- [ ] [M] Smoke test API: DMI EDR (`harmonie_dini_sf`, `wam_nsb`), DMI blesky, Open-Meteo ensemble + marine + seasonal, ECMWF `waef`.
- [ ] [M] Ověřit souřadnice HR1 a HR2 (EMODnet / Wikipedia), 2–3 body na farmu.
- [ ] [M] Přidat `LICENSE` (Apache-2.0).
- [ ] [M] Stáhnout kandidátní modely do Ollamy (nemít je až na akci): např. Qwen 3 4B/8B, Gemma, Llama 3.x 8B, Mistral 7B. Ověřit tool calling a licenci v model card.
- [ ] [M] Zjistit u pořadatele, co smí být připraveno předem.

## A, Data (ingest, cache)

- [ ] [M] Struktura `backend/src/backend/{ingest,engine,agent,api}`; přesunout stávající `main.py` do `api/`.
- [ ] [M] Fetcher Open-Meteo Ensemble (ECMWF IFS 0,25°, 51 členů, 15 dní): vítr 10 m a 100 m, m/s.
- [ ] [M] Fetcher Open-Meteo Marine na 16 dní (rozšířit stávající ze 3 dní): Hs, perioda, směr, swell.
- [ ] [M] Fetcher DMI HARMONIE DINI (EDR, `position`, CoverageJSON) na 0–60 h: vítr, nárazy, viditelnost, srážky. Záloha: HARMONIE přes Open-Meteo.
- [ ] [S] Fetcher DMI WAM (`wam_nsb` / `wam_dw`); poznamenat omezení na mělčině Horns Rev.
- [ ] [S] Fetcher ECMWF `waef` / `swh` (ecmwf-opendata + xarray + cfgrib), jen body farem, běh 00/12 UTC. **Brána v H3.**
- [ ] [M] Fetcher DMI blesků (bbox + datetime), okruhy 48 a 80 km.
- [ ] [S] Open-Meteo Seasonal (EC46), týdenní signál pro dny 16–21.
- [ ] [M] Cache (SQLite nebo Parquet), obnova DMI po 3 h, ensemble po 12 h; čas vydání u každého zdroje.
- [ ] [M] Snapshot pro HR1 do `data/snapshots/` (CSV + JSON) jako záloha dema.
- [ ] [M] Ověřit párování členů ensemble Open-Meteo vítr × ECMWF vlny.
- [ ] [C] ECMWF hustota blesků (`litota1/3/6`).
- [ ] [C] Deploy (DigitalOcean kredit vyprší po 31. 10. 2026; demo může běžet lokálně).

## B, Engine

- [ ] [M] Model profilů: lodě (CTV 1,5 m, SOV 2,5 m, nastavitelné do 3,5 m, plavba), úkoly (gondola 20 m/s, hub 15 m/s, zvedání 10 m/s), společné (blesky, světlo, viditelnost 1 km). U každé hodnoty zdroj a poznámka „výchozí, nastavitelné“.
- [ ] [M] Seznam farem a přístavů (HR1/HR2 Esbjerg, HR3 Hvide Sande), doba plavby.
- [ ] [M] Kontrola limitů po hodinách a členech: ano/ne + seznam porušených limitů. Vítr lodi z 10 m, vítr turbíny ze 100 m.
- [ ] [M] Denní světlo přes `astral` (Europe/Copenhagen).
- [ ] [M] Hledání souvislého okna: plavba tam + práce + plavba zpět, celé ve světle.
- [ ] [M] Pravděpodobnost dne = podíl členů s oknem.
- [ ] [M] Úrovně jistoty: 0–60 h vysoká (DMI), 3–15 dní střední/nízká, 16–21 dní jen výhled.
- [ ] [M] Limitující parametr (limit porušený nejvíc členy) a datum přepočtu (vstup do 60h horizontu).
- [ ] [S] Ranking: pravděpodobnost, rezerva k limitům, jistota, po sobě jdoucí dny. Jednoduchý, vysvětlitelný vzorec.
- [ ] [M] `check_task_fits`: poslední bezpečný začátek, poslední transfer zpět.
- [ ] [M] Briefing pack JSON < 1 MB (metadata, 0–60 h hodinově, percentily do 15 dní, předpočítaná okna, světlo, limity); engine umí číst pack místo cache.
- [ ] [S] Záloha pro H3: nejistota vln z rozptylu ensemble větru, označená jako aproximace.
- [ ] [M] Unit testy: okna, pravděpodobnost, `null` hodnoty, přechod času (25. 10.), východ/západ slunce.

## C, Agent

- [ ] [M] Vybrat model podle evalu (2–3 kandidáti do 10B), kvantizace běžící offline na notebooku. Do README název, velikost, licenci.
- [ ] [M] Vlastní smyčka nad Ollama chat API s tool callingem (bez frameworku).
- [ ] [M] Nástroje jako FastAPI endpointy i agent tools: `list_sites`, `build_job_profile`, `find_windows`, `explain_day`, `check_task_fits`, `get_conditions_now`, `data_status`.
- [ ] [M] Endpoint pro chat, který vrací text odpovědi + seznam volání nástrojů (název, vstup, krátký výstup) pro panel nástrojů.
- [ ] [M] System prompt: čísla jen z nástrojů, vždy stáří dat, nikdy „bezpečné“/„go“, limity nelze změnit konverzací („co kdyby“ jen jako označená simulace), offline + data > 12 h bez časového doporučení, jazyk uživatele.
- [ ] [M] Offline režim: stejný agent, zdroj dat = briefing pack; `get_conditions_now` offline vrací, že živé blesky nejsou.
- [ ] [M] Eval: `eval/prompts.yaml` (15 dotazů: 5 plánování, 3 vysvětlení, 4 offline, 3 záludné) a `eval/run_eval.py` (správné nástroje a pořadí, čísla shodná s výstupy, stáří dat, žádné „bezpečné“).
- [ ] [S] Kontrola v kódu, že odpověď neobsahuje „bezpečné“/„safe“/„go“ (pojistka nad promptem).
- [ ] [C] Krajní záloha: formulář pro profil, LLM jen vysvětluje.

## D, Frontend a demo

- [ ] [M] Layout Planner: chat vlevo, dashboard vpravo, panel nástrojů dole.
- [ ] [M] Kalendář 21 dní: barva podle pravděpodobnosti, šrafování podle jistoty, dny 16–21 jako výhled.
- [ ] [M] Detail dne (ECharts): hodinová osa, pruh pro každý limit, okno, plavba, světlo, limitující parametr, datum přepočtu.
- [ ] [M] Dashboard se kreslí z výsledků nástrojů (API), nikdy z JSONu od LLM.
- [ ] [M] Panel nástrojů s každým voláním agenta.
- [ ] [M] Technik offline: úzké rozložení, odpočet do posledního transferu, stáří dat (zelená < 6 h, žlutá 6–12 h, > 12 h jen informace), chat.
- [ ] [S] Daily brief: karta s oknem a pravděpodobností, hodnoty teď proti limitům, mapa blesků 48/80 km, stáří dat.
- [ ] [S] Editor profilů s poznámkou o původu výchozí hodnoty.
- [ ] [M] Zobrazení v Europe/Copenhagen, atribuce zdrojů (DMI, ECMWF, Open-Meteo) a upozornění „podpora rozhodování, rozhoduje kapitán“ v UI.
- [ ] [M] Přejmenovat PWA manifest z „Offshore Weather“ na Harbour Pulse (pokud zůstane název).
- [ ] [M] Scénář dema (3 min) podle PLAN.md, předem připravený dotaz na 4 dny na HR1.

## Pitch, README, odevzdání

- [ ] [M] Přepsat `README.md`: co to je, screenshot, spuštění jedním příkazem (včetně `ollama pull` a offline režimu), model a licence, závislosti, zdroje dat a licence, výchozí limity a jejich původ, výsledek evalu.
- [ ] [M] `ATTRIBUTION.md`: DMI (CC BY 4.0), ECMWF (CC BY 4.0), Open-Meteo (CC BY 4.0, API nekomerční).
- [ ] [M] Aktualizovat `claude.md` a `agents.md`: teď popisují browserový Qwen jen na shrnutí a zakazují mu cokoli dalšího; po přechodu na agenta je přepsat (bezpečnostní pravidla zachovat).
- [ ] [M] Doplnit URL ke zdrojům v PLAN.md (teď jen názvy).
- [ ] [M] Přidat obrázky MoSCoW, architektury a harmonogramu do `docs/`.
- [ ] [S] Slajd s mapou konkurence (StormGeo, DTN, DHI, ABB OCTOPUS, 4insight, SeaPlanner, ForeCoast, UWiSE).
- [ ] [M] Test „člověk mimo tým“: najde licenci, pochopí AI část, projde README.
- [ ] [M] Odevzdání přes OrganizerHQ Challenges, kategorie Best Open-Source AI Project.

## Checkpointy

- [ ] **H3:** end to end na skutečných datech pro HR1. Rozhodnout ECMWF `waef` vs. aproximace. Když end to end nejede, škrtnout Should.
- [ ] **H6, feature freeze:** jen opravy, README, testy. Checklist licencí a atribucí.
- [ ] **H6–H7:** test bez wifi na demo notebooku (model, briefing pack, agent), nahrát záložní video, vygenerovat záložní briefing pack.
- [ ] **H7–H8:** dvě zkoušky dema, odevzdat s rezervou.
