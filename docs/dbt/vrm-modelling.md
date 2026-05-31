# VRM andmemodelleerimine (silver → gold)

Käesolev dokument selgitab, kuidas VRM bronze-kihi toored andmed transformeeritakse
silver- ja gold-kihtideks ning millistest kaalutlustest lähtuti disainiotsuste tegemisel.

Ingest-kihi (bronze) kirjeldus: [`docs/ingest/vrm-ingest.md`](../ingest/vrm-ingest.md)

---

## Andmevoog

```
bronze.vrm_raw          (JSONB blob, 343 kirjet tunni kohta)
        │
        ▼  stg_vrm_energy_snapshot  (silver)
silver.stg_vrm_energy_snapshot   (25 tüpiseeritud veergu, 1 rida tunni kohta)
        │
        ▼  fct_vrm_energy_hourly   (gold)
gold.fct_vrm_energy_hourly        (faktitabel dimensioonivõtmetega)
        │
        ├──── mart_meteo_hourly    (gold, olemasolev)
        ▼
gold.mart_solar_performance_hourly  (analüütikamart, VRM + ilm koos)
```

---

## Silver kiht: `stg_vrm_energy_snapshot`

### Graanulaarsus

Bronze: **üks rida = üks JSONB-plokk** (site_id + tund), mis sisaldab 343 kirjet massiivis.  
Silver: **üks rida = üks tund** (site_id + fetched_hour) — sama graanulaarsus, erinev struktuur.

Bronze ei muutu — silver lahti pakib selle laia formaati.

### JSONB lahti pakkimise strateegia

VRM API `diagnostics` lõpp-punkt tagastab kõik mõõtmised ühe tasase massiivina:

```json
{
  "records": [
    { "code": "bs",  "rawValue": 90.0,     "Device": "System overview" },
    { "code": "P",   "rawValue": 2002.0,   "Device": "System overview" },
    { "code": "SOH", "rawValue": 100.0,    "Device": "Battery Monitor" },
    ...
  ]
}
```

Kasutusele võetud lähenemine on **kaheastmeline pööramine (explode → pivot)**:

```sql
-- 1. Laienda: 1 rida (site_id, tund) → 343 rida (üks iga 'code' kohta)
expanded AS (
    SELECT site_id, fetched_hour, fetched_at,
           jsonb_array_elements(payload -> 'records') AS record
    FROM bronze.vrm_raw
),

-- 2. Pööra: 343 rida → 1 rida laia formaadiga
pivoted AS (
    SELECT
        site_id,
        fetched_hour,
        MAX(CASE WHEN record->>'code' = 'bs' THEN (record->>'rawValue')::numeric END) AS battery_soc_pct,
        MAX(CASE WHEN record->>'code' = 'P'  THEN (record->>'rawValue')::numeric END) AS pv_l1_w,
        ...
    FROM expanded
    GROUP BY site_id, fetched_hour
)
```

**Miks see lähenemine?**

| Alternatiiv | Miks ei kasutata |
|-------------|-----------------|
| `jsonb_path_query` konkreetsete teede järgi | Sõltub massiivis asukoha fikseeritusest — VRM-i vastuse struktuur pole garanteeritud |
| Korreleeritud alamkäsud (üks päring iga `code` kohta) | Väga paljusõnaline, halb jõudlus N-kordse skaneerimise tõttu |
| `crosstab()` | Nõuab `tablefunc` laiendust, vähem loetav |
| Pööramine Python-ingest-is enne bronzesse salvestamist | Rikuks ELT põhimõtet — bronze peab hoidma originaalandmeid muutmata |

`MAX(CASE WHEN ...)` + `GROUP BY` on standardne SQL, laialt tuntud muster ja töötab
sujuvalt ka siis, kui mõni `code` mõnel tunnil puudub (tagastab `NULL`).

### Millised `code`-väärtused valiti ja miks

Bronzes on 343 kirjet tunni kohta. Suurem osa neist on Gateway seadme konfiguratsioonid
(firmware versioon, IP-aadressid, ESS seaded jne), need muutuvad harva ja pole
ajaloolise analüütika jaoks huvitavad.

