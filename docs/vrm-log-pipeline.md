# VRM Log pipeline

Käesolev dokument kirjeldab VRM Log andmevoogu — `/download` lõpp-punktist kuni
analüütikamartin välja — ning selgitab kõiki olulisi disainiotsuseid.

---

## Ülevaade

```
vrm-reports-api.victronenergy.com/download
              │  (CSV, type=log, format=csv)
              ▼
  bronze.vrm_log_raw          üks rida (site_id, tund) kohta, toored andmed + JSONB
              │
              ▼
  stg_vrm_log_hourly          silver view — veergude ümbernimetamine + faaside summad
              │
              ▼
  fct_vrm_log_hourly          gold faktitabel — asendvõtmed, dimensioon-FK-d
              │
              ├── LEFT JOIN fct_meteo_hourly
              └── LEFT JOIN dim_time
                            │
                            ▼
              mart_vrm_log_hourly   gold mart — KPI-d + ilmaandmed
```

`dim_time` ühendab tunnid kolmest allikast: `stg_meteo_hourly`,
`stg_vrm_energy_snapshot` ja `stg_vrm_log_hourly` — seega on `season` ja
`is_daytime` täidetud ka ajalooliste backfill-andmete puhul.

dbt transformatsioonid käivitab olemasolev `pipeline_smoke_test` DAG
(`dbt run` ilma `--select` filtrita), mis haarab automaatselt uued mudelid.

---

## ELT põhimõte

| Etapp | Vastutav komponent | Mis toimub |
|---|---|---|
| **Extract** | `vrm_log_ingest.py` | CSV allalaadimine VRM Reports API-st |
| **Load** | Python + Supabase | Toored read kirjutatakse `bronze.vrm_log_raw`-i muutmata kujul; täielik `metrics` JSONB säilitatakse |
| **Transform** | dbt | Veergude kaardistamine ja KPI arvutus andmelaos |

Bronze kiht salvestab iga CSV rea muutmata kujul. Kui välja kaardistamist on
vaja muuta, saab ajaloolised andmed ümber transformeerida ilma API-st uuesti
laadimata. dbt mudelid on versioonihalduses ja käivitatavad igal ajal
muutumatu bronze-kihi vastu.

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

**Autentimine:** `X-Authorization: Token <VRM_API_TOKEN>`

**Vastuse formaat — 4-realine päis:**

| Rida | Sisu |
|---|---|
| `rida 0` | Seadmeploki sildid (nt `Battery Monitor [512]`), ulatuvad üle veergude |
| `rida 1` | Mõõdiku nimed igas plokis; `veerg 0` = saidi ajavööndi string (nt `Europe/Tallinn (+03:00)`) |
| `rida 2` | Ühikud |
| `rida 3+` | Andmeread; `veerg 0` = ajatempel saidi kohalikus ajavööndis |

Ajatemplid teisendatakse ingestis kohalikust ajavööndist UTC-sse.

**Kiiruspiirang:** HTTP 429 on võimalik. Ingest-skript kordab päringut kuni 8
korda eksponentsiaalse taandumisega (algviide 2 s, max 120 s).

---

## Bronze: `bronze.vrm_log_raw`

**Migratsioon:** `sql/006_bronze_vrm_log_raw.sql`  
**Graanulaarsus:** üks rida `(site_id, recorded_at)` kohta, kus `recorded_at` on UTC tunniajaatempel.  
**UPSERT strateegia:** `ON CONFLICT (site_id, recorded_at) DO UPDATE` — Airflow retry ja backfill korduvkäivitus on idempotentsed.

### Veerud

