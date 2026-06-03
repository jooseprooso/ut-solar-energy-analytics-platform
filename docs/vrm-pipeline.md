# VRM diagnostics pipeline

Käesolev dokument kirjeldab VRM `/diagnostics` andmevoogu — API-st kuni
hetkeseisuvaateni välja — ning selgitab kõiki olulisi disainiotsuseid.

Ajaloolise analüüsi jaoks on eraldi pipeline: vt `docs/vrm-log-pipeline.md`.

---

## Ülevaade

```
Victron VRM API
      │
      └─ /diagnostics (reaalaeg, iga 15 min)
              │
              ▼
      bronze.vrm_raw          üks rida (site_id, fetched_hour) kohta, JSONB payload
              │
              ▼  JSONB pivot + meteo LEFT JOIN (inline)
      mart_solar_performance_hourly (view)
              │
              └─ Grafana hetkeseisudasboard
```

---

## Eesmärk ja piirid

`/diagnostics` lõpp-punkt tagastab **hetkeseisu** — ühe päringu tulemusena ~343
mõõtmist sellel ajahetkel. See teeb sellest ideaalse allika reaalajas
dashboardi jaoks.

**Mida see pipeline teeb:**
- Kogub GX seadme hetkeseisu iga 15 minuti tagant
- Arvutab KPI-d (`self_sufficiency_rate`, `self_consumption_rate`, `performance_ratio`)
- Väljastab ühe rea saidi kohta (`mart_solar_performance_hourly` view)

**Mida see pipeline ei tee:**
- Ei säilita ajalugu — view näitab alati ainult viimast rida
- Ei toeta backfill-i — `/diagnostics` ei võta kuupäevavahemikku
- Ajaloolise analüüsi jaoks kasuta `mart_vrm_log_hourly` (vt vrm-log-pipeline.md)

---

## ELT põhimõte

| Etapp | Vastutav komponent | Mis toimub |
|---|---|---|
| **Extract** | `vrm_ingest.py` | Pärib `/diagnostics` lõpp-punktist hetkeseisu |
| **Load** | Python + Supabase | Kirjutab JSONB payload muutmata kujul bronzesse |
| **Transform** | dbt (`mart_solar_performance_hourly`) | JSONB pivot + KPI arvutus andmelaos |

Bronze kiht salvestab kogu API vastuse (`payload` JSONB veerg) muutmata kujul.
Upsert `ON CONFLICT (site_id, fetched_hour, endpoint) DO UPDATE` tagab, et
iga tunni kohta on alati viimane lugemine.

---

## VRM API lõpp-punkt

```
GET https://vrmapi.victronenergy.com/v2/installations/{site_id}/diagnostics
```

**Autentimine:** `x-authorization: Token <VRM_API_TOKEN>`

**Vastuse struktuur:** `{"records": [{"code": "bs", "rawValue": 92.0, ...}, ...]}`
— ~343 kirjet, üks kood = üks mõõtmise hetkeväärtus.

---

## Bronze: `bronze.vrm_raw`

**Migratsioon:** `sql/004_bronze_vrm_raw.sql`  
**Upsert:** `ON CONFLICT (site_id, fetched_hour, endpoint) DO UPDATE`  
— sama tunni retry kirjutab eelmise üle, duplikaate ei teki.

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

`fetched_hour` arvutatakse Pythonis (minutid ja sekundid nullitakse).
`endpoint` veerg on alati `'diagnostics'`.

---

## Gold: `mart_solar_performance_hourly`

**Fail:** `dbt/models/gold/mart_solar_performance_hourly.sql`  
**Materjalisatsioon:** view  
**Allikad:** `bronze.vrm_raw` (viimane rida) LEFT JOIN `fct_meteo_hourly` + `vrm_sites`

View teeb kõik ühes kohas:
1. Valib viimase `fetched_hour` per `site_id` bronzest
2. Lahti pakkimine: `jsonb_array_elements(payload -> 'records')` → pivot `MAX(CASE WHEN code=...)`
3. Liidab meteo- ja saidiandmed
4. Arvutab KPI-d

Kuna tegemist on view'ga (mitte inkrementaalse tabeliga), on see alati ohutu
uuesti ehitada — `dbt run --full-refresh` ei kaota midagi.

