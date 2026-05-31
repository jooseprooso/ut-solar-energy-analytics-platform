# VRM pipeline

Käesolev dokument kirjeldab kogu VRM andmevoogu — API-st kuni analüütikamartin välja —
ning selgitab kõiki olulisi disainiotsuseid.

---

## Ülevaade

```
Victron VRM API
      │
      ├─ /diagnostics (reaalaeg, kord tunnis)     ├─ /stats (backfill, käsitsi)
      ▼                                            ▼
bronze.vrm_raw                              bronze.vrm_stats_raw
      │                                            │
      ▼                                            ▼
stg_vrm_energy_snapshot (silver)        stg_vrm_stats_snapshot (silver)
      │                                            │
      └──────────────┬─────────────────────────────┘
                     ▼  UNION + deduplikatsioon (diagnostics võidab)
          gold.fct_vrm_energy_hourly
                     │
                     ▼  LEFT JOIN meteo
          gold.mart_solar_performance_hourly
```

---

## ELT põhimõte

| Etapp | Vastutav komponent |
|-------|-------------------|
| **Extract** — andmed tuuakse VRM API-st | `vrm_ingest.py` / `vrm_backfill.py` |
| **Load** — toored andmed kirjutatakse bronzesse muutmata kujul | Python + Supabase |
| **Transform** — andmed puhastatakse ja rikastatatakse andmelaos | dbt mudelid (silver, gold) |

Bronze kiht salvestab kogu API vastuse ühe JSONB veeruna — ühtegi välja ei filtreerrita ega
teisendatagi enne bronzesse kirjutamist. See tagab, et originaalandmestik on alati taaskasutatav.

---

## VRM API