| Veerg | Tüüp | Allikas | Kirjeldus |
|---|---|---|---|
| `site_id` | TEXT | — | VRM paigaldise ID |
| `recorded_at` | TIMESTAMPTZ | CSV veerg 0 | Tunniajaatempel UTC-s |
| `fetched_at` | TIMESTAMPTZ | ingest-käivitus | Kõik sama käivituse read jagavad seda väärtust |
| `metrics` | JSONB | kõik CSV veerud | Täielik pesastatud `{plokk: {mõõdik: väärtus}}` — terve rida säilitatud |
| `battery_soc` | NUMERIC | Battery Monitor [512] | Laetuse tase, % |
| `battery_voltage` | NUMERIC | Battery Monitor [512] | Pinge, V |
| `battery_current` | NUMERIC | Battery Monitor [512] | Vool, A (positiivne = laadimine) |
| `battery_temperature` | NUMERIC | Battery Monitor [512] | Aku temperatuur, °C |
| `battery_power` | NUMERIC | System overview [0] | Aku võimsus, W (positiivne = laadimine) |
| `battery_discharged_energy` | NUMERIC | Battery Monitor [512] | Perioodil akust väljastatud energia, kWh |
| `battery_charged_energy` | NUMERIC | Battery Monitor [512] | Perioodil akusse laetud energia, kWh |
| `ac_consumption_l1` | NUMERIC | System overview [0] | AC koormusvõimsus faasil L1, W |
| `ac_consumption_l2` | NUMERIC | System overview [0] | AC koormusvõimsus faasil L2, W |
| `ac_consumption_l3` | NUMERIC | System overview [0] | AC koormusvõimsus faasil L3, W |
| `pv_power_l1` | NUMERIC | PV Inverter [20] | PV AC väljundvõimsus faasil L1, W |
| `pv_power_l2` | NUMERIC | PV Inverter [20] | PV AC väljundvõimsus faasil L2, W |
| `pv_power_l3` | NUMERIC | PV Inverter [20] | PV AC väljundvõimsus faasil L3, W |
| `pv_energy_l1` | NUMERIC | PV Inverter [20] | PV toodetud energia faasil L1, kWh |
| `pv_energy_l2` | NUMERIC | PV Inverter [20] | PV toodetud energia faasil L2, kWh |
| `pv_energy_l3` | NUMERIC | PV Inverter [20] | PV toodetud energia faasil L3, kWh |
| `grid_input_power_l1` | NUMERIC | VE.Bus System [276] | Võrgust sisendvõimsus faasil L1, W |
| `grid_input_power_l2` | NUMERIC | VE.Bus System [276] | Võrgust sisendvõimsus faasil L2, W |
| `grid_input_power_l3` | NUMERIC | VE.Bus System [276] | Võrgust sisendvõimsus faasil L3, W |
| `grid_input_voltage_l1` | NUMERIC | VE.Bus System [276] | Võrgu pinge faasil L1, V |
| `grid_input_voltage_l2` | NUMERIC | VE.Bus System [276] | Võrgu pinge faasil L2, V |
| `grid_input_voltage_l3` | NUMERIC | VE.Bus System [276] | Võrgu pinge faasil L3, V |
| `grid_input_current_l1` | NUMERIC | VE.Bus System [276] | Võrgu vool faasil L1, A |
| `grid_input_current_l2` | NUMERIC | VE.Bus System [276] | Võrgu vool faasil L2, A |
| `grid_input_current_l3` | NUMERIC | VE.Bus System [276] | Võrgu vool faasil L3, A |
| `grid_input_frequency_l1` | NUMERIC | VE.Bus System [276] | Võrgu sagedus faasil L1, Hz |
| `grid_input_frequency_l2` | NUMERIC | VE.Bus System [276] | Võrgu sagedus faasil L2, Hz |
| `grid_input_frequency_l3` | NUMERIC | VE.Bus System [276] | Võrgu sagedus faasil L3, Hz |
| `grid_alarm` | TEXT | System overview [276] | Võrgu alarmi olek tekstina |

---

## Silver: `stg_vrm_log_hourly`

**Fail:** `dbt/models/silver/stg_vrm_log_hourly.sql`  
**Materjalisatsioon:** view  
**Allikas:** `bronze.vrm_log_raw`

Otsene veergude ümbernimetamine ühikusufiksitega. Neli faaside summat arvutatakse:

| Tuletatud veerg | Valem | NULL kui |
|---|---|---|
| `ac_consumption_total_w` | `L1 + L2 + L3` | L1 on NULL |
| `pv_power_total_w` | `L1 + L2 + L3` | L1 on NULL |
| `pv_energy_total_kwh` | `L1 + L2 + L3` | L1 on NULL |
| `grid_input_power_total_w` | `L1 + L2 + L3` | L1 on NULL |

Agregatsiooni ei toimu — API tagastab andmed juba tunnipõhisena.

---

## Gold: `fct_vrm_log_hourly`

