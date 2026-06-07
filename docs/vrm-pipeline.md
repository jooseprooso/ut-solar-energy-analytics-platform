# VRM diagnostics pipeline

Käesolev dokument kirjeldab VRM `/diagnostics` andmevoogu — API-st kuni
hetkeseisuvaateni — ning selgitab kõiki olulisi disainiotsuseid.

> **Ajaloolise analüüsi pipeline** asub eraldi dokumendis: [`docs/vrm-log-pipeline.md`](vrm-log-pipeline.md)

---

## Ülevaade

```
┌─────────────────────────┐
│    Victron VRM API      │
│  /diagnostics endpoint  │
│  (hetkeseisu snapshot)  │
└────────────┬────────────┘
             │  HTTP GET · iga tund
             ▼
┌─────────────────────────┐
│    bronze.vrm_raw       │  üks rida (site_id, fetched_hour) kohta
│    JSONB payload        │  upsert — retry ei loo duplikaate
└────────────┬────────────┘
             │  JSONB pivot + meteo LEFT JOIN
             ▼
┌─────────────────────────┐
│  gold.mart_solar_       │  vaade (view) — alati värske
│  performance_hourly     │  üks rida saidi kohta
└────────────┬────────────┘
             │
             ▼
      Grafana dashboard
```

---

## Eesmärk ja piirid

`/diagnostics` lõpp-punkt tagastab **hetkeseisu** — ühe päringu tulemusena
~343 mõõtmist sellel ajahetkel. See teeb sellest ideaalse allika
reaalajas dashboardi jaoks.

### Mida see pipeline teeb

- Küsib GX seadme hetkeseisu **iga tund**
- Salvestab töötlemata API vastuse bronze kihti muutmata kujul
- Arvutab KPI-d (`self_sufficiency_rate`, `self_consumption_rate`, `performance_ratio`)
- Väljastab **ühe rea saidi kohta** läbi `mart_solar_performance_hourly` vaate

### Mida see pipeline ei tee

- **Ei säilita ajalugu** — vaade näitab alati ainult viimast lugemist saidi kohta
- **Ei toeta backfill-i** — `/diagnostics` ei võta kuupäevavahemikku
- Ajaloolise analüüsi jaoks kasuta `mart_vrm_log_hourly` *(vt vrm-log-pipeline.md)*

---

## ELT põhimõte

| Etapp | Komponent | Toiming |
|:---:|:---|:---|
| **Extract** | `vrm_ingest.py` | Pärib `/diagnostics` lõpp-punktist hetkeseisu |
| **Load** | Python + PostgreSQL | Kirjutab JSONB payload muutmata kujul bronze kihti |
| **Transform** | dbt — `mart_solar_performance_hourly` | JSONB pivot, ilmaandmete liitmine, KPI arvutus |

Bronze kiht salvestab kogu API vastuse (`payload JSONB` veerg) muutmata kujul.
Upsert strateegi `ON CONFLICT (site_id, fetched_hour, endpoint) DO UPDATE` tagab,
et sama tunni retry kirjutab eelmise üle — duplikaate ei teki.

---

## VRM API lõpp-punkt

```
GET https://vrmapi.victronenergy.com/v2/installations/{site_id}/diagnostics
```

| Parameeter | Väärtus |
|:---|:---|
| Autentimine | `x-authorization: Token <VRM_API_TOKEN>` |
| Vastuse formaat | JSON |

**Vastuse struktuur:**

```json
{
  "records": [
    { "code": "bs",  "rawValue": 92.0,  "formattedValue": "92%"   },
    { "code": "bv",  "rawValue": 53.2,  "formattedValue": "53.2V" },
    { "code": "Pb",  "rawValue": 1.43,  "formattedValue": "1.43 kWh" }
  ]
}
```

Iga kirje sisaldab ühe mõõtmise koodi ja hetkväärtuse. Mart kasutab
valitud koodide alamhulka (vt väljuvate veergude tabel allpool).

---

## Bronze: `bronze.vrm_raw`

**Migratsioon:** `sql/004_bronze_vrm_raw.sql`

```sql
CREATE TABLE bronze.vrm_raw (
    id           BIGSERIAL    PRIMARY KEY,
    site_id      TEXT         NOT NULL,
    fetched_at   TIMESTAMPTZ  NOT NULL,  -- täpne pärimise aeg
    fetched_hour TIMESTAMPTZ  NOT NULL,  -- minutid ja sekundid nullitud
    endpoint     TEXT         NOT NULL,  -- alati 'diagnostics'
    payload      JSONB        NOT NULL,
    UNIQUE (site_id, fetched_hour, endpoint)
);
```

`fetched_hour` arvutatakse Pythonis — minutid ja sekundid nullitakse, et
tagada ühtne grupeerimisalus tunni kohta.

---

## Gold: `gold.mart_solar_performance_hourly`

**Fail:** `dbt/models/gold/mart_solar_performance_hourly.sql`  
**Materjalisatsioon:** `view`  
**Allikad:** `bronze.vrm_raw` · `fct_meteo_hourly` · `vrm_sites`

Vaade teostab kogu transformatsiooni ühe SQL-lausega:

