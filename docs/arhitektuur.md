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
    gha[GitHubActionsCron] --> ingestLayer
    gha --> silver
    gha --> forecastJob
```

## Andmeallikad

- Victron VRM API: telemeetriaandmed 
- Open-Meteo API: ilmavaatlused/prognoosid

## Tehnilised kokkulepped

- Ajatsoon: UTC
- Granulaarsus: 1h
- Võtmed: `site_id + timestamp_utc`
- Idempotentsus: upsert (`ON CONFLICT DO UPDATE`)
- Kihid: `bronze -> silver -> gold`
