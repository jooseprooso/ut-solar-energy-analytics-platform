# Off-Grid Päikesejaama Analüütika Platvorm

Off-grid paigaldise telemeetria ja ilmaprognoosi analüütikaplatvorm.

## Äriküsimus

Kuidas mõjutavad ilmastikutingimused off-grid paigaldise energiatootmist ning kui
tapselt on voimalik prognoosida jargmise paeva paikeseenergia tootmist?

## Võtmemõõdikud

- Täpsustamisel

## Tehnoloogiavirn

- Replikatsioon: Python
- Transformatsioon + andmekvaliteet: dbt Core
- Andmeladu: Supabase (Postgres)
- Orkestreerimine: GitHub Actions (cron)
- Näidikulaud: Grafana Cloud
- Prognoos: Pythoni töö

## Repositooriumi arhitektuur

```text
├─ .github/workflows/
├─ Dockerfile
├─ dbt/
│  ├─ models/
│  │  ├─ silver/
│  │  └─ gold/
│  ├─ dbt_project.yml
│  └─ profiles.yml
├─ docker-compose.yml
├─ docs/
├─ sql/
├─ src/
│  ├─ ingest/
│  └─ forecast/
├─ .env.example
└─ requirements.txt
```

## Kohalikus masinas käivitamine

1. Loo `.env` fail `.env.example` põhjal.
2. Ehita konteiner:
   - `docker compose build`
3. Kontrolli dbt paigaldust konteineris:
   - `docker compose run --rm dev dbt --version`
4. Kontrolli ühendust Supabase'iga:
   - `docker compose run --rm dev dbt debug`
5. Kaivita Python skript konteineris (naide):
   - `docker compose run --rm dev python --version`