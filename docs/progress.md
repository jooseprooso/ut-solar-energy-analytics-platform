# Progressi logi

## Nädal 1

- Plaan: tööjaotus, arhitektuur.md sisustamine, repositoorium
- Valmis: infrastruktuur (Hetzner VM, Airflow 3, Postgres, dbt Core), repositooriumi struktuur

## Nädal 2

- Plaan: VRM ja Meteo valmendus MVP, dbt silver + gold mudelid + min 3 DQ testi
- Valmis:
  - VRM andmed ingestion:
    - VRM ingest DAG (tunniline sisselugemine, bronze.vrm_raw, upsert-strateegia)
    - VRM ajalooliste andmete backfill implementeeritud
  - Meteo andmed ingestion:
    - Meteo ingest DAG eraldatud iseseisvaks pipeline'iks, lisatud korduspäringute loogika
    - Meteo backfill DAG ajalooliste ilmaandmete laadimiseks
  - Transformeerimine (dbt)
    - dbt silver kiht: stg_meteo_hourly, stg_vrm_energy_snapshot, stg_vrm_stats_snapshot
    - dbt gold kiht: ajaline dimensioon, asukoha dimensioon, meteo faktitabel, VRM energiafaktitabel, meteo analüütikamart, päikeseenergia tootlikkuse mart (omavarustuse määr, omakasutusmäär, tootlikkuse suhtarv)
    - Manuaalne dbt DAG seemnefailide, mudelite ja testide käsitsi käivitamiseks
    - 60 andmekvaliteedi (dbt) testi
  - Infrastruktuuri parandused: nginx seadistus, Airflow kasutaja loomine, inkrementaalne loogika
  - Grafana seadistatud ja esimene vaade valmis


## Nädal 3

- Plaan:
  - Grafana vaadete tegemine
  - Prognoosimudeli arendamine (ajaloolised VRM + meteo andmed aluseks)
- Valmis:
  - PV prognoosimudel (Ridge regressioon, scikit-learn):
  - dbt mart_forecast_accuracy_daily — päevased KPI-d:
    - MAE (kWh), tegeliku ja prognoosi erinevus (kWh), erinevus (%)
    - DQ testid: not_null, abs_error_kwh vahemikus 0–200
  - Grafana Solar KPI Overview dashboard (3 paneeli):
    - MAE (kWh) stat paneel
    - Tegelik vs prognoos aegrida
    - Prognoosiviga (%) stat paneel
  - Forecast DAG-id:
    - `solar_analytics_hourly` — live prognoos + accuracy mart refresh
    - `solar_analytics_backtest_daily` — walk-forward backtest + accuracy mart (Grafana KPI-d)
    - pipeline_smoke_test jäi muutmata
  - Dokumentatsioon: arhitektuur.md andmevoo ja DQ testide sektsioonid uuendatud
- Järgmised sammud:
  - Meteo ingest laiendada forecast_days=2 jaoks (homse ilmaprognoos)
  - Demo video salvestamine
  - README finaalversioon