**Fail:** `dbt/models/gold/fct_vrm_log_hourly.sql`  
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='vrm_log_key'`)  
**Allikas:** `stg_vrm_log_hourly` LEFT JOIN `vrm_sites`

Kimball faktitabel. Lisab asendvõtmed ja nimetab `recorded_at` ümber `timestamp_utc`-ks.
KPI-sid siin ei ole — need kuuluvad martti.

| Võtmeveerg | Genereeritakse |
|---|---|
| `vrm_log_key` | `site_id` + `timestamp_utc` |
| `time_key` | `timestamp_utc` |
| `location_key` | `latitude` + `longitude` tabelist `vrm_sites` |

Kõik silver-kihi mõõtmisveerud edastatakse muutmata kujul.

### Faktide tüübid (Kimball)

| Tüüp | Veerud | Lubatud agregatsioon |
|---|---|---|
| **Täielikult aditiivsed** | kWh energiavood (`pv_energy_*`, `battery_*_kwh`) | SUM üle aja ja objektide |
| **Pooladitiivsed** | W, %, V, °C, A, Hz | AVG üle aja — mitte SUM |
| **Mitteaditiivsed** | `grid_alarm` (tekst) | loendamine, mitte agregatsioon |

---

## Gold: `mart_vrm_log_hourly`

**Fail:** `dbt/models/gold/mart_vrm_log_hourly.sql`  
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='vrm_log_key'`)  
**Allikad:** `fct_vrm_log_hourly` LEFT JOIN `fct_meteo_hourly` + `dim_time` + `vrm_sites`

Kõik faktitabeli veerud edastatakse. Mart lisab:

### Ilmaandmed (`fct_meteo_hourly`, NULL kui meteo pole saadaval)

| Veerg | Ühik | Kirjeldus |
|---|---|---|
| `shortwave_radiation_wm2` | W/m² | Globaalne horisontaalne kiirgus |
| `direct_radiation_wm2` | W/m² | Otsekiirgus |
| `sunshine_duration_s` | s | Päikesepaiste kestus tunnis |
| `cloud_cover_pct` | % | Pilvisus |

### Kalendrimärgendid (`dim_time`, NULL kui tund pole veel dim_time-s)

| Veerg | Kirjeldus |
|---|---|
| `season` | `winter` / `spring` / `summer` / `autumn` |
| `is_daytime` | True vahemikus 06:00–20:00 UTC |

### KPI-d

| Veerg | Valem | NULL kui |
|---|---|---|
| `performance_ratio` | `pv_energy_total_kwh / (shortwave_radiation_wm2 / 1000 × capacity_kw)` | kiirgus ≤ 50 W/m² või võimsus teadmata |
| `specific_yield_kwh_per_kwp` | `pv_energy_total_kwh / capacity_kw` | võimsus teadmata |
| `battery_net_kwh` | `battery_charged_kwh − battery_discharged_kwh` | kumbki veerg NULL |
| `grid_import_kwh_estimate` | `grid_input_power_total_w / 1000` | võrguvõimsus NULL. Tähistatud `_estimate`: eeldab püsivat võimsust tunni vältel |
| `pv_cover_ratio` | `pv_energy_total_kwh / (pv_energy_total_kwh + grid_import_kwh_estimate)` | kumbki sisend NULL. Ligikaudne — ei kasuta GX seadme sisemist energiavoogude arvestust |

`pv_cover_ratio` on varustuspoole proksi omavarustusele. See erineb
`mart_solar_performance_hourly` mudeli `self_sufficiency_rate`-st, mis kasutab
GX seadme sisemist energiavoogude arvestust (`pv_to_consumers_kwh` jne), mis on
saadaval ainult `/diagnostics` lõpp-punktist.

---

## DAG: `vrm_log_ingest`

**Fail:** `airflow/dags/dag_vrm_log_ingest.py`  
**Ajakava:** `@hourly`  
**Ülesanded:** `validate_config >> ingest_vrm_log`

dbt transformatsioonid käivitab eraldi `pipeline_smoke_test` DAG,
mis käivitab `dbt run` kõigi mudelite peale.

### Vaikimisi režiim (tunnipõhine)

Iga planeeritud käivituse puhul arvutab skript ajavahemiku automaatselt:

```
algus = floor(praegune aeg tunnini) − 1 tund
lõpp  = floor(praegune aeg tunnini)
```

### Backfill-i režiim

Käivita DAG käsitsi parameetritega:

| Parameeter | Formaat | Näide |
|---|---|---|
| `start_time` | `YYYY-MM-DDTHH:MM:SS` (UTC) | `2025-01-01T00:00:00` |
| `end_time` | `YYYY-MM-DDTHH:MM:SS` (UTC) | `2026-01-01T00:00:00` |

Mõlemad tühjaks jättes kasutatakse vaikimisi viimase tunni akent.

Parameetrid edastatakse skriptile keskkonnamuutujatena `VRM_LOG_START` / `VRM_LOG_END`.

### DAG-ide võrdlus

| DAG | Käivitus | Mida teeb |
|---|---|---|
| `vrm_log_ingest` | `@hourly` | Laadib log-CSV → `bronze.vrm_log_raw` |
| `pipeline_smoke_test` | `@hourly` | VRM diagnostics + meteo ingest → dbt → prognoos |
| `vrm_backfill` | Käsitsi | Ajaloolised `/stats` andmed → `bronze.vrm_stats_raw` |

