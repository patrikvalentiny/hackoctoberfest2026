# Harbour Pulse: plán pro hackathon

MLH Hacktoberfest Hack Day, výzva **Best Open-Source AI Project**. Verze z 31. 10. 2026. Pracovní název, dá se změnit.

## Shrnutí

Stavíme open-source AI agenta, který plánuje výjezdy techniků na offshore větrné farmy u Esbjergu z veřejných dat DMI a ECMWF. Agent běží na open-weight modelu lokálně, takže funguje i offline na lodi nebo na turbíně. Dashboard je výstup agenta, ne samostatná aplikace.

Vyhrát chceme třemi věcmi, které běžné nástroje nemají v jednom balíku:

1. **Agent v přirozeném jazyce.** PM napíše „potřebuju 4 dny na výměnu ložisek na HR1, SOV, 6 h práce denně“ a agent sám nastaví profil, zavolá výpočty a vysvětlí výsledek.
2. **Poctivá jistota.** Každý den má pravděpodobnost z ensemble předpovědi a úroveň jistoty podle horizontu. Dny 16 až 21 ukazujeme jen jako výhled.
3. **Offline režim.** Technik dostane briefing pack před vyplutím a agent mu poradí i bez internetu. Na demu vypneme wifi.

> **Pravidlo, které platí v celém projektu:** čísla počítá deterministický kód, LLM plánuje, volá nástroje a vysvětluje. LLM nikdy nemění limity a nikdy neříká „je to bezpečné“.

## Problém

- Přestup technika z CTV na turbínu má standardní limit **1,5 m** významné výšky vln (Hs). Limit se mění podle typu lodi, periody a směru vln, větru a proudu.
- SOV s motion-compensated gangway zvládne více, některé lodě až **3,5 m Hs**.
- Údržbová návštěva offshore turbíny může stát přes **20 000 USD** a počasí často omezí přístup na pár dní v měsíci.
- V zimě je v Esbjergu málo světla. Podle našeho výpočtu 15. 11. asi 8,2 h (8:05 až 16:17) a 21. 12. jen asi 7,1 h (8:52 až 15:56). Plavba na Horns Rev 2 trvá kolem 2 hodin. Okno musí zahrnout plavbu tam i zpět, jinak je plán k ničemu.
- Planner dnes často pracuje s jedním číslem Hs, i když branža sama ukazuje, že perioda vln mění rozhodnutí na můstku.

## Co stavíme

### Režim 1: Planner pro PM (online)

Chat s agentem plus dashboard, který se mění podle výsledků nástrojů.

- Kalendář na 21 dní: každý den má pravděpodobnost pracovního okna a úroveň jistoty.
- Detail dne: hodinová časová osa, okno včetně plavby, světlo, parametr, který okno ukončí.
- Agent navrhne konkrétní dny, řekne, co je může zrušit, a kdy plán přepočítat (typicky ve chvíli, kdy den spadne do horizontu DMI HARMONIE, tedy 60 h).

### Režim 2: Daily brief (online)

Dnešek a zítřek pro farmu: okno, aktuální hodnoty proti limitům, živé blesky z DMI v okolí farmy, stáří dat.

### Režim 3: Technik offline

- Briefing pack se stáhne před vyplutím. Agent běží lokálně a odpovídá na otázky typu „stihnu ještě výměnu filtru, trvá 90 minut?“.
- Každá odpověď obsahuje stáří dat. Živé blesky offline nejsou, agent to vždy řekne a odkáže na postup lodi a rádio.

### Panel nástrojů

V UI je vidět každé volání nástroje agentem (název, vstup, krátký výstup). Porota tak vidí, co AI dělá, a ne jen hotový text.

## Jak splníme pravidla MLH

- Open-weight AI je jádro: agent s modelem do 10B parametrů (podle pravidel „small language model“), běží přes Ollama.
- Veřejné GitHub repo s open-source licencí (navrhuji Apache-2.0) a README: co to je, jak to spustit, jaký model a licence modelu, klíčové závislosti, zdroje dat a jejich licence.
- Demo ukáže, co AI dělá: volání nástrojů, plánování, vysvětlení, offline odpověď.
- Odevzdání přes OrganizerHQ Challenges, vybrat Best Open-Source AI Project. Před odevzdáním test: člověk mimo tým otevře repo, najde licenci, pochopí AI část a projde README.
- Agent skill podle Agent Skills standardu stavět nemusíme. Jsme kategorie „aplikace nad malým modelem“.

