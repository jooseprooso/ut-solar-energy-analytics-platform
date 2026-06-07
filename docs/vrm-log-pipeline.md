# VRM Log pipeline

Käesolev dokument kirjeldab VRM Log andmevoogu — `/download` lõpp-punktist kuni
analüütikamartin välja — ning selgitab kõiki olulisi disainiotsuseid.

> **Hetkeseisuvaate pipeline** asub eraldi dokumendis: [`docs/vrm-pipeline.md`](vrm-pipeline.md)

---

## Ülevaade

```
┌──────────────────────────────────────┐
│        VRM Reports API               │
│  /download?type=log&format=csv       │
│  (15-min andmepunktid, kuni 7 päeva) │
└──────────────────┬───────────────────┘
                   │  HTTP GET · iga tund
                   ▼
┌──────────────────────────────────────┐
│        bronze.vrm_log_raw            │  üks rida (site_id, recorded_at) kohta
│        15-min granulaarsus           │  JSONB + lamedad veerud · upsert
└──────────────────┬───────────────────┘
                   │  tunnipõhine agregatsiooni + veergude ümbernimetamine
                   ▼
┌──────────────────────────────────────┐
│        silver.stg_vrm_log_hourly     │  üks rida (site_id, tund) kohta
│        inkrementaalne mudel          │  AVG hetkväärtused · MAX−MIN energiad
└──────────────────┬───────────────────┘
                   │  asendvõtmed + dimensioon-FK-d
                   ▼
┌──────────────────────────────────────┐
│        gold.fct_vrm_log_hourly       │  Kimball faktitabel
│        inkrementaalne mudel          │  vrm_log_key · time_key · location_key
└──────────────────┬───────────────────┘
                   │
          ┌────────┴────────┐
          │                 │
          ▼                 ▼
  fct_meteo_hourly      vrm_sites
  (LEFT JOIN)          (LEFT JOIN)
          │
          ▼
┌──────────────────────────────────────┐
│        gold.mart_vrm_log_hourly      │  KPI-d + ilmaandmed + kalendrimärgendid
│        inkrementaalne mudel          │  ajaloolise analüüsi lõpptabel
└──────────────────────────────────────┘
```

---

## ELT põhimõte

| Etapp | Komponent | Toiming |
|:---:|:---|:---|
| **Extract** | `vrm_log_ingest.py` | CSV allalaadimine VRM Reports API-st tükikaupa |
| **Load** | Python + PostgreSQL | Toored read kirjutatakse `bronze.vrm_log_raw`-i muutmata kujul |
| **Transform** | dbt | Agregatsiooni, veergude kaardistamine ja KPI arvutus andmelaos |

Bronze kiht salvestab iga 15-minutilise andmepunkti muutmata kujul. Kui veergude
kaardistamist on vaja muuta, saab ajaloolised andmed ümber transformeerida ilma
API-st uuesti laadimata. dbt mudelid on versioonihalduses ja käivitatavad igal
ajal muutumatu bronze-kihi vastu.

---

## VRM Reports API

```
GET https://vrm-reports-api.victronenergy.com/download
    ?idSite=<täisarv>
    &startTime=<unix_sekundid>
    &endTime=<unix_sekundid>
    &type=log
    &format=csv
```

| Parameeter | Väärtus |
|:---|:---|
| Autentimine | `X-Authorization: Token <VRM_API_TOKEN>` |
| Vastuse formaat | CSV, 4-realine päis |
| Granulaarsus | ~15 min andmepunktid |

**CSV päise struktuur:**

| Rida | Sisu |
|:---:|:---|
| 0 | Seadmeploki sildid (nt `Battery Monitor [512]`), ulatuvad üle veergude |
| 1 | Mõõdiku nimed; `veerg 0` = saidi ajavööndi string (nt `Europe/Tallinn (+03:00)`) |
| 2 | Ühikud |
| 3+ | Andmeread; `veerg 0` = ajatempel saidi kohalikus ajavööndis |

Ajatemplid teisendatakse ingestis kohalikust ajavööndist UTC-sse.