---

## Konfigureerimine

| Muutuja | Kirjeldus | Kasutatav |
|---|---|---|
| `VRM_API_TOKEN` | VRM API ligipääsuvõti | ingest |
| `VRM_SITE_ID` | Paigaldise ID (täisarv, saadetakse `idSite` parameetrina) | ingest |
| `SUPABASE_DB_HOST` | Andmebaasi host | ingest |
| `SUPABASE_DB_PORT` | Andmebaasi port | ingest |
| `SUPABASE_DB_NAME` | Andmebaasi nimi | ingest |
| `SUPABASE_DB_USER` | Andmebaasi kasutaja | ingest |
| `SUPABASE_DB_PASSWORD` | Andmebaasi parool | ingest |
| `VRM_LOG_START` | Algusaja ülekiri (ISO 8601 UTC) | ainult backfill |
| `VRM_LOG_END` | Lõpuaja ülekiri (ISO 8601 UTC) | ainult backfill |

---

## Backfill-i käivitamine

1. Ava Airflow UI → DAG `vrm_log_ingest`
2. **Lülita DAG sisse** kui see on peatatud (uued DAG-id luuakse vaikimisi peatatult)
3. Klõpsa **Trigger DAG w/ config**
4. Täida `start_time` ja `end_time` (UTC ISO 8601, nt `2025-06-01T00:00:00`)
5. Käivita

Järgmine `pipeline_smoke_test` käivitus haarab uued bronze-read automaatselt
ja käivitab dbt transformatsioonid. Koheseks transformeerimiseks ilma ootamata:

```bash
dbt run --project-dir dbt --profiles-dir dbt \
  --select stg_vrm_log_hourly fct_vrm_log_hourly mart_vrm_log_hourly
```

---

## Testimine

```bash
pytest tests/ingest/test_vrm_log_ingest.py -v               # 68 ühiktesti
pytest tests/airflow/test_vrm_log_ingest_dag_contract.py -v # 9 kontrakttesti
```

| Testiklass | Mida testitakse |
|---|---|
| `TestDownloadReport` | URL, autentimispäis, päringuparameetrid, 429 taandumine, 202 viga, JSON kaitse |
| `TestParseHeaderTimezone` | Nimeline ajavöönd, UTC nihe varuvariandina, tühi string |
| `TestColumnRuns` | Plokisiltide grupeerimine, tühikute eemaldamine, äärejuhud |
| `TestCoerceValue` | int/float/string/None tüübimuundus |
| `TestParseSampleTime` | Kohalik → UTC teisendus, mitteloetavad sisendid |
| `TestBuildMetrics` | Pesastatud dict-i koostamine, tühiväärtuste väljajätmine |
| `TestExtractFlatValues` | FLAT_COLUMN_MAP järjestus, `grid_alarm` tekstina säilitamine |
| `TestIngestCsvText` | <4 rida tõstab vea, ridade arv, dry run, tühjade ridade vahelejätmine, commit, UTC ajatemplid |
| `TestUpsertLogRow` | INSERT SQL, ON CONFLICT, parameetrite sidumine, JSON serialiseerimine, commit |
| `TestBuildIngestConfig` | Puuduvad muutujad tõstavad vea, vaikimisi ajaaken, muutujate ülekiri, site_id täisarvuks |
| `TestMain` | Välumiskoodid, ühenduse sulgemine õnnestumisel ja ebaõnnestumisel |

---

## Seotud failid

| Fail | Kirjeldus |
|---|---|
| `sql/006_bronze_vrm_log_raw.sql` | Bronze tabeli migratsioon |
| `src/ingest/vrm_log_ingest.py` | CSV allalaadimine → parsimine → bronze upsert |
| `airflow/dags/dag_vrm_log_ingest.py` | Tunnipõhine DAG backfill-i parameetritega |
| `dbt/models/silver/stg_vrm_log_hourly.sql` | Silver view — veergude kaardistamine |
| `dbt/models/gold/fct_vrm_log_hourly.sql` | Gold faktitabel |
| `dbt/models/gold/mart_vrm_log_hourly.sql` | Gold mart — ilmaandmed + KPI-d |
| `dbt/models/gold/dim_time.sql` | Uuendatud — lisatud VRM log tunniread |
| `dbt/models/silver/schema.yml` | dbt testid `stg_vrm_log_hourly` jaoks |
| `dbt/models/gold/schema.yml` | dbt testid faktitabeli ja mardi jaoks |
| `tests/ingest/test_vrm_log_ingest.py` | Ingest-skripti ühiktestid |
| `tests/airflow/test_vrm_log_ingest_dag_contract.py` | DAG kontrakttestid |