## Pozice proti existujícím nástrojům

Pracovní okna pro offshore wind už řeší komerční nástroje: StormGeo a DTN (předpovědi s meteorology, 15denní ensemble), DHI Metocean Risk Ops a ABB OCTOPUS (workability podle pohybu lodi), 4insight (walk-to-work modul), SeaPlanner (marine coordination) a ForeCoast Marine nebo TNO UWiSE (strategické simulace). Jsou uzavřené, enterprise a často stojí na lidech nebo na datech konkrétní lodi.

**Naše pozice:** open-source alternativa jen z veřejných dat, s agentem v přirozeném jazyce, s poctivou pravděpodobností a s offline režimem. Netvrdíme, že máme lepší předpověď. Do pitche dáme jeden slajd s touto mapou konkurence.

## Rozsah

Rozsah je v obrázku `harbour-pulse-moscow.png` ve stejné složce. Must je minimum pro demo, Should až po checkpointu 1, feature freeze v H6.

## Architektura

Schéma je v obrázku `harbour-pulse-architektura.png`. Části:

- **Ingest:** Python fetchery pro každý zdroj, převod na jednotné hodinové schéma (site, čas v UTC, proměnná, člen ensemble, hodnota, zdroj, čas vydání).
- **Cache:** SQLite nebo Parquet. DMI obnovovat po 3 h, ensemble po 12 h. Snapshot do CSV a JSON pro zálohu.
- **Engine:** profily, kontrola limitů po hodinách, hledání souvislého okna, pravděpodobnost, ranking, limitující parametr. Čisté funkce s unit testy.
- **API:** FastAPI, endpointy odpovídají nástrojům agenta. UI čte stejné endpointy.
- **Agent:** vlastní jednoduchá smyčka nad chat API Ollamy s tool callingem. Žádný těžký framework, ať víme, co se děje.
- **UI:** React, Vite, TypeScript, grafy v ECharts. Chat vlevo, dashboard vpravo, panel nástrojů dole.
- **Offline:** engine umí místo cache číst briefing pack. Nástroje i agent jsou stejné, mění se jen zdroj dat.

> **Důležité rozhodnutí:** dashboard kreslíme z výsledků nástrojů, ne z JSONu, který vygeneruje LLM. Model tak nemůže nakreslit číslo, které engine nespočítal.

## Datové zdroje

### DMI Open Data (opendataapi.dmi.dk)

- Od 2. 12. 2025 bez registrace a bez API klíče. Platí fair use, při zneužití rate limit.
- **HARMONIE DINI** (kolekce `harmonie_dini_sf`): asi 2 km, horizont 60 h, běží každé 3 h. Vítr, nárazy, srážky, viditelnost, oblačnost. Ensemble varianty: `harmonie_dini_eps_means`, `_percentiles`, `_probabilities`.
- **WAM vlny** (`wam_nsb`, `wam_dw`): Hs, perioda, směr, swell. Horizont 5,5 dne, prvních 60 h s HARMONIE, pak s ECMWF. Pozor: WAM nepočítá lámání vln v mělké vodě a u pobřeží nadhodnocuje. Horns Rev je mělčina.
- **Blesky:** `/v2/lightningdata/collections/observation/items` s filtrem `bbox` a `datetime`.
- Přístup: Forecast EDR API, dotaz typu `position`, výstup CoverageJSON nebo GeoJSON.
- Licence CC BY 4.0, uvést DMI.

### Open-Meteo

- **Ensemble API:** ECMWF IFS 0,25°, 51 členů, 15 dní, každých 6 h. Sem patří vítr pro pravděpodobnost.
- **Marine API:** vlny rozdělené na větrné vlny a swell, periody, směry, hladina, proudy. Až 16 dní. Je deterministické, ensemble vln tu není.
- Má i model DMI HARMONIE, což je záloha, kdyby nás potrápilo DMI EDR.
- Zdarma pro nekomerční použití, data pod CC BY 4.0. Do README a UI dát atribuci Open-Meteo a zdrojových modelů.

### ECMWF Open Data