Silver mudel eraldab ainult **ajas muutuvad mõõtmised**, mis vastavad äriküsimustele:

| Kategooria | `code`-id | Allikaseade |
|------------|-----------|-------------|
| Energiavood (kWh perioodil) | `Pb`, `Pc`, `Gb`, `Gc`, `Bc` | System overview |
| PV hetkvõimsus faasiti (W) | `P`, `P2`, `P3` | System overview |
| Tarbimine faasiti (W) | `a1`, `a2`, `a3` | System overview |
| Aku seisund | `bs`, `bp`, `bv`, `bT`, `bst` | System overview |
| Aku tervis | `SOH`, `dH21`, `dH22` | Battery Monitor |
| Süsteemi olek | `ss`, `Agl`, `pS` | System overview / PV Inverter |

Tekstiliste olekuväljade puhul (nt `bst` → "charging") kasutatakse `formattedValue`,
numbriliste puhul `rawValue`.

### Inkrementaalne strateegia

`stg_vrm_energy_snapshot` ja `fct_vrm_energy_hourly` on inkrementaalsed mudelid
(`delete+insert` strateegia, unikaalvõti `vrm_snapshot_key` / `vrm_hourly_key`).

**Miks `delete+insert`, mitte `append` või `merge`?**

| Strateegia | Sobib? | Põhjus |
|------------|--------|--------|
| `append` | Ei | Airflow retry sama tunni sees tekitab bronze'i teise rea sama (site_id, fetched_hour) kohta — `append` lisaks duplikaadi |
| `delete+insert` | Jah | Kustutab eelnevad read unikaalvõtme järgi, siis INSERT — käsitleb retry-d ja osaandmeid korrektselt |
| `merge` | Alternatiiv | Töötaks Supabase PostgreSQL 15-l, kuid `delete+insert` on järjepidev olemasoleva `fct_meteo_hourly` mudeliga |

Inkrementaalfilter: `fetched_at > MAX(fetched_at) - 1 tund` — 1-tunnine tagasivaatamisaken
tagab, et osaliste andmetega tund kirjutatakse üle, kui Airflow jookseb sama tunni sees uuesti.

Bronze'i graanulaarsus on juba (site_id, fetched_hour, endpoint) — silver töötleb
täpselt neid samu kirjeid, lihtsalt muutab nende kuju.

---

## Gold kiht: `fct_vrm_energy_hourly`

### Disainiotsus: üks faktitabel vs mitu

Kaaluti kahte lähenemist:

**Variant A — üks faktitabel kõigi mõõdikutega** (valitud)  
**Variant B — eraldi faktitabelid seadmete kaupa** (nt `fct_vrm_battery_hourly`, `fct_vrm_pv_hourly`)

Valiti variant A, sest:
- Kõigil mõõdikutel on **sama graanulaarsus** (site_id + tund)
- Praegu on ainult **üks objekt** — eraldi tabelite haldamise keerukus pole põhjendatud
- Aku tervise mõõdikud (SOH, laetud/tühja kWh delta) vastavad samadele äriküsimustele
  kui energiavood — need on omavahel seotud, mitte eraldiseisvad teemad
- Lisatabelit saab alati hiljem eraldada, kui tekib konkreetne vajadus

### Faktide tüübid (Kimball)

Kimball eristab kolme fakti tüüpi — oluline teada, et vältida valesid agregatsioone:

| Tüüp | Veerud | Lubatud agregatsioon |
|------|--------|---------------------|
| **Täielikult aditiivsed** (kWh energiavood) | `pv_to_battery_kwh`, `pv_to_consumers_kwh`, `grid_to_battery_kwh`, `grid_to_consumers_kwh`, `battery_to_consumers_kwh`, `pvinverter_energy_delta_kwh`, `battery_discharged_kwh_delta`, `battery_charged_kwh_delta` | SUM üle aja ja objektide |
| **Pooladitiivsed** (hetkväärtused) | `pv_total_w`, `load_total_w`, `battery_soc_pct`, `battery_power_w`, `battery_voltage_v`, `battery_temp_c`, `battery_soh_pct` | AVG üle aja, mitte SUM |
| **Mitteaditiivsed** (olekud) | `battery_state`, `system_state`, `grid_alarm`, `pvinverter_status` | Loendamine, mitte agregatsioon |

