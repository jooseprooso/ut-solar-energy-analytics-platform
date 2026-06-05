# Meteo pipeline

Käesolev dokument kirjeldab Open-Meteo ilmaandmete voogu — API-st kuni
analüütikamardin välja — ning selgitab kõiki olulisi disainiotsuseid.

---

## Ülevaade

```
Open-Meteo API
      │
      ├─ /forecast (reaalaeg, 24h minevik + 24h prognoos)
      │
      └─ /archive (ajalooline, kuni 6 kuud tagasi)
              │
              ▼
      bronze.meteo_raw          üks rida (timestamp_utc, lat, lon, variable_name) kohta
              │
              ▼  pivot long → wide
      stg_meteo_hourly (silver view)
              │
              ▼  asendvõtmed + dimensioon-FK-d
      fct_meteo_hourly (gold inkrementaalne)
              │
              ▼  LEFT JOIN dim_time
      mart_meteo_hourly (gold mart)
              │
              ├── Grafana dashboard
              └── LEFT JOIN → mart_vrm_log_hourly (ilm + PV ühes reas)
```

---

## Eesmärk ja piirid

**Mida see pipeline teeb:**
- Kogub tunnipõhised ilmaandmed (kiirgus, pilvisus, päikesepaiste kestus)
- Salvestab toored andmed pika formaadi (long format) kujul bronzesse
- Transformeerib dbt-ga analüüsivalmis martideks
- Toetab nii inkrementaalset laadimist (tunnipõhine) kui ka ajaloolist backfill-i

**Mida see pipeline ei tee:**
- Ei salvesta prognoosi ajalugu eraldi (prognoos ja minevik lähevad samasse tabelisse)
- Ei teosta andmekvaliteedi kontrolli ingesti ajal — see toimub dbt testidena

---

## ELT põhimõte

| Etapp | Vastutav komponent | Mis toimub |
|---|---|---|
| **Extract** | `meteo_api_client.py` | Pärib Open-Meteo API-st tunniandmed |
| **Load** | `meteo_db_writer.py` | Kirjutab toored read bronzesse UPSERT-iga |
| **Transform** | dbt (`stg_meteo_hourly` → `fct_meteo_hourly` → `mart_meteo_hourly`) | Pivot, asendvõtmed ja KPI-d andmelaos |

Bronze kiht salvestab iga mõõtmise eraldi reana (long format). Kui veerge on
vaja lisada või transformatsiooni muuta, saab ajaloolised andmed ümber
transformeerida ilma API-st uuesti laadimata.

---

## Open-Meteo API lõpp-punkt

### Inkrementaalne (tunnipõhine)

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude=58.2538
    &longitude=22.4922
    &hourly=sunshine_duration,shortwave_radiation,direct_radiation,cloud_cover
    &timezone=UTC
    &past_hours=24
    &forecast_hours=24
```

### Ajalooline (backfill)

```
GET https://archive-api.open-meteo.com/v1/archive
    ?latitude=58.2538
    &longitude=22.4922
    &start_date=2025-12-01
    &end_date=2025-12-31
    &hourly=sunshine_duration,shortwave_radiation,direct_radiation,cloud_cover
    &timezone=UTC