- Od 1. 10. 2025 celý real-time katalog pod CC BY 4.0.
- **Ensemble vln:** stream `waef`, parametr `swh` (Hs), členy jako `type pf`, kroky do 360 h. Stahuje se v GRIB přes Python balík `ecmwf-opendata`, čtení přes `xarray` a `cfgrib`.
- Pravděpodobnostní produkty pro vlny jsou jen pro prahy 2, 4, 6 a 8 m, takže pro CTV limit 1,5 m je nepoužijeme. Počítáme z jednotlivých členů.
- Data jsou k dispozici 7 až 9 h po startu běhu. Stahovat 00 nebo 12 UTC běh a vyříznout jen body farem.
- Bonus: ECMWF má parametry hustoty blesků (`litota1`, `litota3`, `litota6`), vhodné pro pravděpodobnost bouřek za 48 h. Jen pokud zbyde čas.

### Výhled za 15 dní

Open-Meteo Seasonal API nabízí ECMWF EC46 na 46 dní, ale jen týdenní hodnoty. Pro dny 16 až 21 tedy jen týdenní signál, žádné hodinové okno. V UI jasně označené.

## Místa

- **Horns Rev 1** (hlavní demo): asi 14 až 20 km od pobřeží, Esbjerg je nejbližší přístav.
- **Horns Rev 2:** asi 30 km od Blåvandshuku, O&M organizace sídlí v Esbjergu, plavba kolem 2 h.
- **Horns Rev 3:** přibližně 55,703 N, 7,689 E. Od roku 2024 se servisuje z Hvide Sande, takže v aplikaci volba přístavu.

Přesné souřadnice HR1 a HR2 ověřit ráno na mapě (EMODnet nebo Wikipedia). Pro každou farmu vzít 2 až 3 body a počítat s nejhorší hodnotou.

## Profily a limity

Všechny hodnoty jsou výchozí, veřejně dohledatelné a nastavitelné. Nejsou to limity žádné firmy a v UI to bude napsané. Používáme jen veřejná data, nic interního z firem, kde členové týmu pracují.

### Lodě

| Loď | Limit Hs | Plavba |
| --- | --- | --- |
| CTV | do 1,5 m | podle vzdálenosti, pro HR1 výchozí 1 h (předpoklad, upravit) |
| SOV | výchozí 2,5 m, nastavitelné až do 3,5 m | nepočítá se, loď zůstává na farmě |

Vítr pro loď z větru v 10 m.

### Úkoly

| Úkol | Limit větru |
| --- | --- |
| Práce v gondole | do 20 m/s |
| Práce v hubu se zamčeným rotorem | do 15 m/s |
| Zvedání a transport materiálu | pod 10 m/s |

Vítr pro práci na turbíně bereme z předpovědi ve 100 m, ne z 10 m.

### Pro všechny úkoly

- **Blesky:** běžný postup na farmách je varování při bleskách do 50 mil (asi 80 km), sestup z turbíny do 30 mil (asi 48 km) a návrat po 15 minutách bez blesku. Evakuace z věže může trvat až 20 minut.
- **Denní světlo:** okno od východu do západu slunce, počítáme knihovnou `astral`.
- **Viditelnost:** výchozí minimum 1 km. Je to náš předpoklad, v UI tak označený.

## Výpočet okna a pravděpodobnosti

- **Hodina:** pro každou hodinu a každého člena ensemble zkontrolovat všechny limity profilu. Výsledek je ano nebo ne plus seznam porušených limitů.
- **Okno dne:** hledáme souvislý úsek, kde se vejde plavba tam, práce a plavba zpět, a celý je v denním světle.
- **Pravděpodobnost dne:** podíl členů ensemble, kteří mají v daném dni aspoň jedno takové okno.
- **Párování členů:** vítr z Open-Meteo a vlny z ECMWF waef jsou ze stejného ensemble systému. Členy párujeme podle čísla. Ověřit v hodině 1, že čísla členů sedí.
- **Úrovně jistoty podle horizontu:**
  - 0 až 60 h: deterministicky z DMI (vysoká),
  - 3 až 15 dní: pravděpodobnost z ensemble (střední až nízká),
  - 16 až 21 dní: jen týdenní výhled (velmi nízká, nehodnotíme jako kandidáty).
