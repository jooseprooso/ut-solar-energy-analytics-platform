# Arhitektuuriskeem

```mermaid
flowchart LR
    vrmApi[VictronVRMAPI] --> ingestLayer[PythonIngestion]
    meteoApi[OpenMeteoAPI] --> ingestLayer
    ingestLayer --> bronze[(SupabaseBronze)]
    bronze --> silver[dbtSilverModels]
    silver --> gold[dbtGoldModels]
    gold --> grafana[GrafanaDashboard]
    gold --> forecastJob[PythonForecastJob]
    forecastJob --> forecastTable[(GoldForecastTable)]
    forecastTable --> grafana
    airflow[Airflow3OnHetznerVM] --> ingestLayer
    airflow --> silver
    airflow --> forecastJob
    gha[GitHubActionsCIOnly] --> silver
```

## Andmeallikad

- Victron VRM API: telemeetriaandmed 
- Open-Meteo API: ilmavaatlused/prognoosid

## Tehnilised kokkulepped

- Ajatsoon: UTC
- Andmete värskendamise intervall: 1h
- Võtmed: `site_id + timestamp_utc`
- Idempotentsus: upsert (`ON CONFLICT DO UPDATE`)
- Kihid: `bronze -> silver -> gold`
- Orkestreerimine: Airflow 3 (peamine scheduler), GitHub Actions ainult CI/manual check

## Keskse VM suurus (Hetzner)

### Miinimum (tootmiskatse / low load)
- 2 vCPU
- 4 GB RAM
- 40 GB SSD

### Soovituslik (stabiilsem tiimitöö)
- 4 vCPU
- 8 GB RAM
- 80 GB SSD

### Miks soovituslik
- Airflow webserver + scheduler + metadata DB + dbt jooksud vajavad tipukoormusel rohkem mälu.
- 8 GB jätab puhvri logidele, retry-dele ja paralleelsetele taskidele.