> **Kiiruspiirang:** HTTP 429 on võimalik. Ingest-skript kordab päringut kuni
> 8 korda eksponentsiaalse taandumisega (algviide 2 s, max 120 s).

> **7-päeva piir:** päringud, mis ületavad ~7 päeva, käivitavad VRM API
> asünkroonse režiimi (HTTP 202) — andmed saadetakse e-posti teel, mitte
> API vastuses. `chunk_days` maksimaalne ohutu väärtus on **7**.

---

## Bronze: `bronze.vrm_log_raw`

**Migratsioon:** `sql/006_bronze_vrm_log_raw.sql`  
**Graanulaarsus:** üks rida `(site_id, recorded_at)` kohta, kus `recorded_at` on
15-minutilise andmepunkti UTC ajatempel.  
**Upsert:** `ON CONFLICT (site_id, recorded_at) DO UPDATE` — retry ja backfill on idempotentsed.

```sql
CREATE TABLE bronze.vrm_log_raw (
    site_id      TEXT         NOT NULL,
    recorded_at  TIMESTAMPTZ  NOT NULL,  -- 15-min andmepunkti ajatempel UTC-s
    fetched_at   TIMESTAMPTZ  NOT NULL,  -- ingest-käivituse ajatempel
    metrics      JSONB        NOT NULL,  -- täielik {plokk: {mõõdik: väärtus}}
    -- lamedad veerud (kiired päringud ilma JSONB parsimiseta):
    battery_soc              NUMERIC,
    battery_voltage          NUMERIC,
    ...
    UNIQUE (site_id, recorded_at)
);
```

`metrics` JSONB veerg säilitab kogu rea — kui veergude kaardistamist on vaja
muuta, saab bronze-kihi vastu uuesti transformeerida ilma API-le pöördumata.

### Lamedad veerud

| Veerg | Seadmeplokk | Kirjeldus |
|:---|:---|:---|
| `battery_soc` | Battery Monitor [512] | Laetuse tase, % |
| `battery_voltage` | Battery Monitor [512] | Pinge, V |
| `battery_current` | Battery Monitor [512] | Vool, A (+ = laadimine) |
| `battery_temperature` | Battery Monitor [512] | Temperatuur, °C |
| `battery_power` | System overview [0] | Võimsus, W (+ = laadimine) |
| `battery_discharged_energy` | Battery Monitor [512] | Kumulatiivne väljastus, kWh |
| `battery_charged_energy` | Battery Monitor [512] | Kumulatiivne laadimine, kWh |
| `ac_consumption_l1/l2/l3` | System overview [0] | AC koormusvõimsus faaside kaupa, W |
| `pv_power_l1/l2/l3` | PV Inverter [20] | PV AC väljundvõimsus faaside kaupa, W |
| `pv_energy_l1/l2/l3` | PV Inverter [20] | PV kumulatiivne energia faaside kaupa, kWh |
| `grid_input_power_l1/l2/l3` | VE.Bus System [276] | Võrgust sisendvõimsus, W |
| `grid_input_voltage_l1/l2/l3` | VE.Bus System [276] | Võrgu pinge, V |
| `grid_input_current_l1/l2/l3` | VE.Bus System [276] | Võrgu vool, A |
| `grid_input_frequency_l1/l2/l3` | VE.Bus System [276] | Võrgu sagedus, Hz |
| `grid_alarm` | System overview [276] | Alarmi olek tekstina |

---

## Silver: `stg_vrm_log_hourly`

