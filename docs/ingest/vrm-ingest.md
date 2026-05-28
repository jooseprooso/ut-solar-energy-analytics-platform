# VRM ingest (`vrm_ingest`)

## Ülevaade

`src/ingest/vrm_ingest.py` toob Victron VRM API-st hetkelised mõõtmised ja salvestab need muutmata kujul Supabase'i bronze kihti. Airflow DAG `vrm_ingest` (`airflow/dags/dag_vrm_ingest.py`) käivitab seda kord tunnis.

```
Victron VRM API
      │
      │  HTTP GET /installations/{site_id}/diagnostics
      ▼
vrm_ingest.py
      │
      │  INSERT INTO bronze.vrm_raw (UPSERT)
      ▼
Supabase: bronze.vrm_raw
      │
      ▼  (järgmine etapp)
dbt silver mudelid
```

---

## ELT põhimõte

| Etapp | Vastutav komponent |
|-------|-------------------|
| **Extract** — andmed tuuakse VRM API-st | `src/ingest/vrm_ingest.py` |
| **Load** — toored andmed kirjutatakse bronzesse muutmata kujul | `src/ingest/vrm_ingest.py` + Supabase |
| **Transform** — andmed puhastatakse ja rikastatatakse andmelaos | dbt mudelid (`silver`, `gold` kiht) |

---

## Victron VRM API