Äriküsimused (omavarustuse määr, omakasutusmäär, tootlikkuse suhtarv) arvutatakse
mart-kihis aditiivsete kWh-faktide põhjal — vt allpool.

### Dimensioonid

`fct_vrm_energy_hourly` viitab kahele dimensioonile:

- `time_key → dim_time` — aastaaeg, päevaosa, kellaaeg
- `location_key → dim_location` — geograafiline asukoht (koordinaadid `vrm_sites` seedist)

`location_key` genereeritakse `vrm_sites` seedi koordinaatidest, mis seob VRM `site_id`
geograafilise asukohaga — see võimaldab tulevikus mitme objekti toetamist ja
VRM-andmete ühendamist meteo-andmetega asukoha järgi.

---

## Gold kiht: `mart_solar_performance_hourly`

Analüütikamart ühendab VRM energiamõõdikud Open-Meteo ilmaandmetega:

```
fct_vrm_energy_hourly  ──┐
                          ├── LEFT JOIN timestamp_utc järgi ──► mart_solar_performance_hourly
mart_meteo_hourly      ──┘
dim_time (season, is_daytime)
```

**Miks LEFT JOIN?**  
Meteo-ingest ja VRM-ingest on sõltumatud — kui ilmateenuse API oli maas, pole vastaval
tunnil ilmaandmeid, kuid VRM energiamõõdikud on olemas. LEFT JOIN tagab, et VRM-andmed
ei kao meteo katkestuse tõttu.

**Põhi-KPI valemid** (kõik kasutavad ainult kWh aditiivseid fakte):

| KPI | Valem |
|-----|-------|
| Omavarustuse määr | `(pv_to_consumers_kwh + battery_to_consumers_kwh) / (pv_to_consumers_kwh + battery_to_consumers_kwh + grid_to_consumers_kwh)` |
| Omakasutusmäär | `(pv_to_consumers_kwh + pv_to_battery_kwh) / pvinverter_energy_delta_kwh` |
| Tootlikkuse suhtarv | `pvinverter_energy_delta_kwh / (shortwave_radiation_wm2 × paigaldise_võimsus_kw)` |

Hooajaline analüüs ja pilvisuse mõju kasutavad `season`, `is_daytime`, `cloud_cover_pct`
dimensioonide kaudu — kõik saadaval selles martis.

---

## Edasiarendused

**Indeksid**

dbt-postgres toetab `indexes` konfiguratsiooni inkrementaalsetes mudelites. Praegu
indekseid ei kasutata, kuna andmemaht on väike — ühe objekti tunniandmed kasvavad
~8 760 reani aastas, millel PostgreSQL teeb täisskaneerimise millisekunditega.

Indeksid (`timestamp_utc`, `site_id` veergudele) tasub lisada, kui:
- objekte lisandub mitu ja tabelid kasvavad kümnete tuhandete ridade suuruseks, või
- Grafana päringuaeg muutub märgatavaks.

**Snapshots**

`bronze.vrm_raw` salvestab iga tunni eraldi reana, seega ajalugu on bronzes olemas
ja snapshotsid pole vajalikud. Erandiks on Gateway konfiguratsioonimõõdikud (ESS
miinimum SOC, DESS režiim, firmware), mille muutuste jälgimiseks sobiks tulevikus
eraldi `stg_vrm_site_config` snapshot.

**Mitu objekti**

`vrm_sites` seed ja `site_id` veerg on ette valmistatud mitme objekti jaoks.
Lisandamiseks piisab uuest reast seedis ja `VRM_SITE_ID` loopimisest ingestis.