```

**Autentimist ei nõuta** — Open-Meteo API on avalik.

**Vastuse struktuur:**
```json
{
  "hourly_units": {"sunshine_duration": "s", "shortwave_radiation": "W/m²", ...},
  "hourly": {
    "time": ["2026-01-01T00:00", "2026-01-01T01:00", ...],
    "sunshine_duration": [0.0, 0.0, ...],
    "shortwave_radiation": [0.0, 12.5, ...]
  }
}
```

---

## Mõõdetavad muutujad

| Muutuja | Ühik | Kirjeldus |
|---|---|---|
| `sunshine_duration` | s | Päikesepaiste kestus tunnis |
| `shortwave_radiation` | W/m² | Globaalne horisontaalne kiirgus |
| `direct_radiation` | W/m² | Otsekiirgus |
| `cloud_cover` | % | Pilvisus |

---

## Bronze: `bronze.meteo_raw`

**Migratsioon:** `sql/003_create_meteo_raw.sql`
**Graanulaarsus:** üks rida `(timestamp_utc, latitude, longitude, variable_name)` kohta.
**UPSERT strateegia:** `ON CONFLICT (timestamp_utc, latitude, longitude, variable_name) DO UPDATE` — korduvkäivitused on idempotentsed.

### Veerud

| Veerg | Tüüp | Kirjeldus |
|---|---|---|
| `id` | BIGSERIAL | Primaarvõti |
| `timestamp_utc` | TIMESTAMPTZ | Mõõtmise ajahetk UTC-s |
| `latitude` | DOUBLE PRECISION | Laiuskraad |
| `longitude` | DOUBLE PRECISION | Pikkuskraad |
| `variable_name` | TEXT | Muutuja nimi (`sunshine_duration`, `shortwave_radiation` jne) |
| `value` | DOUBLE PRECISION | Mõõtmisväärtus (võib olla NULL) |
| `unit` | TEXT | Ühik (`s`, `W/m²`, `%`) |
| `ingested_at` | TIMESTAMPTZ | Kirjutamise hetk (uueneb igal upsert-il) |

Long format tähendab, et iga tunniajahetk genereerib 4 rida (üks muutuja kohta).
See tagab, et uue muutuja lisamine ei nõua skeemimuudatust.

---

## Silver: `stg_meteo_hourly`

**Fail:** `dbt/models/silver/stg_meteo_hourly.sql`
**Materjalisatsioon:** view
**Allikas:** `bronze.meteo_raw`

Pivot long → wide: grupeerimine `(timestamp_utc, latitude, longitude)` järgi,
iga muutuja saab oma veeru:

| Väljundveerg | Allikas |
|---|---|
| `meteo_hourly_key` | Asendvõti (`timestamp_utc` + `latitude` + `longitude`) |
| `sunshine_duration_s` | `variable_name = 'sunshine_duration'` |
| `shortwave_radiation_wm2` | `variable_name = 'shortwave_radiation'` |
| `direct_radiation_wm2` | `variable_name = 'direct_radiation'` |
| `cloud_cover_pct` | `variable_name = 'cloud_cover'` |
| `ingested_at` | `max(ingested_at)` grupis |

NULL väärtustega read filtreeritakse välja enne pivoteerimist.

---

## Gold: `fct_meteo_hourly`

**Fail:** `dbt/models/gold/fct_meteo_hourly.sql`
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='meteo_hourly_key'`)
**Allikas:** `stg_meteo_hourly`

Kimball faktitabel. Lisab dimensioon-FK-d:

| Võtmeveerg | Genereeritakse |
|---|---|
| `meteo_hourly_key` | `timestamp_utc` + `latitude` + `longitude` |
| `time_key` | `timestamp_utc` |
| `location_key` | `latitude` + `longitude` |

### Inkrementaalne loogika

```sql
{% if is_incremental() %}
where ingested_at > (select max(ingested_at) - interval '1 hour' from {{ this }})
{% endif %}
```

Lookback-aken (1 tund enne max `ingested_at`) tagab, et hilinevatega andmed ei lähe kaotsi.

---

## Gold: `mart_meteo_hourly`

**Fail:** `dbt/models/gold/mart_meteo_hourly.sql`
**Materjalisatsioon:** inkrementaalne (`delete+insert`, `unique_key='meteo_hourly_key'`)
**Allikad:** `fct_meteo_hourly` INNER JOIN `dim_time`

Mart lisab kalendrimärgendid:

| Veerg | Allikas | Kirjeldus |
|---|---|---|
| `season` | `dim_time` | `winter` / `spring` / `summer` / `autumn` |
| `is_daytime` | `dim_time` | True vahemikus 06:00–20:00 UTC |

Kõik faktitabeli mõõtmisveerud edastatakse muutmata kujul.

---

## DAG: `meteo_ingest`

**Fail:** `airflow/dags/meteo_ingest_dag.py`
**Ajakava:** `@hourly`
**Ülesanded:** `validate_config >> ingest_meteo`

| Parameeter | Väärtus |
|---|---|
| `retries` | 2 |
| `retry_delay` | 5 min |
| `max_active_runs` | 1 |
| `catchup` | False |