### Väljuvad veerud

| Veerg | Tüüp | Kirjeldus |
|---|---|---|
| `site_id`, `timestamp_utc` | — | Identifikaatorid |
| `hour_of_day`, `date_day`, `season`, `is_daytime` | — | Kalendrimärgendid (arvutatakse inline) |
| `pv_total_w`, `pv_l1/l2/l3_w` | W | PV hetkvõimsus faaside kaupa |
| `load_total_w` | W | Kogu tarbimine |
| `pv_to_battery_kwh`, `pv_to_consumers_kwh` | kWh | GX energiavood |
| `grid_to_battery_kwh`, `grid_to_consumers_kwh` | kWh | GX energiavood |
| `battery_to_consumers_kwh` | kWh | GX energiavood |
| `battery_soc_pct`, `battery_power_w`, `battery_voltage_v` | % / W / V | Aku seisund |
| `battery_temp_c`, `battery_soh_pct` | °C / % | Aku tervis |
| `battery_state`, `system_state`, `grid_alarm`, `pvinverter_status` | text | Olekutekstid |
| `pvinverter_energy_delta_kwh` | kWh | KPI-de nimetaja |
| `shortwave_radiation_wm2`, `cloud_cover_pct` | W/m² / % | Ilmaandmed |
| `self_sufficiency_rate` | 0–1 | Omavarustuse määr |
| `self_consumption_rate` | 0–1 | Omakasutusmäär |
| `performance_ratio` | ratio | Tootlikkuse suhtarv |

### KPI valemid

| KPI | Valem | NULL kui |
|---|---|---|
| `self_sufficiency_rate` | `(pv_to_consumers + battery_to_consumers) / kogukulutus` | tarbimine puudub |
| `self_consumption_rate` | `(pv_to_consumers + pv_to_battery) / pvinverter_energy_delta` | PV toodang puudub |
| `performance_ratio` | `pvinverter_energy_delta / (kiirgus / 1000 × capacity_kw)` | kiirgus ≤ 0 või võimsus teadmata |

Need KPI-d on ainulaadsed selle pipeline jaoks — need sõltuvad GX seadme
sisemisest energiavoogude arvestusest (`Pb`, `Pc`, `Bc` jne koodid), mida
`/download` lõpp-punkt ei tagasta.

---

## DAG: `vrm_ingest`

**Fail:** `airflow/dags/dag_vrm_ingest.py`  
**Ajakava:** `@hourly`  
**Ülesanded:** üks — `ingest_vrm` (PythonOperator → `vrm_ingest.main()`)

dbt transformatsioon käivitub automaatselt `pipeline_smoke_test` DAG kaudu.

---

## Konfigureerimine

| Muutuja | Kirjeldus |
|---|---|
| `VRM_API_TOKEN` | VRM API ligipääsuvõti |
| `VRM_SITE_ID` | Paigaldise ID |
| `SUPABASE_DB_*` | Andmebaasi ühendusparameetrid |

Kui `VRM_API_TOKEN` või `VRM_SITE_ID` puudub, lõpetab moodul töö koodiga `0`
(ohutu käitumine lokaalses arenduskeskkonnas).

---

## Testimine

```bash
pytest tests/ingest/test_vrm_ingest.py -v
```

| Testiklass | Mida testitakse |
|---|---|
| `TestFetchDiagnostics` | URL, token päises, JSON vastus, HTTP vead, timeout |
| `TestUpsert` | INSERT bronzesse, ON CONFLICT, parameetrite järjekord, commit |
| `TestMain` | Puuduvad muutujad → skip, edukas jooksmine, ühenduse sulgemine |

---

## Seotud failid

| Fail | Kirjeldus |
|---|---|
| `sql/004_bronze_vrm_raw.sql` | Bronze tabeli migratsioon |
| `src/ingest/vrm_ingest.py` | Diagnostics ingest-skript |
| `airflow/dags/dag_vrm_ingest.py` | 15-minutiline DAG |
| `dbt/models/gold/mart_solar_performance_hourly.sql` | Hetkeseisumart (view) |
| `dbt/models/gold/schema.yml` | dbt testid mardi jaoks |
| `tests/ingest/test_vrm_ingest.py` | Ühiktestid |