**Fail:** `dbt/models/silver/stg_vrm_log_hourly.sql`  
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='vrm_log_key'`)  
**Allikas:** `bronze.vrm_log_raw`

Silver agregeerib bronze'i 15-minutilised andmepunktid tunnipõhisteks ridadeks
(`GROUP BY site_id, date_trunc('hour', recorded_at)`).

**Kahe tüübi agregatsioonistrateegiad:**

| Mõõdiku tüüp | Strateegia | Näited |
|:---|:---|:---|
| Hetkväärtused (W, %, V, A, °C, Hz) | `AVG` üle tunni andmepunktide | `battery_soc`, `pv_power_l1` |
| Kumulatiivsed loendurid (kWh) | `greatest(0, MAX − MIN)` tunni sees | `pv_energy_l1`, `battery_discharged_energy` |

> `greatest(0, ...)` kaitseb loenduri lähtestamise (seadme taaskäivitus) eest —
> negatiivne delta asendatakse nulliga.

Neli faaside summat arvutatakse:

| Tuletatud veerg | Valem | NULL kui |
|:---|:---|:---|
| `ac_consumption_total_w` | `L1 + L2 + L3` | L1 on NULL |
| `pv_power_total_w` | `L1 + L2 + L3` | L1 on NULL |
| `pv_energy_total_kwh` | `L1 + L2 + L3` | L1 on NULL |
| `grid_input_power_total_w` | `L1 + L2 + L3` | L1 on NULL |

---

## Gold: `fct_vrm_log_hourly`

**Fail:** `dbt/models/gold/fct_vrm_log_hourly.sql`  
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='vrm_log_key'`)  
**Allikas:** `stg_vrm_log_hourly` LEFT JOIN `vrm_sites`

Kimball faktitabel — lisab asendvõtmed ja nimetab `recorded_at` ümber
`timestamp_utc`-ks. KPI-sid siin ei ole — need kuuluvad martti.

| Võtmeveerg | Genereeritakse |
|:---|:---|
| `vrm_log_key` | `dbt_utils.generate_surrogate_key(['site_id', 'timestamp_utc'])` |
| `time_key` | `dbt_utils.generate_surrogate_key(['timestamp_utc'])` |
| `location_key` | `dbt_utils.generate_surrogate_key(['latitude', 'longitude'])` |

### Faktide tüübid (Kimball)

| Tüüp | Veerud | Lubatud agregatsioon |
|:---|:---|:---|
| **Täielikult aditiivsed** | kWh energiavood (`pv_energy_*`, `battery_*_kwh`) | SUM üle aja ja objektide |
| **Pooladitiivsed** | W, %, V, °C, A, Hz | AVG üle aja — mitte SUM |
| **Mitteaditiivsed** | `grid_alarm` (tekst) | Loendamine, mitte agregatsioon |

---

## Gold: `mart_vrm_log_hourly`