dbt transformatsioonid käivitab eraldi `pipeline_smoke_test` DAG.

---

## DAG: `meteo_backfill`

**Fail:** `airflow/dags/meteo_backfill_dag.py`
**Ajakava:** `None` (ainult käsitsi käivitus)
**Ülesanded:** `validate_config >> run_backfill`

Backfill-i saab seadistada keskkonnamuutujatega:

| Muutuja | Vaikimisi | Kirjeldus |
|---|---|---|
| `METEO_BACKFILL_START` | 182 päeva tagasi | Alguskuupäev (ISO 8601) |
| `METEO_BACKFILL_END` | eile | Lõppkuupäev (ISO 8601) |

### Tükeldamine (chunking)

Pikad kuupäevavahemikud tükeldatakse 30-päevasteks osadeks:
- 182 päeva → 7 tükki × ≤30 päeva
- Iga tükk eraldi API päring
- 5 kordust eksponentsiaalse taandumisega (backoff 1.0 s)
- Kordamine ainult HTTP 502, 503, 504 korral

### Idempotentsus

Backfill kasutab sama UPSERT-i lõpp-punkti nagu inkrementaalne ingest.
Korduvkäivitus ei tekita duplikaate — sama päring sama tulemusega.
Olekumasinat ega vesimärgitabelit (watermark) pole vaja.

---

## Puhas kood ja disainimustrid

### Protocol-põhine sõltuvuste süstimine

```python
class HttpClient(Protocol):
    def get(self, url: str, params: dict[str, Any]) -> Any: ...

class DbConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
```

Testides süstitakse mock-objekte; toodangus kasutatakse `requests.Session`
ja `psycopg2.connect()`. Moodulid ei sõltu konkreetsetest teekidest.

### Muutumatu konfiguratsioon (frozen dataclass)

```python
@dataclass(frozen=True)
class MeteoApiConfig:
    latitude: float
    longitude: float
    timezone: str
    past_hours: int = 24
    forecast_hours: int = 24
```

### SQL-süsti kaitse

Tabelinimed valideeritakse regex-iga enne kasutamist:
```python
TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
```
Rea andmed edastatakse alati parameetritena (`executemany`), mitte stringi liitmisega.

### Ühe vastutuse printsiip (SRP)

| Moodul | Vastutus |
|---|---|
| `meteo_api_client.py` | Ainult HTTP loogika + kordamine |
| `meteo_transform.py` | Ainult JSON → tabeliread (puhas funktsioon) |
| `meteo_db_writer.py` | Ainult SQL + ühenduse haldus |
| `meteo_ingest.py` | Orkestreerib: ei sisalda äriloogikat |
| `meteo_backfill.py` | Tükeldamine + tsükli juhtimine |

---

## Konfigureerimine

| Muutuja | Kirjeldus | Kasutatav |
|---|---|---|
| `METEO_LAT` | Laiuskraad | ingest + backfill |
| `METEO_LON` | Pikkuskraad | ingest + backfill |
| `METEO_TIMEZONE` | Ajavöönd (vaikimisi `UTC`) | ainult ingest |
| `SUPABASE_DB_HOST` | Andmebaasi host | ingest + backfill |
| `SUPABASE_DB_PORT` | Andmebaasi port | ingest + backfill |
| `SUPABASE_DB_NAME` | Andmebaasi nimi | ingest + backfill |
| `SUPABASE_DB_USER` | Andmebaasi kasutaja | ingest + backfill |
| `SUPABASE_DB_PASSWORD` | Andmebaasi parool | ingest + backfill |
| `METEO_BACKFILL_START` | Alguskuupäev ülekiri (ISO 8601) | ainult backfill |
| `METEO_BACKFILL_END` | Lõppkuupäev ülekiri (ISO 8601) | ainult backfill |
| `BRONZE_TABLE_PREFIX` | Tabeli eesliide (nt `smoke_test_`) | test |

---

## Backfill-i käivitamine

1. Ava Airflow UI → DAG `meteo_backfill`
2. **Lülita DAG sisse** kui see on peatatud
3. Klõpsa **Trigger DAG w/ config**
4. Soovi korral seadista `METEO_BACKFILL_START` ja `METEO_BACKFILL_END` keskkonnamuutujad enne käivitust
5. Käivita