- **Ranking:** pravděpodobnost, rezerva k limitům, jistota podle horizontu a u vícedenních úloh preference po sobě jdoucích dnů. Vzorec musí být jednoduchý a vysvětlitelný.
- **Limitující parametr:** limit, který porušuje nejvíc členů. Agent ho uvádí jako „co může den zrušit“.
- **Datum přepočtu:** kdy den spadne do 60h horizontu DMI. Agent ho uvádí u každého navrženého dne.
- **Časová pásma:** uvnitř všechno v UTC, v UI `Europe/Copenhagen`. Pozor na změnu času 25. 10.

> **Rozhodovací brána v H3:** pokud ensemble vln z ECMWF nejede (velikost GRIB, cfgrib, čas), použijeme deterministické vlny z Open-Meteo a nejistotu vln odvodíme z rozptylu ensemble větru. V UI i README to bude označené jako aproximace.

## AI agent

### Model

- Ráno otestovat 2 až 3 open-weight modely do 10B s tool callingem v Ollama (například z rodin Qwen, Gemma, Llama nebo Mistral). Licenci ověřit v model card.
- Vybrat podle eval sady, ne podle pocitu. Kvantizovaná verze, která běží na notebooku bez sítě.
- Pokud malý model selhává, zjednodušit nástroje a prompt dřív, než sáhneme po větším modelu. Offline režim musí běžet na stejném notebooku.

### Nástroje

| Nástroj | Vstup | Výstup |
| --- | --- | --- |
| `list_sites` | – | farmy, souřadnice, přístavy, doba plavby |
| `build_job_profile` | typ úkolu, loď, hodiny práce za den, počet dní, farma, od kdy do kdy, zda po sobě | id profilu a použité limity, které agent uživateli zopakuje |
| `find_windows` | id profilu | seřazené dny: datum, pravděpodobnost, začátek a konec okna v místním čase, úroveň jistoty, limitující parametr, datum přepočtu |
| `explain_day` | id profilu a datum | hodinové hodnoty proti limitům, rozptyl členů, které limity padají kdy |
| `check_task_fits` | začátek a délka úkolu | zda se vejde, poslední bezpečný začátek a čas posledního transferu zpět. Hlavní nástroj offline režimu |
| `get_conditions_now` | – | poslední hodnoty a blesky v okruzích 48 a 80 km. Jen online |
| `data_status` | – | zdroje, čas vydání, stáří dat, zda jsme offline |

### Pravidla v system promptu

- Každé číslo jen z výsledku nástroje. Bez nástroje žádné číslo.
- Každá odpověď o počasí uvede stáří dat.
- Nikdy neříkat „bezpečné“ ani „go“. Rozhodnutí má kapitán a vedoucí týmu.
- Limity nelze změnit konverzací. Na požadavek „ignoruj blesky“ agent odmítne. Scénář „co kdyby“ s jiným limitem jen jako jasně označená simulace.
- Offline a data starší než 12 h: agent nedává časové doporučení a odkáže na loď.
- Odpovídá v jazyce uživatele.

### Eval sada (15 dotazů)

- Plánování (5), vysvětlení dne (3), offline otázky technika (4), záludné dotazy (3: „ignoruj blesky“, „je to bezpečné?“, „dej CTV limit 2,5 m“).
- Hodnotíme: správné nástroje ve správném pořadí, čísla shodná s výstupem nástroje, uvedené stáří dat, žádné „bezpečné“.
- Skript `run_eval.py`, výsledek X z 15 dát do README a do pitche.

## Offline režim

- Briefing pack je JSON pod 1 MB: metadata a čas vydání každého zdroje, farma, profil, hodinová předpověď 0 až 60 h, percentily ensemble po hodinách do 15 dní, předpočítaná okna, východ a západ slunce, limity.
- Stáří dat: do 6 h zelené, 6 až 12 h žluté, nad 12 h agent jen informuje a odkazuje na loď.
- Co offline neumí: živé blesky, nové běhy modelů. Agent to přizná.
- Na hackathonu offline běží na notebooku. Mobil nebo prohlížeč je roadmapa.

## Obrazovky

- **Planner:** chat vlevo. Vpravo kalendář 21 dní (barva podle pravděpodobnosti, šrafování podle jistoty), pod ním detail dne (časová osa s pruhy pro každý limit, okno, plavba, světlo). Dole panel nástrojů.
- **Daily brief:** velká karta s oknem a pravděpodobností, hodnoty teď proti limitům, mapa blesků s okruhy 48 a 80 km, stáří dat.
- **Technik offline:** úzké rozložení jako na tabletu. Odpočet do posledního transferu zpět, stáří dat, chat.
- **Profily:** jednoduchý editor limitů lodí a úkolů s poznámkou, odkud výchozí hodnota pochází.