[Victron VRM](https://vrm.victronenergy.com/) on Victron Energy pilveplatvorm, mis kogub andmeid off-grid ja hübriidsüsteemidelt (inverterid, akumonitorid, laadijad jne).

### Kasutatav lõpp-punkt

```
GET https://vrmapi.victronenergy.com/v2/installations/{site_id}/diagnostics
```

**Autentimine:** päises `x-authorization: Token <VRM_API_TOKEN>`

### Miks just see lõpp-punkt?

`diagnostics` tagastab ühe päringuga **kõigi paigaldisega ühendatud seadmete hetkelised mõõtmised** — aku pinge, päikesepaneelide toodang, tarbimine jne. See on piisav, et salvestada bronzesse täielik hetkepilt, mida dbt hiljem transformeerib.

Kaalutud, kuid mitte kasutusele võetud lõpp-punktid:

| Lõpp-punkt | Kirjeldus | Miks ei kasutata |
|-----------|-----------|-----------------|
| `GET /installations/{id}/stats` | Ajaloolised agregeeritud andmed (tunni/päeva keskmised) | Agregeerimise teeb dbt — toored hetkeandmed on paindlikumad |
| `GET /installations/{id}/system-overview` | Seadmete inventar (mis riistvara on paigaldatud) | Ei ole analüütika jaoks vajalik |
| `GET /users/{id}/installations` | Kõik paigaldised kasutaja all | Paigaldis on fikseeritud (`VRM_SITE_ID`), mitut ei ole vaja |

### Vastuse struktuur

API tagastab JSON objekti, milles `records` massiiv sisaldab hetkelisi mõõtmisi kõigist süsteemiga ühendatud seadmetest. Tüüpilised väljad kirjes:

| Väli | Kirjeldus |
|------|-----------|
| `idDataAttribute` | Mõõtmistüübi unikaalne ID VRM-is |
| `description` | Inimloetav nimetus (nt „Battery voltage", „Solar power") |
| `rawValue` | Numbriline väärtus |
| `formattedValue` | Väärtus koos ühikuga tekstina |
| `unit` | Mõõtühik (V, W, % jne) |
| `Device` | Seade, millelt mõõtmine pärineb |
| `timestamp` | Mõõtmise ajamark |

Tegelik vastus sisaldab rohkem välju (nt `dbusPath`, `bitmask`, `dataAttributeEnumValues`) — kõik salvestatakse bronzesse muutmata kujul.

---

## Bronze tabel: `bronze.vrm_raw`

```sql
CREATE TABLE IF NOT EXISTS bronze.vrm_raw (
    id          BIGSERIAL    PRIMARY KEY,
    site_id     TEXT         NOT NULL,
    fetched_at  TIMESTAMPTZ  NOT NULL,
    endpoint    TEXT         NOT NULL,
    payload     JSONB        NOT NULL
);
```

| Veerg | Tüüp | Kirjeldus |
|-------|------|-----------|
| `site_id` | `TEXT` | VRM paigaldise ID |
| `fetched_at` | `TIMESTAMPTZ` | Täpne hetk (UTC), millal andmed toodi |
| `fetched_hour` | `TIMESTAMPTZ` | Tunni granulariteediga ajamark — kasutatakse upsert-i unikaalsuseks |
| `endpoint` | `TEXT` | API lõpp-punkt, praegu alati `diagnostics` |
| `payload` | `JSONB` | Kogu API vastus muutmata JSON-ina |

### Miks JSONB ja miks mitte lahti pakkida?

Kogu API vastus salvestatakse ühe JSONB veeruna — ühtegi välja ei filtreerrita ega teisendatagi bronze kihis. See tagab, et bronzes on alati täielik originaalandmestik, millele saab hiljem tagasi minna.

Väljade lahti pakkimine toimub dbt silver mudelites, kus SQL-iga eraldatakse ainult analüütika jaoks vajalikud väärtused:

```sql
jsonb_array_elements(payload->'records') ->> 'rawValue'  AS raw_value
jsonb_array_elements(payload->'records') ->> 'description' AS description
```

### UPSERT strateegia

Unikaalne indeks `(site_id, fetched_hour, endpoint)` — **üks rida ühe tunni, paigaldise ja lõpp-punkti kohta**. `fetched_hour` arvutatakse Pythonis (`fetched_at` minutid ja sekundid nullitakse) enne sisestamist. Kui Airflow käivitab sama tunni jooksul uuesti, kirjutatakse eelmine kirje üle. See väldib duplikaate ilma andmeid kaotamata.

---

## Konfigureerimine

| Muutuja | Kirjeldus |
|---------|-----------|
| `VRM_API_TOKEN` | VRM API ligipääsuvõti |
| `VRM_SITE_ID` | Paigaldise ID VRM portaalis |
| `SUPABASE_DB_HOST` | Andmebaasi host |
| `SUPABASE_DB_PORT` | Andmebaasi port |
| `SUPABASE_DB_NAME` | Andmebaasi nimi |
| `SUPABASE_DB_USER` | Andmebaasi kasutajanimi |
| `SUPABASE_DB_PASSWORD` | Andmebaasi parool |

Kui `VRM_API_TOKEN` või `VRM_SITE_ID` puudub, lõpetab moodul töö vaikimisi koodiga `0` — vajalik lokaalses arenduskeskkonnas, kus tõelisi võtmeid pole.

---

## Testimine

```bash
# Ühiktestid (mock — ei kutsu päriselt API-t ega andmebaasi)
pytest tests/ingest/test_vrm_ingest.py -v

# Käsitsi ühenduse kontroll päris võtmetega
python3 testing.py
```

| Klass | Mida testitakse |
|-------|-----------------|
| `TestFetchDiagnostics` | HTTP päring: õige URL, token päises, JSON vastus, HTTP vead, timeout |
| `TestUpsert` | SQL: INSERT bronzesse, ON CONFLICT klausel, parameetrite järjekord, commit |
| `TestMain` | Kogu voog: puuduvad muutujad → skip, edukas jooksmine, ühenduse sulgemine vea korral |

---

## Veahaldus

| Stsenaarium | Käitumine |
|-------------|-----------|
| `VRM_API_TOKEN` või `VRM_SITE_ID` puudub | Väljub koodiga `0`, logib hoiatuse |
| VRM API tagastab HTTP vea (4xx/5xx) | `requests.HTTPError` → Airflow üritab uuesti |
| Võrgu timeout | `requests.Timeout` → Airflow üritab uuesti |
| Andmebaasiühendus ebaõnnestub | Erand levib → Airflow uuesti; ühendus suletakse `try/finally` blokis |

DAG-is on seadistatud `retries=2`, `retry_delay=5min`.

---

## Seotud failid

| Fail | Kirjeldus |
|------|-----------|
| `src/ingest/vrm_ingest.py` | Mooduli lähtekood |
| `airflow/dags/dag_vrm_ingest.py` | Airflow DAG |
| `sql/003_bronze_vrm_raw.sql` | Bronze tabeli loomine |
| `tests/ingest/test_vrm_ingest.py` | Ühiktestid |