Järgmine `pipeline_smoke_test` käivitus haarab uued bronze-read automaatselt
ja käivitab dbt transformatsioonid. Koheseks transformeerimiseks:

```bash
dbt run --project-dir dbt --profiles-dir dbt \
  --select stg_meteo_hourly fct_meteo_hourly mart_meteo_hourly
```

---

## Testimine

```bash
pytest tests/ingest/test_meteo_api_client.py -v
pytest tests/ingest/test_meteo_transform.py -v
pytest tests/ingest/test_meteo_db_writer.py -v
pytest tests/ingest/test_meteo_ingest.py -v
pytest tests/ingest/test_meteo_backfill.py -v
pytest tests/airflow/test_meteo_ingest_dag_contract.py -v
```

| Testiklass / fail | Mida testitakse |
|---|---|
| `test_meteo_api_client.py` | URL, parameetrid, HTTP kordamine, mock HttpClient |
| `test_meteo_transform.py` | JSON parsimine, NULL väärtused, tühi vastus, puuduv `hourly` võti |
| `test_meteo_db_writer.py` | UPSERT SQL, tabelinime valideerimine, commit, `CREATE TABLE IF NOT EXISTS` |
| `test_meteo_ingest.py` | Puuduvad muutujad → kood 1, API viga → kood 1, edukas jooksmine → kood 0, ühenduse sulgemine |
| `test_meteo_backfill.py` | Kuupäevade tükeldamine, konfiguratsiooni ehitamine, `run_backfill` tsükli loogika |
| `test_meteo_ingest_dag_contract.py` | DAG ID, ajakava, ülesannete ID-d, sõltuvusjärjekord |

### Testimise põhimõtted

- **Piiri mockimine:** HTTP ja DB süstitakse protokolli kaudu — äriloogika testitakse päris objektidega
- **Kirjeldavad nimed:** `test_returns_empty_list_when_api_unavailable` — testnimi on spetsifikatsioon
- **Äärejuhtude katmine:** NULL, tühi vastus, puuduv võti, timeout
- **DAG kontrakttestid:** lähtekoodi assertioonid — kaitsevad ajakava ja sõltuvuste muutmise eest

---

## Seotud failid

| Fail | Kirjeldus |
|---|---|
| `sql/003_create_meteo_raw.sql` | Bronze tabeli migratsioon |
| `src/ingest/meteo_api_client.py` | Open-Meteo API klient (Protocol + retry) |
| `src/ingest/meteo_transform.py` | JSON → tabeliread (puhas funktsioon) |
| `src/ingest/meteo_db_writer.py` | PostgreSQL UPSERT + ühenduse tehase |
| `src/ingest/meteo_ingest.py` | Inkrementaalne ingest-skript |
| `src/ingest/meteo_backfill.py` | Ajalooline backfill (tükeldatud) |
| `airflow/dags/meteo_ingest_dag.py` | Tunnipõhine DAG |
| `airflow/dags/meteo_backfill_dag.py` | Käsitsi backfill DAG |
| `dbt/models/silver/stg_meteo_hourly.sql` | Silver view — pivot long → wide |
| `dbt/models/gold/fct_meteo_hourly.sql` | Gold faktitabel (inkrementaalne) |
| `dbt/models/gold/mart_meteo_hourly.sql` | Gold mart — kalendrimärgendid |
| `dbt/models/gold/dim_time.sql` | Ajadimensioon |
| `dbt/models/gold/dim_location.sql` | Asukohta dimensioon |
| `tests/ingest/test_meteo_api_client.py` | API kliendi ühiktestid |
| `tests/ingest/test_meteo_transform.py` | Transformatsiooni ühiktestid |
| `tests/ingest/test_meteo_db_writer.py` | DB kirjutaja ühiktestid |
| `tests/ingest/test_meteo_ingest.py` | Peaskripti ühiktestid |
| `tests/ingest/test_meteo_backfill.py` | Backfill-i ühiktestid |
| `tests/airflow/test_meteo_ingest_dag_contract.py` | DAG kontrakttestid |