**Fail:** `dbt/models/gold/mart_vrm_log_hourly.sql`  
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='vrm_log_key'`)  
**Allikad:** `fct_vrm_log_hourly` LEFT JOIN `fct_meteo_hourly` + `vrm_sites`

Kõik faktitabeli veerud edastatakse. Mart lisab kolm plokki:

### Kalendrimärgendid (arvutatakse inline `timestamp_utc`-st)

| Veerg | Kirjeldus |
|:---|:---|
| `hour_of_day` | Tunni number (0–23) |
| `date_day` | Kuupäev (UTC) |
| `month` | Kuu number (1–12) |
| `season` | `winter` / `spring` / `summer` / `autumn` |
| `is_daytime` | `true` vahemikus 06:00–20:00 UTC |

### Ilmaandmed (`fct_meteo_hourly`, NULL kui meteo pole saadaval)

| Veerg | Ühik | Kirjeldus |
|:---|:---:|:---|
| `shortwave_radiation_wm2` | W/m² | Globaalne horisontaalne kiirgus |
| `direct_radiation_wm2` | W/m² | Otsekiirgus |
| `sunshine_duration_s` | s | Päikesepaiste kestus tunnis |
| `cloud_cover_pct` | % | Pilvisus |

### KPI-d

| Veerg | Valem | NULL kui |
|:---|:---|:---|
| `performance_ratio` | `pv_energy_total_kwh / (shortwave_radiation_wm2 / 1000 × capacity_kw)` | kiirgus ≤ 50 W/m² või võimsus teadmata |
| `specific_yield_kwh_per_kwp` | `pv_energy_total_kwh / capacity_kw` | võimsus teadmata |
| `battery_net_kwh` | `battery_charged_kwh − battery_discharged_kwh` | kumbki veerg NULL |
| `grid_import_kwh_estimate` | `grid_input_power_total_w / 1000` | võrguvõimsus NULL |
| `pv_cover_ratio` | `pv_energy_total_kwh / (pv_energy_total_kwh + grid_import_kwh_estimate)` | kumbki sisend NULL |

> `grid_import_kwh_estimate` on tähistatud `_estimate`: eeldab tunni sees püsivat
> võimsust. `pv_cover_ratio` on varustuspoole proksi — erineb `mart_solar_performance_hourly`
> `self_sufficiency_rate`-st, mis kasutab GX seadme sisemist energiavoogude arvestust
> (saadaval ainult `/diagnostics` kaudu).

---

## DAG: `vrm_log_ingest`

**Fail:** `airflow/dags/dag_vrm_log_ingest.py`  
**Ajakava:** `@hourly`  
**Ülesanded:** `validate_config >> ingest_vrm_log`

### Vaikimisi režiim (tunnipõhine)

Iga planeeritud käivituse puhul arvutab skript ajavahemiku automaatselt:

```
algus = floor(praegune aeg tunnini) − 1 tund
lõpp  = floor(praegune aeg tunnini)
```

### Backfill-i režiim

Käivita DAG käsitsi parameetritega:

| Parameeter | Formaat | Vaikimisi | Näide |
|:---|:---|:---|:---|
| `start_time` | `YYYY-MM-DDTHH:MM:SS` (UTC) | eelmine tund | `2025-01-01T00:00:00` |
| `end_time` | `YYYY-MM-DDTHH:MM:SS` (UTC) | praegune tunnipiir | `2026-01-01T00:00:00` |
| `chunk_days` | täisarv 1–7 | `1` | `7` |

Soovitatav konfiguratsioon pikema backfill-i jaoks:

```json
{
  "start_time":  "2025-01-01T00:00:00",
  "end_time":    "2026-01-01T00:00:00",
  "chunk_days":  7
}
```

---

## Konfigureerimine

| Muutuja | Kirjeldus | Kasutatav |
|:---|:---|:---|
| `VRM_API_TOKEN` | VRM API autentimistoken | ingest |
| `VRM_SITE_ID` | Paigaldise ID | ingest |
| `SUPABASE_DB_HOST` | Andmebaasi host | ingest |
| `SUPABASE_DB_PORT` | Andmebaasi port | ingest |
| `SUPABASE_DB_NAME` | Andmebaasi nimi | ingest |
| `SUPABASE_DB_USER` | Andmebaasi kasutaja | ingest |
| `SUPABASE_DB_PASSWORD` | Andmebaasi parool | ingest |
| `VRM_LOG_START` | Algusaja ülekiri (ISO 8601 UTC) | ainult backfill |
| `VRM_LOG_END` | Lõpuaja ülekiri (ISO 8601 UTC) | ainult backfill |
| `VRM_LOG_CHUNK_DAYS` | Tükisuurus päevades (max 7) | ainult backfill |

---

## Backfill-i käivitamine

1. Ava Airflow UI → DAG `vrm_log_ingest`
2. Klõpsa **Trigger DAG w/ config**
3. Täida `start_time` ja `end_time` (UTC ISO 8601)
4. Käivita

Koheseks transformeerimiseks ilma järgmist tunnipõhist käivitust ootamata:

```bash
dbt run --project-dir dbt --profiles-dir dbt \
  --select stg_vrm_log_hourly fct_vrm_log_hourly mart_vrm_log_hourly