[Victron VRM](https://vrm.victronenergy.com/) on Victron Energy pilveplatvorm, mis kogub
andmeid off-grid ja hübriidsüsteemidelt.

**Autentimine kõigil päringutes:** `x-authorization: Token <VRM_API_TOKEN>`

### Kasutatavad lõpp-punktid

| Lõpp-punkt | Kasutus | Struktuur |
|---|---|---|
| `GET /installations/{id}/diagnostics` | Reaalajas ingest, kord tunnis | `{"records": [{code, rawValue, ...}, ...]}` — 343 kirjet |
| `GET /installations/{id}/stats` | Ajaloolise backfill-i päringud | `{"bs": 90.0, "total_solar_yield": 0.45, ...}` — lame dict |

**`/diagnostics`** on hetkeseisundi lõpp-punkt: üks päring = ühe hetke 343 mõõtmist.

**`/stats`** on vahemiku lõpp-punkt: üks päring = kuni 30 päeva tunniandmeid korraga,
kuid tagastab ainult piiratud kogumi mõõdikuid (vt jaotist [Backfill](#backfill)).

Kaalutud, kuid kasutusele võtmata lõpp-punktid:

| Lõpp-punkt | Miks ei kasutata |
|---|---|
| `GET /installations/{id}/system-overview` | Ainult seadmete inventar, mitte mõõtmised |
| `GET /users/{id}/installations` | Paigaldis on fikseeritud (`VRM_SITE_ID`) |

---

## Bronze

Kaks eraldiseisvat tabelit — üks iga andmeallika jaoks. Payload struktuurid on
fundamentaalselt erinevad, seega eraldi tabelid on selgem kui ühine tabel `endpoint` veeruga.

### `bronze.vrm_raw` — reaalajas ingest

```sql
CREATE TABLE bronze.vrm_raw (
    id           BIGSERIAL    PRIMARY KEY,
    site_id      TEXT         NOT NULL,
    fetched_at   TIMESTAMPTZ  NOT NULL,
    fetched_hour TIMESTAMPTZ  NOT NULL,
    endpoint     TEXT         NOT NULL,
    payload      JSONB        NOT NULL,
    UNIQUE (site_id, fetched_hour, endpoint)
);
```

`payload` struktuur: `{"records": [{"code": "Pb", "rawValue": 1.23}, ...]}` — 343 kirjet.

`endpoint` veerg on hetkel alati `'diagnostics'` — tabel on mõeldud ainult reaalajas ingestiks.

### `bronze.vrm_stats_raw` — backfill

```sql
CREATE TABLE bronze.vrm_stats_raw (
    id           BIGSERIAL    PRIMARY KEY,
    site_id      TEXT         NOT NULL,
    fetched_at   TIMESTAMPTZ  NOT NULL,
    fetched_hour TIMESTAMPTZ  NOT NULL,
    payload      JSONB        NOT NULL,
    UNIQUE (site_id, fetched_hour)
);
```

`payload` struktuur: `{"bs": 90.0, "bv": 52.5, "total_solar_yield": 0.45, ...}` — lame dict.

### UPSERT strateegia (mõlemad tabelid)

`fetched_hour` arvutatakse Pythonis (minutid ja sekundid nullitakse).
Kui sama tunni kohta tuleb uus kirje (Airflow retry või backfill korduvkäivitus),
kirjutatakse eelmine üle — duplikaate ei teki.

---

## Silver kiht

### `stg_vrm_energy_snapshot` — diagnostics

**Graanulaarsus:** üks rida = üks tund (site_id + fetched_hour).

Lahti pakkimine kasutab **kaheastmelist explode → pivot** mustrit:

```sql
-- 1. laiendamine: 1 bronze rida → 343 rida
jsonb_array_elements(payload -> 'records') AS record

-- 2. pööramine: 343 rida → 1 lai rida
MAX(CASE WHEN record->>'code' = 'bs' THEN (record->>'rawValue')::numeric END) AS battery_soc_pct
```

`MAX(CASE WHEN ...)` + `GROUP BY` on valitud sest: töötab ka siis, kui mõni `code`
mõnel tunnil puudub (tagastab `NULL`), ei sõltu massiivi järjekorrast ega nõua lisalaiendusi.

Eraldatavad `code`-väärtused:

| Kategooria | Koodid | Tüüp |
|---|---|---|
| Energiavood (kWh) | `Pb`, `Pc`, `Gb`, `Gc`, `Bc`, `dpE`, `dH21`, `dH22` | Perioodi summa |
| PV võimsus (W) | `P`, `P2`, `P3` | Hetkväärtus |
| Tarbimine (W) | `a1`, `a2`, `a3` | Hetkväärtus |
| Aku seisund | `bs`, `bp`, `bv`, `bT`, `bst` | Hetkväärtus / tekst |
| Aku tervis | `SOH`, `dH21`, `dH22` | Delta / % |
| Süsteemi olekud | `ss`, `Agl`, `pS` | Tekst |

### `stg_vrm_stats_snapshot` — stats backfill

**Allikas:** `bronze.vrm_stats_raw` (eraldi tabel, ei vaja `endpoint` filtrit).

**Graanulaarsus:** sama — üks rida = üks tund (site_id + fetched_hour).

`/stats` lõpp-punkt tagastab lame dict-i, mitte `code/rawValue` massiivi.
Silver mudel parsib otse:

```sql
(payload ->> 'bs')::numeric                AS battery_soc_pct
(payload ->> 'bv')::numeric                AS battery_voltage_v
(payload ->> 'total_solar_yield')::numeric AS pvinverter_energy_delta_kwh
```

Kõik muud 25-st veerust on `NULL` — `/stats` ei tagasta granulaarset energiavoogude jaotust.

| Silver veerg | Saadaval backfill-ist |
|---|---|
| `pvinverter_energy_delta_kwh` | ✅ (`total_solar_yield`) |
| `battery_soc_pct` | ✅ (tunni keskmine) |
| `battery_voltage_v` | ✅ (tunni keskmine) |
| Kõik energiavood (`pv_to_*`, `battery_to_*`, jne) | NULL |
| Watts väljad, temperatuur, olekutekstid | NULL |

### Inkrementaalne strateegia

`stg_vrm_energy_snapshot` on inkrementaalne tabel (`delete+insert`, unikaalvõti `vrm_snapshot_key`).
Filter `fetched_at > MAX(fetched_at) - 1 tund` tagab, et osaliste andmetega tunni kirjed
kirjutatakse üle, kui Airflow jookseb sama tunni sees uuesti. `append` ei sobi, kuna
Airflow retry tekitaks duplikaate.

`stg_vrm_stats_snapshot` on **view**, mitte tabel. `bronze.vrm_stats_raw` on ühekordse
backfill-i tabel — uusi ridu ei tule pidevalt, transformatsioon on triviaalne (kolm
`payload ->>` väljavõtet) ja ridade arv on väike (~4 000 rida aasta kohta). Inkrementaalne
materjalisatsioon ei annaks midagi juurde.

---

## Gold: `fct_vrm_energy_hourly`

Kimball faktitabel — üks rida = üks tund, üks objekt.

### Kahe silver-allika ühendamine

Faktitabel loeb mõlemast silver-mudelist ja deduplikeerib `ROW_NUMBER()` abil:

```sql
select *, 'diagnostics' as _source from stg_vrm_energy_snapshot
union all
select *, 'stats'       as _source from stg_vrm_stats_snapshot
```

Kui sama tunni kohta on mõlemas allikas rida, eelistatakse `diagnostics`.

### Skeema

| Veerg | Tüüp | Märkus |
|---|---|---|
| `vrm_hourly_key` | surrogate PK | site_id + fetched_hour |
| `time_key` | FK → dim_time | |
| `location_key` | FK → dim_location | |
| `site_id`, `timestamp_utc` | | |
| `pv_total_w`, `pv_l1_w/l2_w/l3_w` | numeric | hetkväärtus, W |
| `load_total_w`, `load_l1/l2/l3_w` | numeric | hetkväärtus, W |
| `pv_to_battery_kwh`, `pv_to_consumers_kwh` | numeric | perioodi summa, kWh |
| `grid_to_battery_kwh`, `grid_to_consumers_kwh` | numeric | perioodi summa, kWh |
| `battery_to_consumers_kwh` | numeric | perioodi summa, kWh |
| `battery_soc_pct`, `battery_power_w`, `battery_voltage_v` | numeric | pooladitiivne |
| `battery_temp_c`, `battery_soh_pct` | numeric | pooladitiivne |
| `battery_discharged_kwh_delta`, `battery_charged_kwh_delta` | numeric | kWh |
| `pvinverter_energy_delta_kwh` | numeric | KPI-de nimetaja |
| `battery_state`, `system_state`, `grid_alarm`, `pvinverter_status` | text | mitteaditiivne |
| `data_source` | text | `'diagnostics'` või `'stats'` |
| `fetched_at` | timestamptz | |

### Faktide tüübid (Kimball)

| Tüüp | Veerud | Lubatud agregatsioon |
|---|---|---|
| **Täielikult aditiivsed** | kWh energiavood, kWh deltad | SUM üle aja ja objektide |
| **Pooladitiivsed** | W, %, V, °C | AVG üle aja — mitte SUM |
| **Mitteaditiivsed** | olekutekstid | loendamine, mitte agregatsioon |

---

## Gold: `mart_solar_performance_hourly`

Ühendab VRM energiamõõdikud Open-Meteo ilmaandmetega:

```
fct_vrm_energy_hourly ──┐
                         ├── LEFT JOIN timestamp_utc järgi
fct_meteo_hourly      ──┘
```

LEFT JOIN on vajalik, sest meteo- ja VRM-ingest on sõltumatud — kui ilmateenuse API
oli maas, ei tohiks VRM-andmed sellest kaduda.

**KPI valemid** (kõik kasutavad ainult kWh aditiivseid fakte):

| KPI | Valem |
|---|---|
| `self_sufficiency_rate` | `(pv_to_consumers_kwh + battery_to_consumers_kwh) / (... + grid_to_consumers_kwh)` |
| `self_consumption_rate` | `(pv_to_consumers_kwh + pv_to_battery_kwh) / pvinverter_energy_delta_kwh` |
| `performance_ratio` | `pvinverter_energy_delta_kwh / (shortwave_radiation_wm2 / 1000 × capacity_kw)` |

**KPI-de saadavus andmeallika järgi:**

| KPI | `data_source = 'diagnostics'` | `data_source = 'stats'` |
|---|---|---|
| `performance_ratio` | ✅ | ✅ |
| `self_sufficiency_rate` | ✅ | NULL |
| `self_consumption_rate` | ✅ | NULL |

---

## Backfill

### Miks backfill?

Reaalajas ingest kogub ainult hetkeseisundit — enne süsteemi käivitamist puuduvad ajaloolised
andmed. Backfill täidab selle lünga `/stats` lõpp-punkti kaudu.

### Käivitamine Airflow UI-st

1. Ava DAG `vrm_backfill`
2. Klõpsa **Trigger DAG w/ config**
3. Täida kuupäevaväljad (`start_date`, `end_date`) — vaikimisi 6 kuud tagasi kuni eile
4. Käivita

Pärast edukat bronze laadimist käivita dbt:

```bash
dbt run --select stg_vrm_stats_snapshot fct_vrm_energy_hourly mart_solar_performance_hourly
```

### Laadimisloogika

- Ajavahemik jagatakse 30-päevasteks tükkideks — ~6 API päringut aasta backfill-i kohta
- Iga tunni kohta kirjutatakse üks lame JSON-rida bronzesse (`endpoint='stats'`)
- `ON CONFLICT DO UPDATE` — korduvkäivitamine on ohutu (idempotentne)
- Kõik backfill-i read saavad sama `fetched_at` (käivitamise hetk), mis tagab
  dbt inkrementaalse filtri korrektse töö

### `data_source` veerg

`fct_vrm_energy_hourly` ja `mart_solar_performance_hourly` sisaldavad `data_source` veergu:

| Väärtus | Tähendus |
|---|---|
| `'diagnostics'` | Reaalajas ingest |
| `'stats'` | Ajaloolise backfill-i käigus laaditud |

---

## Konfigureerimine

| Muutuja | Kirjeldus | Kasutatav |
|---|---|---|
| `VRM_API_TOKEN` | VRM API ligipääsuvõti | ingest + backfill |
| `VRM_SITE_ID` | Paigaldise ID | ingest + backfill |
| `SUPABASE_DB_*` | Andmebaasi ühendusparameetrid | ingest + backfill |
| `VRM_BACKFILL_START` | Backfill-i alguskuupäev (ISO 8601) | ainult backfill |
| `VRM_BACKFILL_END` | Backfill-i lõppkuupäev (ISO 8601) | ainult backfill |

Kui `VRM_API_TOKEN` või `VRM_SITE_ID` puudub reaalajas ingestis, lõpetab moodul töö
koodiga `0` (ohutu käitumine lokaalses arenduskeskkonnas).

---

## Testimine

```bash
pytest tests/ingest/test_vrm_ingest.py -v    # reaalajas ingest
pytest tests/ingest/test_vrm_backfill.py -v  # backfill
```

| Testiklass | Mida testitakse |
|---|---|
| `TestFetchDiagnostics` | URL, token päises, JSON vastus, HTTP vead, timeout |
| `TestUpsert` | INSERT bronzesse, ON CONFLICT, parameetrite järjekord, commit |
| `TestMain` (ingest) | Puuduvad muutujad → skip, edukas jooksmine, ühenduse sulgemine |
| `TestDateChunks` | Ajavahemiku tükeldamine |
| `TestFetchStatsChunk` | URL, token, interval=hours, HTTP vead |
| `TestUnpackToHourlyRows` | JSON lahtipakkimine, tuntud koodid, sorteerimine |
| `TestUpsertStatsRows` | INSERT bronzesse, endpoint=stats, JSON serialiseerimine, commit |
| `TestRunBackfill` | Tükkide töötlemine, tühi vastus, veapropageerimine |
| `TestMain` (backfill) | Puuduvad muutujad, edukas jooksmine, ühenduse sulgemine |

---

## Seotud failid

| Fail | Kirjeldus |
|---|---|
| `src/ingest/vrm_ingest.py` | Reaalajas ingest |
| `src/ingest/vrm_backfill.py` | Ajaloolise backfill-i skript |
| `airflow/dags/dag_vrm_ingest.py` | Hourly DAG |
| `airflow/dags/dag_vrm_backfill.py` | Backfill DAG (käsitsi, kuupäevaparameetritega) |
| `sql/004_bronze_vrm_raw.sql` | `bronze.vrm_raw` tabeli loomine |
| `sql/005_bronze_vrm_stats_raw.sql` | `bronze.vrm_stats_raw` tabeli loomine |
| `dbt/models/silver/stg_vrm_energy_snapshot.sql` | Silver — diagnostics |
| `dbt/models/silver/stg_vrm_stats_snapshot.sql` | Silver — stats backfill |
| `dbt/models/gold/fct_vrm_energy_hourly.sql` | Gold faktitabel |
| `dbt/models/gold/mart_solar_performance_hourly.sql` | Analüütikamart |
| `tests/ingest/test_vrm_ingest.py` | Ingest ühiktestid |
| `tests/ingest/test_vrm_backfill.py` | Backfill ühiktestid |

---

## Graafikute ideed (Grafana)

Kõik alljärgnevad päringud käivad vastu `gold.mart_solar_performance_hourly`.

### Reaalajaline seisund (stat/gauge paneel)

| Mõõdik | Veerg | Märkus |
|---|---|---|
| Hetke PV toodang | `pv_total_w` | viimane rida |
| Aku laetuse tase | `battery_soc_pct` | viimane rida, gauge 0–100% |
| Aku olek | `battery_state` | tekst: charging / discharging / idle |
| Süsteemi olek | `system_state` | hoiatus kui ≠ "Running" |
| Tarbimise hetkvõimsus | `load_total_w` | viimane rida |

### Päevane energiavoog (aegrida + virntulpdiagramm)

PV toodang vs tarbimine ühel teljel (W, tunnipõhine):
```sql
select timestamp_utc, pv_total_w, load_total_w
from gold.mart_solar_performance_hourly
where timestamp_utc >= $__timeFrom() and timestamp_utc <= $__timeTo()
```

Energiavoogude jaotus virntulpdiagrammina (kWh/tund) — näitab kuhu PV energia läheb:
```sql
select timestamp_utc,
       pv_to_battery_kwh,
       pv_to_consumers_kwh,
       grid_to_consumers_kwh,
       battery_to_consumers_kwh
from gold.mart_solar_performance_hourly
```

### Aku analüüs

- **SOC päevane tsükkel** — `battery_soc_pct` aegrida: näitab laadimist päeval ja tühjenemist öösel
- **Laaditud vs tühendatud energia päevas** — `battery_charged_kwh_delta` ja `battery_discharged_kwh_delta` tulpdiagrammina päevade kaupa
- **Aku tervise trend** — `battery_soh_pct` aegrida kuude lõikes; langus viitab kulumisele

### KPI trendid (aegrida)

```sql
select timestamp_utc,
       self_sufficiency_rate,
       self_consumption_rate,
       performance_ratio
from gold.mart_solar_performance_hourly
where data_source = 'diagnostics'   -- backfill read on osalised KPI-de osas
```

- **Omavarustuse määr** — kui suur osa tarbimisest kaetakse päikese + akuga (eesmärk: võimalikult kõrge)
- **Omakasutusmäär** — kui suur osa PV toodangust tarbitakse kohapeal (eesmärk: kõrge, viitab hea dimensioneerimisele)
- **Tootlikkuse suhtarv** — tegelik toodang vs teoreetiline max kiirguse põhjal; langus viitab varjutusele, mustusele või rikele

### Ilma vs toodangu korrelatsioon (scatter / dual-axis)

```sql
select shortwave_radiation_wm2,
       pvinverter_energy_delta_kwh,
       cloud_cover_pct,
       season
from gold.mart_solar_performance_hourly
where is_daytime = true
```

- Kiirgus (W/m²) vs PV toodang (kWh) — lineaarne seos, kõrvalekalded viitavad probleemidele
- Pilvisus vs tootlikkuse suhtarv — kvantitatiivselt nähtav pilvisuse mõju
- Aastaajad eraldi värviga — hooajalise erinevuse visualiseerimine

### Hooajaline kokkuvõte (tulpdiagramm)

```sql
select season,
       avg(self_sufficiency_rate)  as keskmine_omavarustus,
       sum(pvinverter_energy_delta_kwh) as kogu_toodang_kwh,
       avg(performance_ratio)      as keskmine_pr
from gold.mart_solar_performance_hourly
group by season
```

Näitab selgelt talve/suve erinevust — kasulik süsteemi dimensioneerimise hindamiseks.

### Kuupäevapõhised kokkuvõtted (tabel / bar chart)

```sql
select date_trunc('day', timestamp_utc) as kuupäev,
       sum(pvinverter_energy_delta_kwh)  as toodang_kwh,
       sum(grid_to_consumers_kwh)        as võrgust_kwh,
       avg(battery_soc_pct)              as keskmine_soc,
       avg(self_sufficiency_rate)        as omavarustus
from gold.mart_solar_performance_hourly
group by 1
order by 1 desc
```

---

## Edasiarendused

**Indeksid** — praegu pole vajalikud (üks objekt, ~8 760 rida/aastas). Tasub lisada
`timestamp_utc` ja `site_id` veergudele, kui objekte lisandub mitu või Grafana
päringuaeg muutub märgatavaks.

**Mitu objekti** — `vrm_sites` seed ja `site_id` veerg on ette valmistatud.
Lisandamiseks piisab uuest reast seedis ja `VRM_SITE_ID` loopimisest ingestis.

**Gateway konfiguratsioon** — `bronze.vrm_raw` sisaldab ka ESS seadeid, firmware
versioone jne (harvasti muutuvad). Nende muutuste jälgimiseks sobiks tulevikus
eraldi `stg_vrm_site_config` snapshot.