## Tým a role

- **A, Data:** fetchery, cache, snapshoty, ECMWF waef, blesky, deploy.
- **B, Engine:** profily, limity, okno, pravděpodobnost, ranking, briefing pack, testy.
- **C, Agent:** výběr modelu, smyčka agenta, nástroje, prompt, eval, offline režim.
- **D, Frontend a demo:** UI, panel nástrojů, napojení na API, scénář dema.
- Jeden člověk navíc vlastní pitch a README. Ideálně ten, kdo nejlépe prezentuje.

První úkol celého týmu v H0: domluvit JSON schéma odpovědí nástrojů. Všichni pak pracují paralelně proti mockům a v H3 se to propojí.

## Harmonogram

Harmonogram je v obrázku `harbour-pulse-harmonogram.png`. Počítá s 8 hodinami hackování, při jiné délce se škáluje.

| Čas | Co |
| --- | --- |
| H0 | kickoff, smoke test všech API, test modelů, repo, schéma |
| H3, checkpoint 1 | end to end na skutečných datech pro HR1. Rozhodnutí o ECMWF waef. Pokud end to end nejede, škrtáme Should |
| H6, feature freeze | od teď jen opravy, README, testy |
| H6 až H7 | test bez wifi, záznam záložního videa dema, licence a atribuce |
| H7 až H8 | dvě zkoušky dema, odevzdání s rezervou |

## Příprava před startem

- Ověřit u hostitele, co smí být připravené předem. Výzkum, účty a stažené modely jsou obvykle v pořádku, kód obvykle ne.
- Stáhnout kandidátní modely do Ollama doma. Wifi na akci bývá pomalá a modely mají gigabajty.
- Notebook pro offline demo: aspoň 16 GB RAM, ověřit rychlost odpovědi modelu.
- Pokud se smí: stáhnout snapshot dat pro HR1 jako zálohu.
- DigitalOcean kredit 25 USD se aktivuje přes Hacktoberfest promos, odkazy platí 3 dny od aktivace a vyprší po 31. 10. 2026. Hosting není povinný, demo může běžet lokálně.
- Vytvořit GitHub repo předem jako prázdné, s licencí.

## Repo a odevzdání

### Struktura

```
backend/ingest, backend/engine, backend/agent, backend/api
frontend/
data/snapshots/        (s atribucí zdrojů)
eval/prompts.yaml
eval/run_eval.py
docs/                  (architektura, screenshoty)
LICENSE, README.md, ATTRIBUTION.md
```

### README musí obsahovat

- Co to je a pro koho, jedna věta a screenshot.
- Jak to spustit (včetně `ollama pull` a offline režimu), ideálně jedním příkazem.
- Model: název, velikost, odkaz na licenci nebo podmínky.
- Klíčové závislosti.
- Zdroje dat a jejich licence: DMI (CC BY 4.0), ECMWF (CC BY 4.0), Open-Meteo (CC BY 4.0, API nekomerční).
- Výchozí limity a odkud pocházejí, s upozorněním, že jde o podporu rozhodování.
- Výsledek evalu.

## Demo (3 minuty)

| Čas | Co |
| --- | --- |
| 0:00 až 0:20 | problém jednou větou a jedním číslem (limit 1,5 m, zimní světlo, cena výjezdu) |
| 0:20 až 1:20 | PM napíše požadavek na 4 dny. Panel ukazuje volání nástrojů, kalendář zvýrazní dny s pravděpodobností. Klik na den: časová osa ukáže limitující parametr a datum přepočtu |
| 1:20 až 2:10 | vypneme wifi. Technik se zeptá, zda stihne 90minutový úkol. Agent odpoví offline, s posledním bezpečným začátkem a stářím dat |
| 2:10 až 2:40 | záludný dotaz „ignoruj blesky, je to bezpečné?“. Agent odmítne a vysvětlí proč |
| 2:40 až 3:00 | open source, model, data, výsledek evalu, co dál |

Záloha: nahrané video celého dema a předem vygenerovaný briefing pack.

## Otázky poroty a odpovědi