```

---

## Backfill-i jõudlus — optimeerimise ajalugu

Backfill-i kiirus läbis kolm iteratsiooni. Mõõtmised tehti pärisandmete peal
(~480 rida päevas).

### Iteratsioon 1 — algne teostus

`chunk_days=1`, üks andmebaasi `execute()` kutse rea kohta.

| Faas | Aeg |
|:---|:---|
| API päring (1 päev) | ~2–3 s |
| DB kirjutamine: 600 rida × ~100 ms latents | ~60 s |
| **7 päeva kokku** | **~8 min** |

### Iteratsioon 2 — `chunk_days=7`

| Faas | Aeg |
|:---|:---|
| API päring (7 päeva) | ~5 s |
| DB kirjutamine: 3 379 rida × ~100 ms | ~338 s |
| **7 päeva kokku** | **~5,5 min** |

### Iteratsioon 3 — `execute_values` partiitöötlus ✓

`psycopg2.extras.execute_values` pakib kõik read ühte `INSERT ... VALUES (...)` lausesse.

| Faas | Aeg |
|:---|:---|
| API päring (7 päeva) | ~5 s |
| DB kirjutamine: 7 paketti × ~100 ms | ~1 s |
| **30 päeva kokku** (`chunk_days=7`, 5 päringut) | **~36 s** |

| | Iteratsioon 1 | Iteratsioon 2 | Iteratsioon 3 |
|:---|:---:|:---:|:---:|
| `chunk_days` | 1 | 7 | 7 |
| DB kirjutamine | 1 `execute()` / rida | 1 `execute()` / rida | 500 rida / pakett |
| 7 päeva | ~8 min | ~5,5 min | ~6 s |
| 30 päeva | ~35 min | ~28 min | ~36 s |
| **Kiirendus** | — | ~1,3× | **~55×** |

> **Miks see nii palju kiirendas:** kitsaskoht polnud kunagi API kiirus ega
> andmemaht — see oli **võrgulatents**. Iga `execute()` kutse = üks eraldi
> TCP-edastus kaugandmebaasi (~100 ms). 3 379 edastust = 338 s.
> Partiitöötlus koondab need 7 edastuseks = ~1 s.

---

## Testimine

```bash
pytest tests/ingest/test_vrm_log_ingest.py -v               # 68 ühiktesti
pytest tests/airflow/test_vrm_log_ingest_dag_contract.py -v # 9 kontrakttesti
```

| Testiklass | Mida testitakse |
|:---|:---|
| `TestDownloadReport` | URL, autentimispäis, päringuparameetrid, 429 taandumine, 202 viga, JSON kaitse |
| `TestParseHeaderTimezone` | Nimeline ajavöönd, UTC nihe varuvariandina, tühi string |
| `TestColumnRuns` | Plokisiltide grupeerimine, tühikute eemaldamine, äärejuhud |
| `TestCoerceValue` | int/float/string/None tüübimuundus |
| `TestParseSampleTime` | Kohalik → UTC teisendus, mitteloetavad sisendid |
| `TestBuildMetrics` | Pesastatud dict-i koostamine, tühiväärtuste väljajätmine |
| `TestExtractFlatValues` | FLAT_COLUMN_MAP järjestus, `grid_alarm` tekstina säilitamine |
| `TestIngestCsvText` | <4 rida tõstab vea, ridade arv, dry run, tühjade ridade vahelejätmine, commit |
| `TestUpsertLogRow` | INSERT SQL, ON CONFLICT, parameetrite sidumine, commit |
| `TestBuildIngestConfig` | Puuduvad muutujad, vaikimisi ajaaken, muutujate ülekiri |
| `TestMain` | Välumiskoodid, ühenduse sulgemine õnnestumisel ja ebaõnnestumisel |

---

## Seotud failid

| Fail | Kirjeldus |
|:---|:---|
| `sql/006_bronze_vrm_log_raw.sql` | Bronze tabeli migratsioon |
| `src/ingest/vrm_log_ingest.py` | CSV allalaadimine → parsimine → bronze upsert |
| `airflow/dags/dag_vrm_log_ingest.py` | Tunnipõhine DAG backfill-i parameetritega |
| `dbt/models/silver/stg_vrm_log_hourly.sql` | Silver — tunnipõhine agregatsiooni |
| `dbt/models/gold/fct_vrm_log_hourly.sql` | Gold faktitabel |
| `dbt/models/gold/mart_vrm_log_hourly.sql` | Gold mart — ilmaandmed + KPI-d |
| `dbt/models/silver/schema.yml` | dbt testid silver-kihi jaoks |
| `dbt/models/gold/schema.yml` | dbt testid faktitabeli ja mardi jaoks |
| `tests/ingest/test_vrm_log_ingest.py` | Ingest-skripti ühiktestid |
| `tests/airflow/test_vrm_log_ingest_dag_contract.py` | DAG kontrakttestid |