1. **Filtreerimine** — valib iga `site_id` kohta viimase `fetched_hour`
2. **Lahtipakkimine** — `jsonb_array_elements(payload -> 'records')` laiendab kirjete massiivi
3. **Pivot** — `MAX(CASE WHEN code = '...' THEN rawValue::numeric END)` iga mõõtmiskoodi kohta
4. **Rikastamine** — LEFT JOIN ilmaandmete ja paigaldise andmetega
5. **KPI arvutus** — tuletatud mõõdikud pivoteeritud väärtustest

> Kuna tegemist on **vaatega** (mitte inkrementaalse tabeliga), on seda
> alati ohutu uuesti ehitada. `dbt run --select mart_solar_performance_hourly`
> ei kaota ühtegi andmerida.

### Väljuvad veerud

| Veerg | Ühik | Kirjeldus |
|:---|:---:|:---|
| `site_id`, `timestamp_utc` | — | Rea identifikaatorid |
| `hour_of_day`, `date_day`, `season`, `is_daytime` | — | Kalendrimärgendid, arvutatakse inline `timestamp_utc`-st |
| `pv_total_w`, `pv_l1/l2/l3_w` | W | PV inverteri väljundvõimsus faaside kaupa |
| `load_total_w` | W | Kogu AC tarbimine |
| `pv_to_battery_kwh`, `pv_to_consumers_kwh` | kWh | GX seadme sisemised energiavood |
| `grid_to_battery_kwh`, `grid_to_consumers_kwh` | kWh | GX seadme sisemised energiavood |
| `battery_to_consumers_kwh` | kWh | GX seadme sisemised energiavood |
| `battery_soc_pct`, `battery_power_w`, `battery_voltage_v` | % / W / V | Aku seisund |
| `battery_temp_c`, `battery_soh_pct` | °C / % | Aku tervis |
| `battery_state`, `system_state`, `grid_alarm`, `pvinverter_status` | text | Olekutekstid |
| `pvinverter_energy_delta_kwh` | kWh | PV toodang tunnis (KPI nimetaja) |
| `shortwave_radiation_wm2`, `cloud_cover_pct` | W/m² / % | Open-Meteo ilmaandmed |
| `self_sufficiency_rate` | 0–1 | Omavarustuse määr |
| `self_consumption_rate` | 0–1 | Omakasutusmäär |
| `performance_ratio` | suhtarv | Tegelik vs teoreetiline toodang kiirguse suhtes |

### KPI valemid

| KPI | Valem | NULL kui |
|:---|:---|:---|
| `self_sufficiency_rate` | `(pv_to_consumers + battery_to_consumers) / kogukulutus` | Tarbimisandmed puuduvad |
| `self_consumption_rate` | `(pv_to_consumers + pv_to_battery) / pvinverter_energy_delta` | PV toodanguandmed puuduvad |
| `performance_ratio` | `pvinverter_energy_delta / (kiirgus / 1000 × capacity_kw)` | Kiirgus ≤ 0 või võimsus teadmata |

> Need KPI-d on **ainulaadsed selle pipeline jaoks** — need sõltuvad GX seadme
> sisemisest energiavoogude arvestusest (koodid `Pb`, `Pc`, `Bc` jne),
> mida `/download` lõpp-punkt ei tagasta.

---

## DAG: `vrm_ingest`

**Fail:** `airflow/dags/dag_vrm_ingest.py`  
**Ajakava:** `@hourly`  
**Ülesanded:** üks — `ingest_vrm` (PythonOperator → `vrm_ingest.main()`)

dbt transformatsioon ei käivitu selle DAG-i osana — gold vaade loeb
bronzest otse igal päringul.

---

## Konfigureerimine

Kõik muutujad on kohustuslikud. Puuduvate muutujate korral lõpetab
ingest-skript töö koodiga `0` — ohutu käitumine lokaalses arenduskeskkonnas.

| Muutuja | Kirjeldus |
|:---|:---|
| `VRM_API_TOKEN` | VRM API autentimistoken |
| `VRM_SITE_ID` | Paigaldise ID |
| `SUPABASE_DB_HOST` | Andmebaasi host |
| `SUPABASE_DB_PORT` | Andmebaasi port |
| `SUPABASE_DB_NAME` | Andmebaasi nimi |
| `SUPABASE_DB_USER` | Andmebaasi kasutaja |
| `SUPABASE_DB_PASSWORD` | Andmebaasi parool |

---

## Testimine

```bash
pytest tests/ingest/test_vrm_ingest.py -v
```

| Testiklass | Mida testitakse |
|:---|:---|
| `TestFetchDiagnostics` | URL, token päises, JSON vastus, HTTP vead, timeout |
| `TestUpsert` | INSERT bronzesse, ON CONFLICT käitumine, parameetrite järjekord, commit |
| `TestMain` | Puuduvad muutujad → ohutu lõpetamine, edukas jooksmine, ühenduse sulgemine |

---

## Seotud failid

| Fail | Kirjeldus |
|:---|:---|
| `sql/004_bronze_vrm_raw.sql` | Bronze tabeli migratsioon |
| `src/ingest/vrm_ingest.py` | Diagnostics ingest-skript |
| `airflow/dags/dag_vrm_ingest.py` | Tunnine Airflow DAG |
| `dbt/models/gold/mart_solar_performance_hourly.sql` | Hetkeseisumart (view) |
| `dbt/models/gold/schema.yml` | dbt veerutestid mardi jaoks |
| `tests/ingest/test_vrm_ingest.py` | Ühiktestid |