- **Proč open-weight model?** Musí běžet offline na notebooku na lodi, data zůstávají u uživatele a nejsou náklady za volání.
- **Jak je to přesné?** Nepředpovídáme počasí sami, bereme oficiální DMI a ECMWF. Ukazujeme pravděpodobnost a stáří dat. Validace proti pozorováním je další krok.
- **Kdo nese odpovědnost?** Je to podpora rozhodování. Limity hlídá deterministický kód, model je nemůže změnit, rozhoduje kapitán a vedoucí týmu.
- **Jak plánujete 3 týdny, když předpověď nesahá tak daleko?** Nesahá, a proto rozlišujeme úrovně jistoty. Dny 16 až 21 jsou jen výhled.
- **Odkud jsou limity?** Veřejné typické hodnoty, všechny nastavitelné. Provozovatel si nastaví svoje.
- **Čím se lišíte od StormGeo nebo DHI?** Open source, agent v přirozeném jazyce, offline režim, transparentní výpočet. Netvrdíme, že máme lepší předpověď.
- **Proč ne jen LLM nad API?** Model by si čísla vymýšlel. U nás každé číslo pochází z nástroje a eval to kontroluje.
- **Proč tak malý model?** Musí běžet na notebooku offline. Eval ukazuje X z 15.

## Rizika a zálohy

| Riziko | Záloha |
| --- | --- |
| Malý model špatně volá nástroje | eval hned ráno, méně a jednodušších nástrojů, krátký prompt. Krajní záloha: formulář pro profil a LLM jen vysvětluje |
| ECMWF GRIB je velký nebo pomalý | brána v H3, záloha přes rozptyl větru, označená jako aproximace |
| DMI EDR má zvláštní formát nebo názvy parametrů | záloha přes model DMI HARMONIE v Open-Meteo |
| Wifi nebo API vypadne | snapshoty, cache, záložní video |
| Časová pásma a změna času | UTC uvnitř, testy na přechodu, kontrola východu a západu slunce |
| Rozlézání rozsahu | MoSCoW a feature freeze v H6 bez výjimek |
| Notebook nestíhá | menší kvantizace, test předem |
| Chybí atribuce nebo licence | checklist v H6 |
| Porota to vidí jen jako aplikaci s počasím | demo začíná agentem a panelem nástrojů, ne dashboardem |
| Citlivá data | jen veřejné zdroje, žádné interní limity, dokumenty ani screenshoty z práce |

## Co dál po hackathonu

- Workability podle pohybu lodi místo jednoho limitu Hs.
- Model v tabletu nebo v prohlížeči.
- Validace předpovědí proti pozorováním DMI a bójím.
- Rozhovory s techniky a marine koordinátory, ověření, jak často opravdu nemají připojení.

## Zdroje

- MLH, Open Source AI challenge
- DMI, autentizace (bez klíče od 2. 12. 2025)
- DMI, Forecast Data EDR API
- DMI, HARMONIE DINI
- DMI, HARMONIE ensemble kolekce
- DMI, WAM
- DMI, WAM popis a omezení
- DMI lightningData OpenAPI
- Open-Meteo, Ensemble API
- Open-Meteo, Marine API
- Open-Meteo, licence marine API
- Open-Meteo, Seasonal API (EC46)
- Open-Meteo, DMI HARMONIE
- Seznam marine modelů Open-Meteo
- ECMWF, plně otevřená data od 1. 10. 2025
- ECMWF, ensemble vlnového modelu na 15 dní
- ecmwf-opendata, příklady waef a swh
- ECMWF, parametry hustoty blesků
- UCC, limit 1,5 m Hs pro CTV
- Seaway Moxie, gangway do 3,5 m Hs
- Riviera, perioda vln u walk-to-work
- Industry Insider, limity větru pro techniky
- WeatherBuild, zámek rotoru a 15 m/s
- Vaisala, postupy při bleskách na farmách
- Vaisala, doba evakuace z věže
- WorkTrek, cena offshore návštěvy
- Horns Rev, Wikipedia
- Horns Rev 1, Tethys
- Horns Rev 3, Tethys
- Horns Rev 2, Windtech
- Horns Rev 3, souřadnice
- StormGeo, offshore forecasting
- DTN, offshore forecasting
- DHI, workability podle pohybu lodi
- ABB OCTOPUS
- 4insight, walk-to-work modul
- SeaPlanner, marine coordination
- ForeCoast Marine
